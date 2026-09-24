import {test,expect} from '@playwright/test';
import {randomUUID} from 'node:crypto';
import {source,diagnostics} from '../tests/fixtures.mjs';
import {setLanguage} from './menu-helper';
import {selectPlacement,catalogRow,previewResult} from './source-placement-fixture';

async function fixture(page:any,role='admin',provider='esxi',failure='',hostId='host-a'){
  const permissions=['source.read','run.read','diagnostics.read',...(role==='viewer'?[]:['source.register','source.probe','source.plan','source.apply']),...(role==='admin'?['source.remove','source.configure','catalog.create','policy.read','policy.write','bootstrap.manage','identity.manage']:[])];
  const writes:string[]=[];let registered:any=null,fail=failure;
  await page.route('**/api/v1/**',async(route:any)=>{
    const req=route.request(),path=new URL(req.url()).pathname;
    if(path==='/api/v1/registration-attempts')return route.fulfill({json:{attempts:[]}});
    if(path==='/api/v1/auth/me')return route.fulfill({json:{principal_id:'fixture-user',username:role,role,provider:'local',permissions}});
    if(path==='/api/v1/bootstrap')return route.fulfill({json:{revision:1,status:'READY',url:'https://netbox.example.test',completed:true,read_token_present:true,apply_token_present:true,safe_code:null,checks:[],validated_at:1}});
    if(path==='/api/v1/teams')return route.fulfill({json:{version:1,revision:1,teams:{team1:{id:'team1',name:'Infrastructure'}},assignments:{}}});
    if(path.endsWith('test-connection')){if(fail){const code=fail;fail='';return route.fulfill({status:400,json:{error:{code}}});}return route.fulfill({json:{...previewResult,preview:{...previewResult.preview,provider,name:'Fixture host',hosts:previewResult.preview.hosts.map(h=>({...h,id:hostId}))}}});}
    if(path.endsWith('cancel-onboarding'))return route.fulfill({json:{status:'cancelled'}});
    if(path.endsWith('resolve-placement'))return route.fulfill({json:{references:Object.fromEntries(['site','platform','device_role','cluster_type'].map(kind=>[kind,{...catalogRow(kind),...(['platform','cluster_type'].includes(kind)&&provider==='proxmox'?{name:'Proxmox VE'}:{})}])),host_types:{[hostId]:catalogRow('device_type')},sites:[catalogRow('site')],create_cluster:true,issues:[]}});
    if(path.endsWith('review-placement'))return route.fulfill({json:{valid:true}});
    if(path.includes('/catalog/')){const kind=path.split('/').pop()!,row=catalogRow(kind);if(kind==='cluster')row.name='Fixture host';if(provider==='proxmox'&&['platform','cluster_type'].includes(kind))row.name='Proxmox VE';return route.fulfill({json:{items:[row],count:1,offset:0,more:false,url:'https://netbox.example.test/'}});}
    if(path==='/api/v1/sources'&&req.method()==='POST'){writes.push(path);const data=req.postDataJSON();expect(Object.keys(data.host_types)).toContain(hostId);expect(data.sync_interval_seconds).toBe(600);expect(data.confirm_sync_disabled).toBe(true);registered={...source(),source_instance:data.source_instance,name:data.name,address:data.address,type:data.source_type,enabled:true,sync_enabled:false,status:'sync_disabled',legacy_identity_owner:false};return route.fulfill({json:registered});}
    if(path==='/api/v1/sources')return route.fulfill({json:{sources:registered?[registered]:[]}});
    if(path==='/api/v1/diagnostics')return route.fulfill({json:diagnostics(registered?[registered]:[])});
    if(req.method()!=='GET')writes.push(path);
    return route.fulfill({json:{}});
  });
  await page.goto('/sources/add');
  return {writes};
}
async function connect(page:any,provider='esxi'){
  await page.getByLabel('Source type').selectOption(provider);
  await page.getByLabel('Hostname or IPv4 address').fill('fixture.example.test');
  await expect(page.getByLabel('Hostname or IPv4 address')).toHaveValue('fixture.example.test');
  await page.locator('[name=username]').fill(provider==='esxi'?'netbox-sync':'netbox-sync@pve');
  if(provider==='proxmox')await page.locator('[name=token_id]').fill('netbox-sync');
  await page.locator('[name=secret]').fill(randomUUID());
  await page.getByRole('button',{name:'Continue',exact:true}).click();
}
async function placement(page:any){
 await expect(page.getByRole('button',{name:'Check parameters again',exact:true})).toBeEnabled();
}
for(const role of ['admin','operator'])for(const provider of ['esxi','proxmox'])test(`three steps ${role} ${provider}`,async({page})=>{
  const server=await fixture(page,role,provider);
  await expect(page.getByRole('navigation',{name:'Source setup steps'}).getByRole('button')).toHaveCount(3);
  await connect(page,provider);await expect(page).toHaveURL(/step=2/);
  await expect(page.getByLabel('Display name',{exact:true})).toHaveValue('Fixture host');
  if(role==='operator'){await expect(page.getByText('An administrator will assign a team')).toHaveCount(0);await expect(page.getByRole('combobox',{name:'Assigned team',exact:true})).toHaveCount(0);}
  else await expect(page.getByRole('combobox',{name:'Assigned team',exact:true})).toBeVisible();
  await placement(page);expect(server.writes).toEqual([]);
  await page.screenshot({path:test.info().outputPath(`wizard-${role}-${provider}-settings.png`),fullPage:true});
  await page.getByRole('button',{name:'Continue',exact:true}).click();await expect(page).toHaveURL(/step=3/);
  await expect(page.getByRole('checkbox',{name:'Confirm source registration'})).toHaveCount(0);
  await page.screenshot({path:test.info().outputPath(`wizard-${role}-${provider}-review.png`),fullPage:true});
  await page.goBack();await expect(page).toHaveURL(/step=2/);await expect(page.getByLabel('Display name',{exact:true})).toHaveValue('Fixture host');await placement(page);
  await page.getByRole('button',{name:'Continue',exact:true}).click();await page.getByRole('button',{name:'Add source',exact:true}).click();
  await expect(page).toHaveURL(/\/sources$/);await expect(page.getByRole('status').filter({hasText:'Source Fixture host added'})).toBeVisible();expect(server.writes).toEqual(['/api/v1/sources']);
  await page.getByRole('button',{name:'Dismiss notification'}).click();await expect(page.getByText('Source Fixture host added')).toHaveCount(0);
});

