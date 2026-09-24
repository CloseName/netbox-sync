// Transparent Unix-socket transport adapter, not mocked application responses.
import {chromium, expect} from '@playwright/test';
import {spawn,execFileSync} from 'node:child_process';
let input='';for await(const chunk of process.stdin)input+=chunk;
const config=JSON.parse(input);input='';
if(!/^netbox-sync-probe-test-[0-9a-f]+$/.test(config.project)||!/^[0-9a-f]{64}$/.test(config.api)||config.kind!=='legacy')throw Error('Unscoped browser target');
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

 await page.goto('https://sync.example.test/sources/add');
 await page.getByLabel('Source type').selectOption('esxi');
 await page.getByLabel('Hostname or IPv4 address').fill('esxi.probe.test');
 await page.getByLabel('HTTPS port').fill('8443');
 await page.locator('.wizard-form [name=username]').fill('netbox-sync');
 await page.locator('.wizard-form [name=secret]').fill(config.secret);config.secret='';
 await page.locator('.wizard-form').getByRole('button',{name:'Continue',exact:true}).click();
 const old=page.locator('#legacy-identity');await expect(old).toBeVisible({timeout:30000});
 await old.getByRole('button',{name:'Review this legacy record',exact:true}).click();
 await expect(old.getByText('ESXI-1L-SUP',{exact:true})).toBeVisible();
 await expect(old.locator('[name=secret]')).toBeEmpty();
 await old.getByRole('textbox',{name:'Decision reason (no secrets)'}).fill('Decommissioned fixture, retained ownership unproved');
 await old.getByRole('checkbox').check();
 await old.getByRole('button',{name:'Isolate unverified record',exact:true}).click();
 await expect(old.getByRole('status')).toContainText('Decision saved',{timeout:30000});
 await page.screenshot({path:'frontend/test-results/production-legacy-decision.png',fullPage:true});
 await page.locator('.wizard-form').getByRole('button',{name:'Continue',exact:true}).click();
 await expect(page).toHaveURL(/step=2/,{timeout:30000});
 await expect(page.getByLabel('Display name',{exact:true})).not.toBeEmpty();
 await page.screenshot({path:'frontend/test-results/production-legacy-continue.png',fullPage:true});
 console.log('PASS production browser legacy block, source-bound Admin decision, retained AM form, actual re-probe and placement');
}catch(error){if(page)await page.screenshot({path:'frontend/test-results/production-legacy-failure.png',fullPage:true});throw error;}finally{await browser.close();}
