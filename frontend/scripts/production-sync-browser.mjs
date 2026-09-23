// Transparent Unix-socket transport adapter, not mocked application responses.
import {chromium, expect} from '@playwright/test';
import {spawn,execFileSync} from 'node:child_process';
let input='';for await(const chunk of process.stdin)input+=chunk;
const config=JSON.parse(input);input='';
if(!/^netbox-sync-probe-test-[0-9a-f]+$/.test(config.project)||!/^[0-9a-f]{64}$/.test(config.api)||!/^full-(esxi|proxmox)$/.test(config.source))throw Error('Unscoped browser target');
const client=`import http.client,socket,sys,json,base64,time
class UnixHTTP(http.client.HTTPConnection):
 def connect(self):
  self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);self.sock.settimeout(310);self.sock.connect('/run/netbox-sync-http/api.sock')
p=json.load(sys.stdin);c=UnixHTTP('sync.example.test',timeout=310)
h=p['headers'];h['host']='sync.example.test';h['x-forwarded-proto']='https'
for key in ('content-length','accept-encoding','connection'):h.pop(key,None)
c.request(p['method'],p['path'],p['body'],h)
if p.get('drop_response'):
 run_id=json.loads(p['body'])['run_id']
 for _ in range(150):
  check=UnixHTTP('sync.example.test',timeout=5);check.request('GET','/api/v1/runs/'+run_id,headers=h)
  result=check.getresponse();data=json.loads(result.read());check.close()
  if result.status==200 and data.get('status')=='RUNNING' and data.get('plan_digest'):break
  time.sleep(.1)
 else:raise RuntimeError('Controlled request was not durably accepted')
 c.close();print(json.dumps({'dropped':True}));sys.exit(0)
r=c.getresponse()
print(json.dumps(dict(status=r.status,headers=dict(r.getheaders()),body=base64.b64encode(r.read()).decode())))`;
function transport(payload){return new Promise((resolve,reject)=>{
 const child=spawn('docker',['exec','-i','--user','10001',config.api,'python','-c',client],{stdio:['pipe','pipe','pipe']});let output='';
 child.stdout.on('data',data=>output+=data);child.stderr.resume();child.on('error',reject);
 child.on('close',code=>{if(code)return reject(Error('Unix transport failed'));try{resolve(JSON.parse(output));}catch{reject(Error('Unix response invalid'));}});
 child.stdin.end(JSON.stringify(payload));
});}
const browser=await chromium.launch({headless:true});let page;
try{
 const context=await browser.newContext({locale:'en-US'});const split=config.cookie.indexOf('=');
 await context.addCookies([{name:config.cookie.slice(0,split),value:config.cookie.slice(split+1),url:'https://sync.example.test',secure:true,httpOnly:true,sameSite:'Strict'}]);config.cookie='';
 page=await context.newPage();const writes=[];let applyHeaders;
 function ownedContainer(name){
  const label=execFileSync('docker',['inspect',name,'--format','{{index .Config.Labels "com.docker.compose.project"}}'],{encoding:'utf8'}).trim();
  if(label!==config.project)throw Error('Foreign test resource');return name;
 }
 function fixtureRelease(){
  execFileSync('docker',['exec',ownedContainer(config.project+'-endpoint'),'python','-c',"import requests; requests.post('https://esxi.probe.test:8443/fixture/release-write',verify='/fixture/server.crt',timeout=5).raise_for_status()"],{stdio:'pipe'});
 }
 async function storedRun(id){
  const value=await transport({path:'/api/v1/runs/'+id,method:'GET',headers:applyHeaders,body:null});
  return value.status===200?JSON.parse(Buffer.from(value.body,'base64').toString()):null;
 }
 await page.route('https://sync.example.test/**',async route=>{
  const req=route.request();const path=new URL(req.url()).pathname+new URL(req.url()).search;
  if(req.method()==='POST' && (path.endsWith('/sync-confirmations')||path.endsWith('/sync')))writes.push({path,body:req.postDataJSON()});
  const headers=await req.allHeaders();
  const drop=config.drop_response && req.method()==='POST' && path.endsWith('/sync');
  if(drop)applyHeaders=headers;
  const response=await transport({path,method:req.method(),headers,body:req.postData(),drop_response:drop});
  if(drop){if(!response.dropped)throw Error('Expected disconnected HTTP client');await route.abort('connectionclosed');return;}
  delete response.headers['Content-Length'];delete response.headers['Transfer-Encoding'];
  await route.fulfill({status:response.status,headers:response.headers,body:Buffer.from(response.body,'base64')});
 });
 await page.goto('https://sync.example.test/sources/'+config.source+'/sync');
 if(config.uncertain){
  await expect(page.getByRole('button',{name:'Rebuild plan',exact:true})).toBeDisabled({timeout:30000});
  await expect(page.getByRole('alert').first()).toContainText('previous synchronization');
  await expect(page.getByText('Plan ready for review.',{exact:true})).toHaveCount(0);
  await expect(page.getByText('Plan permits sync',{exact:true})).toHaveCount(0);
  await expect(page.getByRole('button',{name:'Review and confirm sync'})).toBeDisabled();
  const readOnly=page.getByRole('button',{name:'Run discovery',exact:true});
  await expect(readOnly).toBeEnabled();
  const started=page.waitForResponse(r=>r.url().endsWith('/operations/discovery')&&r.request().method()==='POST');
  await readOnly.click();
  const discoveryResponse=await started;if(discoveryResponse.status()!==202)throw Error('Read-only start failed');
  await expect(readOnly).toBeEnabled({timeout:90000});
  await expect(page.getByRole('alert').first()).toContainText('previous synchronization');
  await expect(page.getByRole('button',{name:'Review and confirm sync'})).toBeDisabled();
  if(writes.length)throw Error('Uncertain source attempted a write');
  await page.screenshot({path:'frontend/test-results/production-sync-uncertain.png',fullPage:true});
 }else{
 await expect(page.getByRole('button',{name:'Rebuild plan',exact:true})).toBeEnabled({timeout:30000});
 await page.getByRole('button',{name:'Rebuild plan',exact:true}).click();
 await expect(page.getByText('Plan ready for review.',{exact:true})).toBeVisible({timeout:90000});
 await page.getByRole('region',{name:'Review plan'}).getByRole('button',{name:'Review and confirm sync'}).click();
 await page.getByRole('dialog').getByRole('button',{name:'Sync to NetBox',exact:true}).click();
 if(config.drop_response){
  await expect.poll(()=>writes.filter(row=>row.path.endsWith('/sync')).length,{timeout:15000}).toBe(1);
  const sent=writes.find(row=>row.path.endsWith('/sync')).body;
  const prepared=writes.find(row=>row.path.endsWith('/sync-confirmations')).body;
  await expect.poll(async()=>{const run=await storedRun(sent.run_id);return run?.status==='RUNNING'&&run.plan_digest===prepared.plan_digest;},{timeout:20000}).toBe(true);
  // The HTTP client has disconnected while the real apply child is blocked in
  // a controlled remote request. Browser reload must not replay the POST.
  await page.reload();
  await expect(page.locator('a[href="/runs/'+sent.run_id+'"]').first()).toBeVisible({timeout:15000});
  await expect(page.getByRole('button',{name:'Review and confirm sync'})).toBeDisabled();
  if((await storedRun(sent.run_id))?.status!=='RUNNING')throw Error('Run did not survive connection loss and reload');
  fixtureRelease();
  await expect.poll(async()=>(await storedRun(sent.run_id))?.status,{timeout:90000}).toBe('SUCCEEDED');
  const terminal=await storedRun(sent.run_id);
  if(terminal.plan_digest!==prepared.plan_digest)throw Error('Wrong durable plan digest');
  execFileSync('docker',['restart',ownedContainer(config.project+'-apply-worker')],{stdio:'pipe',timeout:45000});
  await page.reload();
  await expect(page.getByText('Stored run result is available.',{exact:false})).toBeVisible({timeout:20000});
  await expect(page.locator('a[href="/runs/'+sent.run_id+'"]').first()).toBeVisible();
  await expect(page.getByRole('button',{name:'Review and confirm sync'})).toBeDisabled();
  if(writes.filter(row=>row.path.endsWith('/sync')).length!==1)throw Error('Apply replayed after response loss/restart');
  console.log('PASS real disconnected HTTP apply: RUNNING survives reload, matching durable success, worker restart, no repeated POST');
 }else await expect(page.getByRole('heading',{name:'Sync completed',exact:true})).toBeVisible({timeout:90000});
 const prepare=writes.find(row=>row.path.endsWith('/sync-confirmations'));const apply=writes.find(row=>row.path.endsWith('/sync'));
 if(!prepare?.body.operation_id||prepare.body.operation_id!==apply?.body.operation_id)throw Error('Generation mismatch');
 await page.screenshot({path:'frontend/test-results/production-'+config.source+'-success.png',fullPage:true});
 console.log('PASS production browser '+config.source);
}
}catch(error){if(page)await page.screenshot({path:'frontend/test-results/production-'+config.source+'-failure.png',fullPage:true});throw error;}finally{await browser.close();}