test('connection refusal retains fields, secret stays out of storage, exit is guarded',async({page})=>{
  await fixture(page,'admin','esxi','SOURCE_AUTH_FAILED');await connect(page);
  await expect(page.getByRole('alert').first()).toContainText('Authentication was rejected');
  await expect(page.locator('[name=secret]')).not.toBeEmpty();
  const protectedValue=await page.locator('[name=secret]').inputValue();
  expect(await page.evaluate(()=>JSON.stringify([localStorage,sessionStorage,location.href]))).not.toContain(protectedValue);
  await page.getByRole('button',{name:'Show password',exact:true}).click();await expect(page.locator('[name=secret]')).toHaveAttribute('type','text');
  await page.getByRole('button',{name:'Hide password',exact:true}).click();
  await page.screenshot({path:test.info().outputPath('wizard-connection-refused.png'),fullPage:true});
  await page.getByRole('link',{name:'Sources',exact:true}).first().click();await expect(page.getByRole('dialog')).toBeVisible();
  await page.getByRole('button',{name:'Stay',exact:true}).click();await expect(page.locator('[name=secret]')).not.toBeEmpty();
  await page.getByRole('link',{name:'Sources',exact:true}).first().click();await page.getByRole('button',{name:'Leave',exact:true}).click();await expect(page).toHaveURL(/\/sources$/);
});

test('viewer cannot open source registration',async({page})=>{
 await fixture(page,'viewer');await expect(page.getByText('You do not have permission to open this section.')).toBeVisible();await expect(page.locator('[name=secret]')).toHaveCount(0);
});


test('provider change clears provider-specific secrets and keeps address',async({page})=>{
 await fixture(page);await page.getByLabel('Hostname or IPv4 address').fill('fixture.example.test');
 await page.locator('[name=username]').fill('netbox-sync@pve');await page.locator('[name=secret]').fill(randomUUID());
 await page.getByLabel('Source type').selectOption('esxi');
 await expect(page.locator('[name=secret]')).toBeEmpty();await expect(page.locator('[name=token_id]')).toHaveCount(0);
 await expect(page.getByLabel('Hostname or IPv4 address')).toHaveValue('fixture.example.test');
 await expect(page.getByLabel('Verify TLS certificate')).toBeChecked();
 await page.screenshot({path:test.info().outputPath('wizard-connection.png'),fullPage:true});
});

