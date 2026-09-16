// Transparent Unix-socket transport adapter, not mocked application responses.
import {chromium, expect} from '@playwright/test';
import {spawn} from 'node:child_process';
let input='';for await(const chunk of process.stdin)input+=chunk;
const config=JSON.parse(input);input='';
if(!/^netbox-sync-probe-test-[0-9a-f]+$/.test(config.project)||!/^[0-9a-f]{64}$/.test(config.api))throw Error('Unscoped browser target');
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
const browser=await chromium.launch({headless:true});
let stage="start";let page;
try {
 const context=await browser.newContext({locale:'en-US'}), split=config.cookie.indexOf('=');
 await context.addCookies([{name:config.cookie.slice(0,split),value:config.cookie.slice(split+1),url:'https://sync.example.test',secure:true,httpOnly:true}]);
 page=await context.newPage();
 await page.route('https://sync.example.test/**',async route=>{
  const req=route.request(),url=new URL(req.url());
  const response=await transport({path:url.pathname+url.search,method:req.method(),headers:await req.allHeaders(),body:req.postData()});
  delete response.headers['Content-Length'];delete response.headers['Transfer-Encoding'];
  await route.fulfill({status:response.status,headers:response.headers,body:Buffer.from(response.body,'base64')});
 });
 stage='settings';await page.goto('https://sync.example.test/settings');
 await expect(page.getByRole('heading',{name:'Corporate directory',exact:true})).toBeVisible();
 stage='check';await page.getByRole('button',{name:'Check configuration',exact:true}).click();
 await expect(page.getByRole('button',{name:'Save settings',exact:true})).toBeEnabled({timeout:20000});
 stage='save';await page.getByRole('button',{name:'Save settings',exact:true}).click();
 await expect(page.getByRole('status')).toContainText('Saved.',{timeout:20000});
 await page.screenshot({path:'frontend/test-results/production-ldap-settings.png',fullPage:true});
 for(const role of ['viewer','operator','admin']) {
  stage='logout-'+role;await page.getByRole('button',{name:'Sign out',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Sign in',exact:true})).toBeVisible();
  stage='login-'+role;await page.locator('select[name=provider]').selectOption('ldap');
  await page.locator('input[name=username]').fill(role);
  await page.locator('input[name=password]').fill(config.password);
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await expect(page.getByRole('button',{name:'Sign out',exact:true})).toBeVisible({timeout:20000});
  stage='navigation-'+role;
  if(role==='admin')await expect(page.getByRole('link',{name:'Settings',exact:true}).first()).toBeVisible();
  else await expect(page.getByRole('link',{name:'Settings',exact:true})).toHaveCount(0);
  await page.goto('https://sync.example.test/sources');
  if(role==='admin')await expect(page.getByRole('link',{name:'Add Source',exact:true}).first()).toBeVisible();
  else await expect(page.getByRole('link',{name:'Add Source',exact:true})).toHaveCount(0);
  await page.screenshot({path:'frontend/test-results/production-ldap-'+role+'.png',fullPage:true});
 }
 config.password='';console.log('PASS production browser LDAP settings/test/save and each role sign-in');
} catch { if(page)await page.screenshot({path:'frontend/test-results/production-ldap-failure.png',fullPage:true}); throw Error('Production LDAP browser stage '+stage+' failed; sensitive details suppressed'); }
finally { await browser.close(); }
