// Transparent Unix-socket transport adapter, not mocked application responses.
import {chromium, expect} from '@playwright/test';
import {spawn} from 'node:child_process';
let input='';for await(const chunk of process.stdin)input+=chunk;
const config=JSON.parse(input);input='';
if(!/^netbox-sync-probe-test-[0-9a-f]+$/.test(config.project)||!/^[0-9a-f]{64}$/.test(config.api)||!/^full-(esxi|proxmox)$/.test(config.source))throw Error('Unscoped browser target');
const client=`import http.client,socket,sys,json,base64
class UnixHTTP(http.client.HTTPConnection):
 def connect(self):
  self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);self.sock.settimeout(310);self.sock.connect('/run/netbox-sync-http/api.sock')
p=json.load(sys.stdin);c=UnixHTTP('sync.example.test',timeout=310)
h=p['headers'];h['host']='sync.example.test';h['x-forwarded-proto']='https'
for key in ('content-length','accept-encoding','connection'):h.pop(key,None)
c.request(p['method'],p['path'],p['body'],h);r=c.getresponse()
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
 page=await context.newPage();const writes=[];
 await page.route('https://sync.example.test/**',async route=>{
  const req=route.request();const path=new URL(req.url()).pathname+new URL(req.url()).search;
  if(req.method()==='POST' && (path.endsWith('/sync-confirmations')||path.endsWith('/sync')))writes.push({path,body:req.postDataJSON()});
  const response=await transport({path,method:req.method(),headers:await req.allHeaders(),body:req.postData()});
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
  if(writes.length)throw Error('Uncertain source attempted a write');
  await page.screenshot({path:'frontend/test-results/production-sync-uncertain.png',fullPage:true});
 }else{
 await expect(page.getByRole('button',{name:'Rebuild plan',exact:true})).toBeEnabled({timeout:30000});
 await page.getByRole('button',{name:'Rebuild plan',exact:true}).click();
 await expect(page.getByText('Plan ready for review.',{exact:true})).toBeVisible({timeout:90000});
 await page.getByRole('region',{name:'Review plan'}).getByRole('button',{name:'Review and confirm sync'}).click();
 await page.getByRole('dialog').getByRole('button',{name:'Sync to NetBox',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Sync completed',exact:true})).toBeVisible({timeout:90000});
 const prepare=writes.find(row=>row.path.endsWith('/sync-confirmations'));const apply=writes.find(row=>row.path.endsWith('/sync'));
 if(!prepare?.body.operation_id||prepare.body.operation_id!==apply?.body.operation_id)throw Error('Generation mismatch');
 await page.screenshot({path:'frontend/test-results/production-'+config.source+'-success.png',fullPage:true});
 console.log('PASS production browser '+config.source);
}
}catch(error){if(page)await page.screenshot({path:'frontend/test-results/production-'+config.source+'-failure.png',fullPage:true});throw error;}finally{await browser.close();}