test('changing tested address requires a new check and preserves placement',async({page})=>{
 await fixture(page);await connect(page);await placement(page);
 await page.getByRole('button',{name:'Back',exact:true}).click();
 await page.getByLabel('Hostname or IPv4 address').fill('another.example.test');
 await expect(page.getByRole('button',{name:'2 Source settings'})).toBeDisabled();
 await expect(page.locator('[name=secret]')).toBeEmpty();
 await page.locator('[name=secret]').fill(randomUUID());await page.getByRole('button',{name:'Continue',exact:true}).click();
 await expect(page.getByLabel('Display name',{exact:true})).toHaveValue('Fixture host');
 await expect(page.getByText('Test site',{exact:true}).first()).toBeVisible();
});

for(const role of ['admin','operator'])test(`Russian dark narrow wizard ${role}`,async({page})=>{
 await page.setViewportSize({width:390,height:844});await page.emulateMedia({colorScheme:'dark'});
 await fixture(page,role);await setLanguage(page,'ru');
 await page.screenshot({path:test.info().outputPath('connection-ru-dark.png'),fullPage:true});
 await setLanguage(page,'en');await connect(page);await setLanguage(page,'ru');
 await page.screenshot({path:test.info().outputPath('settings-ru-dark.png'),fullPage:true});
 await selectPlacement(page,'ru');await expect(page).toHaveURL(/step=3/);
 await expect(page.getByRole('button',{name:'Добавить источник',exact:true})).toBeEnabled();
 await page.screenshot({path:test.info().outputPath('review-ru-dark.png'),fullPage:true});
 await page.evaluate(()=>document.documentElement.style.zoom='1.5');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
});

test('team assignment refusal does not repeat a successful registration',async({page})=>{
 const server=await fixture(page);let assignments=0;
 await page.route('**/api/v1/teams',route=>{if(route.request().method()!=='POST')return route.fallback();assignments++;return route.fulfill({status:409,json:{error:{code:'REVISION_CONFLICT'}}});});
 await connect(page);await placement(page);await page.getByRole('combobox',{name:'Assigned team',exact:true}).selectOption('team1');
 await page.getByRole('button',{name:'Continue',exact:true}).click();
 await page.getByRole('button',{name:'Add source',exact:true}).evaluate((button:HTMLButtonElement)=>{button.click();button.click();});
 await expect(page).toHaveURL(/\/sources$/);
 await expect(page.getByRole('alert')).toContainText('team');
 expect(server.writes).toEqual(['/api/v1/sources']);expect(assignments).toBe(1);
 await page.screenshot({path:test.info().outputPath('team-assignment-unconfirmed.png'),fullPage:true});
});

test('secret-only draft guards exit and a late probe cannot advance a new wizard',async({page})=>{
 await fixture(page);await page.locator('[name=secret]').fill(randomUUID());
 await page.getByRole('link',{name:'Sources',exact:true}).first().click();
 await expect(page.getByRole('dialog')).toBeVisible();await page.getByRole('button',{name:'Stay',exact:true}).click();await expect(page.getByRole('dialog')).not.toBeVisible();
 let release:()=>void=()=>{};const gate=new Promise<void>(resolve=>release=resolve);let started=false;
 await page.route('**/api/v1/sources/test-connection',async route=>{started=true;await gate;await route.fulfill({json:previewResult});});
 await connect(page);await expect.poll(()=>started).toBe(true);
 await page.getByRole('link',{name:'Sources',exact:true}).first().click();await page.getByRole('button',{name:'Leave',exact:true}).click();
 await expect(page).toHaveURL(/\/sources$/);
 await page.getByRole('link',{name:'Add Source',exact:true}).first().click();
 const cancelled=page.waitForRequest(request=>request.url().endsWith('/cancel-onboarding'));
 release();await cancelled;await expect(page.locator('[name=secret]')).toBeEmpty();
 await expect(page.getByRole('button',{name:'2 Source settings'})).toBeDisabled();
});

for(const code of ['ONBOARDING_TOKEN_INVALID','PROBE_RECEIPT_INVALID'])test(`receipt expires during placement review ${code}`,async({page})=>{
 const server=await fixture(page);await connect(page);await placement(page);
 await page.route('**/api/v1/sources/review-placement',route=>route.fulfill({status:409,json:{error:{code}}}));
 await page.getByRole('button',{name:'Continue',exact:true}).click();
 await expect(page.locator('[name=secret]')).toBeVisible();
 await expect(page.getByRole('alert').first()).toContainText('expired');
 await expect(page.getByLabel('Hostname or IPv4 address')).toHaveValue('fixture.example.test');
 await page.locator('[name=secret]').fill(randomUUID());await page.getByRole('button',{name:'Continue',exact:true}).click();
 await expect(page.getByLabel('Display name',{exact:true})).toHaveValue('Fixture host');
 await expect(page.getByText('Test site',{exact:true}).first()).toBeVisible();
 expect(server.writes).toEqual([]);
});

for(const role of ['operator','admin'])test(`pending cluster only final registration ${role}`,async({page})=>{
 const server=await fixture(page,role);await connect(page);await placement(page);
 await expect(page.getByRole('checkbox',{name:'Create the cluster when adding this source',exact:true})).toHaveCount(0);
 await expect(page.getByRole('combobox',{name:'Cluster',exact:true})).toHaveCount(0);
 await page.screenshot({path:test.info().outputPath(`pending-cluster-${role}-settings.png`),fullPage:true});
 expect(server.writes).toEqual([]);
 await page.getByRole('button',{name:'Continue',exact:true}).click();await expect(page).toHaveURL(/step=3/);
 expect(server.writes).toEqual([]);
 await page.screenshot({path:test.info().outputPath(`pending-cluster-${role}-review.png`),fullPage:true});
 const sent=page.waitForRequest(request=>request.method()==='POST'&&new URL(request.url()).pathname==='/api/v1/sources');
 await page.getByRole('button',{name:'Add source',exact:true}).click();
 const body=(await sent).postDataJSON();expect(body.create_cluster).toBe(true);expect(body.cluster_name).toBe(body.name);
 expect(body.registration_id).toMatch(/^[0-9a-f-]{36}$/);expect(body.references.cluster).toBeUndefined();
 await expect(page).toHaveURL(/\/sources$/);expect(server.writes).toEqual(['/api/v1/sources']);
});

test('lost final response checks the actor-bound journal without another registration',async({page})=>{
 await fixture(page,'operator');await connect(page);await placement(page);
 await expect(page.getByRole('checkbox',{name:'Create the cluster when adding this source',exact:true})).toHaveCount(0);
 await page.getByRole('button',{name:'Continue',exact:true}).click();
 let posts=0,checks=0;
 await page.route('**/api/v1/sources',route=>{posts++;return route.fulfill({status:503,json:{error:{code:'REGISTRATION_UNCERTAIN'}}});});
 await page.route('**/api/v1/sources/esxi-aabbccddeeff',route=>route.fulfill({status:404,json:{error:{code:'SOURCE_NOT_FOUND'}}}));
 await page.route('**/api/v1/sources/registration-status',route=>{checks++;expect(Object.keys(route.request().postDataJSON()).sort()).toEqual(['registration_id','source_instance']);return route.fulfill({json:{status:'CREATED'}});});
 await page.getByRole('button',{name:'Add source',exact:true}).click();
 await page.getByRole('button',{name:'Check server state',exact:true}).click();
 await expect(page.getByRole('alert')).toContainText('The cluster is saved; the source is not registered.');
 expect(posts).toBe(1);expect(checks).toBe(1);
 await expect(page.getByRole('button',{name:'Add source',exact:true})).toBeDisabled();
});


test('placement review uses its own progress label before final registration',async({page})=>{
 const server=await fixture(page);await connect(page);await placement(page);
 let release:()=>void=()=>{};const gate=new Promise<void>(resolve=>release=resolve);
 await page.route('**/api/v1/sources/review-placement',async route=>{await gate;await route.fulfill({json:{valid:true}});});
 await page.getByRole('button',{name:'Continue',exact:true}).click();
 await expect(page.getByText('Checking placement',{exact:true})).toBeVisible();
 await expect(page.getByText('Registering source',{exact:true})).toHaveCount(0);
 expect(server.writes).toEqual([]);
 release();await expect(page).toHaveURL(/step=3/);
 await expect(page.getByText('Checking placement',{exact:true})).toHaveCount(0);
});


for(const stage of ['connection','registration'])test(`server host duplicate ${stage} retains existing source link`,async({page})=>{
 const server=await fixture(page);
 const rejection={error:{code:'HOST_ALREADY_REGISTERED',existing_source:'source-existing',message:'UNTRUSTED_REMOTE_DETAILS'}};
 if(stage==='connection')await page.route('**/api/v1/sources/test-connection',route=>route.fulfill({status:409,json:rejection}));
 await connect(page);
 if(stage==='registration'){
   await placement(page);await page.getByRole('button',{name:'Continue',exact:true}).click();
   await page.route('**/api/v1/sources',route=>route.request().method()==='POST'?route.fulfill({status:409,json:rejection}):route.fallback());
   await page.getByRole('button',{name:'Add source',exact:true}).click();
 }
 await expect(page.getByText('This host already belongs to a source. Open it; a removed source requires administrator recovery.',{exact:true})).toBeVisible();
 await expect(page.getByRole('link',{name:'Open existing source'})).toHaveAttribute('href','/sources/source-existing');
 await expect(page.getByText('UNTRUSTED_REMOTE_DETAILS')).toHaveCount(0);
 expect(server.writes).toEqual([]);
});


for(const role of ['admin','operator'])test(`removed host recovery is explicit and ${role} bounded`,async({page})=>{
 const server=await fixture(page,role);
 const id='source-existing';let restored=0;
 await page.route('**/api/v1/sources/test-connection',route=>{
  if(route.request().postDataJSON().recovery_source===id)return route.fulfill({json:previewResult});
  return route.fulfill({status:409,json:{error:{code:'HOST_SOURCE_REMOVED',existing_source:id}}});
 });
 await connect(page);
 if(role==='operator'){
  await expect(page.getByRole('button',{name:'Check recovery',exact:true})).toHaveCount(0);
  expect(server.writes).toEqual([]);return;
 }
 const review={source_instance:id,name:'Retained ESXi',operation_id:randomUUID(),proof:{digest:'a'.repeat(64),
  host_uuid:'503c5ad7-aaaa-bbbb-cccc-0123456789ab',site_id:1,cluster_id:3,blockers:[],
  owned:[{kind:'device',id:7},{kind:'vm',id:8}],retained_manual:[{kind:'vm',id:9}]}};
 await page.route(`**/api/v1/sources/${id}/recovery-review`,route=>route.fulfill({json:review}));
 await page.route(`**/api/v1/sources/${id}/recover`,route=>{
  const data=route.request().postDataJSON();expect(data.confirmed).toBe(true);expect(data.digest).toBe(review.proof.digest);
  restored++;return route.fulfill({json:{status:'RESTORED',source_instance:id}});
 });
 await page.route(`**/api/v1/sources/${id}`,route=>route.fulfill({json:{...source(),source_instance:id,type:'esxi',enabled:true,sync_enabled:false}}));
 await page.getByRole('button',{name:'Check recovery',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Retained ESXi'})).toBeVisible();
 await expect(page.locator('[name=secret]')).toHaveValue('');
 expect(restored).toBe(0);
 await page.getByText('Review every object',{exact:true}).click();
 await expect(page.getByText('Host #7',{exact:true})).toBeVisible();
 await expect(page.getByText('Virtual machine #9',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Confirm recovery of this source',exact:true}).click();
 await expect(page).toHaveURL(new RegExp(`/sources/${id}$`));
 expect(restored).toBe(1);expect(server.writes).toEqual([]);
});

for(const lang of ['en','ru'])test(`inconsistent hardware UUID refuses without clearing form ${lang}`,async({page})=>{
 const server=await fixture(page,'admin','esxi','HOST_IDENTITY_INCONSISTENT');
 await page.getByLabel('Source type').selectOption('esxi');
 await page.getByLabel('Hostname or IPv4 address').fill('fixture.example.test');
 await page.locator('[name=username]').fill('netbox-sync');
 await page.locator('[name=secret]').fill(randomUUID());
 if(lang==='ru')await setLanguage(page,lang);
 await page.getByRole('button',{name:lang==='ru'?'Продолжить':'Continue',exact:true}).click();
 await expect(page.getByRole('alert').first()).toContainText(lang==='ru'?'разные BIOS UUID':'different BIOS UUIDs');
 await expect(page.locator('[name=username]')).toHaveValue('netbox-sync');
 await expect(page.locator('[name=secret]')).not.toBeEmpty();
 expect(server.writes).toEqual([]);
 await page.screenshot({path:test.info().outputPath(`uuid-conflict-${lang}.png`),fullPage:true});
 await page.getByRole('button',{name:lang==='ru'?'Продолжить':'Continue',exact:true}).click();
 await expect(page).toHaveURL(/step=2/);
});


test('exact AM BIOS UUID survives preview placement and final registration',async({page})=>{
 const server=await fixture(page,'admin','esxi','','00000000-0000-0000-0000-ac1f6be2c4da');
 await connect(page);await placement(page);
 await page.getByRole('button',{name:'Continue',exact:true}).click();
 await page.getByRole('button',{name:'Add source',exact:true}).click();
 await expect(page).toHaveURL(/\/sources$/);
 expect(server.writes).toEqual(['/api/v1/sources']);
});

for(const lang of ['en','ru'])test(`legacy Admin decision continues full wizard ${lang}`,async({page})=>{
 const server=await fixture(page,'admin','esxi','','00000000-0000-0000-0000-ac1f6be2c4da');
 let resolved=false,decisions=0,oldProbe=0;
 await page.route('**/api/v1/sources/test-connection',route=>resolved?route.fallback():route.fulfill({status:409,json:{error:{code:'HOST_REGISTRY_REVIEW_REQUIRED',existing_source:'legacy'}}}));
 await page.route('**/api/v1/sources/legacy/legacy-*',async route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('review'))return route.fulfill({json:{source_instance:'legacy',name:'ESXI-1L-SUP',address:'old.example.test',port:443,verify_ssl:true,revision:'a'.repeat(64),host_uuid:null,state:'REMOVED',isolated:false,site_slug:'old',cluster_name:'Old'}});
  if(path.endsWith('probe')){oldProbe++;return route.fulfill({status:502,json:{error:{code:'SOURCE_CONNECTION_FAILED'}}});}
  const body=route.request().postDataJSON();expect(body.decision).toBe('ISOLATE');expect(body.confirmed).toBe(true);expect(body.evidence_token).toBeNull();decisions++;resolved=true;return route.fulfill({json:{status:'RECORDED'}});
 });
 await connect(page);await expect(page.getByText('It is not a confirmed duplicate.',{exact:false})).toBeVisible();
 if(lang==='ru')await setLanguage(page,'ru');
 await page.getByRole('button',{name:lang==='ru'?'Открыть проверку старой записи':'Review this legacy record',exact:true}).click();
 const old=page.locator('#legacy-identity');
 const newSecret=await page.locator('.wizard-form [name=secret]').inputValue();
 await old.locator('[name=username]').fill('old-account');await old.locator('[name=secret]').fill(randomUUID());
 expect(await old.locator('[name=secret]').inputValue()).not.toBe(newSecret);
 await old.getByRole('button',{name:lang==='ru'?'Проверить старый сервер':'Check old server',exact:true}).click();await expect.poll(()=>oldProbe).toBe(1);
 await expect(page.locator('.wizard-form [name=secret]')).toHaveValue(newSecret);
 await old.getByRole('textbox',{name:lang==='ru'?'Причина решения (без секретов)':'Decision reason (no secrets)'}).fill('Decommissioned; retained ownership is not proved');
 await old.getByRole('checkbox').check();await old.getByRole('button',{name:lang==='ru'?'Изолировать непроверенную запись':'Isolate unverified record',exact:true}).click();
 await expect(old.getByRole('status')).toContainText(lang==='ru'?'Решение сохранено':'Decision saved');
 await page.screenshot({path:test.info().outputPath('legacy-decision-'+lang+'.png'),fullPage:true});
 if(lang==='ru')await setLanguage(page,'en');
 await page.locator('.wizard-form').getByRole('button',{name:'Continue',exact:true}).click();await expect(page).toHaveURL(/step=2/);
 await placement(page);await page.getByRole('button',{name:'Continue',exact:true}).click();await page.getByRole('button',{name:'Add source',exact:true}).click();
 await expect(page).toHaveURL(/\/sources$/);expect(decisions).toBe(1);expect(server.writes).toEqual(['/api/v1/sources']);
});
