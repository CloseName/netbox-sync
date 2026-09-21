import {openUserMenu,setLanguage} from './menu-helper';
import {test,expect} from './operation-fixture';
import {randomUUID} from 'node:crypto';
import {previewResult,catalogRow,selectPlacement,host} from './source-placement-fixture';
async function fixture(page:any,scenario='exact'){
 let posts=0;let rejected=true;
 const preview=structuredClone(previewResult);
 if(scenario==='generic')preview.preview.hosts[0]={...host,manufacturer:'Supermicro',model:'Super Server'};
 if(scenario==='missing')preview.preview.hosts[0]={...host,manufacturer:null,model:null} as any;
 if(scenario==='heterogeneous')preview.preview={provider:'proxmox',name:'Production cluster',cluster:'Production cluster',hosts:[{...host,id:'a',name:'pve-a',manufacturer:null,model:null},{...host,id:'b',name:'pve-b',manufacturer:null,model:null}]} as any;
 await page.route('**/api/v1/**',route=>{const url=new URL(route.request().url());const path=url.pathname;
 if(path==='/api/v1/teams')return route.fulfill({json:{version:1,revision:1,teams:{},assignments:{}}});
 if(path.endsWith('resolve-placement')){
 const body=route.request().postDataJSON(),missing=scenario==='missing'||scenario==='heterogeneous';
 const references=Object.fromEntries(['site','cluster','platform','device_role','cluster_type'].filter(k=>!(scenario==='catalog'&&k==='platform')).map(k=>[k,{...catalogRow(k),...(k==='cluster'?{name:body.name}:{}),...(k==='site'&&body.site_id?{id:body.site_id}:{})}]));
 const host_types=missing?{}:Object.fromEntries(preview.preview.hosts.map(h=>[h.id,{...catalogRow('device_type'),name:h.model,manufacturer:{id:9,name:h.manufacturer}}]));
 return route.fulfill({json:{references,host_types,sites:[catalogRow('site'),{...catalogRow('site',2),name:'Other site'}],create_cluster:false,issues:scenario==='catalog'?[{kind:'platform',code:'MISSING'}]:missing?preview.preview.hosts.map(h=>({kind:'device_type',host_id:h.id,code:'MISSING'})):[]}});
 }
 if(path.endsWith('review-placement'))return route.fulfill({json:{valid:true}});
 if(path.endsWith('test-connection'))return route.fulfill({json:preview});
 if(path.includes('/catalog/')){const kind=path.split('/').pop()!;const query=url.searchParams.get('search');
 if(query==='denied')return route.fulfill({status:503,json:{error:{code:'CATALOG_PERMISSION_DENIED'}}});
 if(query==='offline')return route.abort('connectionfailed');
 const empty=query==='absent';const rows=empty?[]:[{...catalogRow(kind),...(kind==='cluster'?{name:query||preview.preview.name}:{})}];
 if(query==='ambiguous')rows.push({...catalogRow(kind,2),manufacturer:{id:10,name:'Other manufacturer'}});
 return route.fulfill({json:{items:rows,count:query==='large'?2000:rows.length,offset:Number(url.searchParams.get('offset')),more:query==='large',url:'https://netbox.example.test/dcim/sites/'}});}
 if(path==='/api/v1/sources'&&route.request().method()==='POST'){posts++;if(rejected){rejected=false;return route.fulfill({status:409,json:{error:{code:'CATALOG_CHANGED'}}});}
 const data=route.request().postDataJSON();return route.fulfill({json:{...data,type:data.source_type,status:'sync_disabled',enabled:true,sync_enabled:false,legacy_identity_owner:false}});}
 return route.fulfill({json:{sources:[]}});
 });
 await page.goto('/sources/add');await page.getByLabel('Source type').selectOption(scenario==='heterogeneous'?'proxmox':'esxi');await page.getByLabel('Hostname or IPv4 address').fill('esxi.example.test');await page.locator('[name=username]').fill(scenario==='heterogeneous'?'netbox-sync@pve':'netbox-sync');if(scenario==='heterogeneous')await page.locator('[name=token_id]').fill('netbox-sync');await page.locator('[name=secret]').fill(randomUUID());await page.getByRole('button',{name:'Continue',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Source settings',exact:true})).toBeVisible();await expect(page.locator('[name=secret]')).toHaveCount(0);
 return {posts:()=>posts};
}
for(const lang of ['en','ru'])for(const theme of ['light','dark'] as const)for(const width of [1440,390])test(`placement ${lang} ${theme} ${width}`,async({page})=>{
 await page.setViewportSize({width,height:900});await page.emulateMedia({colorScheme:theme});const f=await fixture(page);
 await setLanguage(page,lang);
 const label=lang==='ru'?'Название источника':'Display name';await page.getByLabel(label,{exact:true}).fill('My host');
 await setLanguage(page,lang==='ru'?'en':'ru');await setLanguage(page,lang);await expect(page.getByLabel(label,{exact:true})).toHaveValue('My host');
 await expect(page.getByText('PowerEdge R650',{exact:true}).first()).toBeVisible();
 expect(f.posts()).toBe(0);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
 await page.screenshot({path:`test-results/placement-${lang}-${theme}-${width}.png`,fullPage:true});
 await selectPlacement(page,lang);
 await page.getByRole('button',{name:lang==='ru'?'Добавить источник':'Add source',exact:true}).click();
 await expect(page.getByRole('alert').first()).toContainText(lang==='ru'?'не прошёл проверку':'could not be verified');expect(f.posts()).toBe(1);
 await expect(page.getByLabel(label,{exact:true})).toHaveValue('My host');
 await page.screenshot({path:`test-results/placement-changed-${lang}-${theme}-${width}.png`,fullPage:true});
});
for(const scenario of ['generic','missing','heterogeneous'])test(`no invented model ${scenario}`,async({page})=>{
 await fixture(page,scenario);await expect(page.getByRole('button',{name:'Check parameters again'})).toBeEnabled();if(scenario==='generic')await expect(page.getByText('Super Server',{exact:true}).first()).toBeVisible();else await expect(page.getByText(/No NetBox device type:/).first()).toBeVisible();
 await page.screenshot({path:`test-results/placement-${scenario}.png`,fullPage:true});
});
test('catalog empty, errors, ambiguity, pagination and keyboard preserve draft',async({page})=>{
 await fixture(page);await expect(page.getByRole('button',{name:'Check parameters again'})).toBeEnabled();await page.getByRole('combobox',{name:'Site',exact:true}).click();const search=page.getByRole('searchbox',{name:'Search: Site',exact:true});
 for(const term of ['absent','denied','offline','ambiguous','large']){await search.fill(term);
 const section=search.locator('xpath=ancestor::section[1]');if(term==='absent')await expect(section).toContainText('No matches');else if(term==='denied')await expect(section).toContainText('read access was denied');else if(term==='offline')await expect(section).toContainText('Could not load');else if(term==='ambiguous')await expect(section.getByRole('option')).toHaveCount(2);else {await expect(section).toContainText('2000');await section.getByRole('button',{name:'Next',exact:true}).click();await expect(section).toContainText('21');}}
 await search.fill('');await expect(page.getByRole('listbox',{name:'Site',exact:true}).getByRole('option')).toHaveCount(1);await search.press('Enter');await expect(page.getByRole('combobox',{name:'Site',exact:true})).toContainText('Test site');
 await page.evaluate(()=>document.documentElement.style.zoom='2');expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
});

test('session expiry keeps only the non-secret draft and never retries registration',async({page})=>{
 const f=await fixture(page);await page.getByLabel('Display name',{exact:true}).fill('Retained draft');
 await expect(page.getByRole('button',{name:'Check parameters again'})).toBeEnabled();
 await page.route('**/api/v1/sources/resolve-placement',route=>route.fulfill({status:401,json:{error:{code:'AUTH_REQUIRED'}}}));
 await page.getByRole('button',{name:'Check parameters again'}).click();
 await expect(page.getByRole('heading',{name:'Sign in',exact:true})).toBeVisible();expect(f.posts()).toBe(0);
 await page.route('**/api/v1/auth/login',route=>route.fulfill({json:{authenticated:true}}));
 await page.getByLabel('Username',{exact:true}).fill('admin');await page.getByLabel('Password',{exact:true}).fill(randomUUID());await page.getByRole('button',{name:'Sign in',exact:true}).click();
 await expect(page.getByLabel('Hostname or IPv4 address')).toHaveValue('esxi.example.test');await expect(page.locator('[name=secret]')).toBeEmpty();
 await page.unroute('**/api/v1/sources/resolve-placement');await page.locator('[name=username]').fill('netbox-sync');await page.locator('[name=secret]').fill(randomUUID());await page.getByRole('button',{name:'Continue',exact:true}).click();
 await expect(page.getByLabel('Display name',{exact:true})).toHaveValue('Retained draft');expect(f.posts()).toBe(0);
});


test('explicit retry after catalog review registers with sync off',async({page})=>{
 const f=await fixture(page);
 for(let attempt=0;attempt<2;attempt++){
  await selectPlacement(page);
  await page.getByRole('button',{name:'Add source',exact:true}).click();
  if(attempt===0)await expect(page.getByRole('alert').first()).toContainText('could not be verified');
 }
 await expect(page).toHaveURL(/\/sources$/);expect(f.posts()).toBe(2);
 await page.screenshot({path:'test-results/placement-success.png',fullPage:true});
});

for(const code of ['ONBOARDING_TOKEN_INVALID','PROBE_RECEIPT_INVALID'])test(`expired ${code} preserves placement`,async({page})=>{
 await fixture(page);await page.getByLabel('Display name',{exact:true}).fill('Retained name');
 await page.route('**/api/v1/sources',route=>route.fulfill({status:409,json:{error:{code}}}));
 await selectPlacement(page);
 await page.getByRole('button',{name:'Add source',exact:true}).click();
 await expect(page.getByRole('alert')).toContainText('no longer valid');
 await expect(page.getByLabel('Hostname or IPv4 address')).toHaveValue('esxi.example.test');
 await page.locator('[name=username]').fill('netbox-sync');await page.locator('[name=secret]').fill(randomUUID());
 await page.getByRole('button',{name:'Continue',exact:true}).click();
 await expect(page.getByLabel('Display name',{exact:true})).toHaveValue('Retained name');
 await expect(page.getByRole('combobox',{name:'Site',exact:true})).toContainText('Test site');
});
test('unknown registration checks server without another POST',async({page})=>{
 await fixture(page);let writes=0,reads=0;
 await page.route('**/api/v1/sources',route=>{writes++;return route.abort('connectionfailed');});
 await page.route('**/api/v1/sources/esxi-aabbccddeeff',route=>{reads++;return route.fulfill({status:404,json:{error:{code:'SOURCE_NOT_FOUND'}}});});
 await selectPlacement(page);
 await page.getByRole('button',{name:'Add source',exact:true}).click();
 await expect(page.getByRole('button',{name:'Add source',exact:true})).toBeDisabled();
 await page.getByRole('button',{name:'Check server state',exact:true}).click();
 await expect(page.getByRole('alert')).toContainText('still unconfirmed');expect(writes).toBe(1);expect(reads).toBe(1);
});

for(const outcome of ['CREATED','REFUSED','UNCERTAIN','EXISTS_REVIEW_REQUIRED'])test(`explicit catalog creation ${outcome}`,async({page})=>{
 await fixture(page,'catalog');await page.getByLabel('Display name',{exact:true}).fill('Retained catalog draft');
 let writes=0,checks=0;
 const created={...catalogRow('platform',12),name:'Custom platform'};
 await page.route('**/api/v1/catalog/platform',async route=>{
  if(route.request().method()!=='POST')return route.fallback();
  writes++;const body=route.request().postDataJSON();expect(body.confirm).toBe(true);expect(body.object).toEqual({name:'Custom platform',slug:'custom-platform'});
  await route.fulfill({json:{operation_id:body.operation_id,status:outcome,item:outcome==='CREATED'||outcome==='EXISTS_REVIEW_REQUIRED'?created:null,error:outcome==='REFUSED'?'PERMISSION_DENIED':null}});
 });
 await page.route('**/api/v1/catalog-operations/*',route=>{checks++;return route.fulfill({json:{operation_id:route.request().url().split('/').pop(),status:'EXISTS_REVIEW_REQUIRED',item:created}});});
 await page.getByRole('button',{name:'Create missing entry',exact:true}).click();
 const dialog=page.getByRole('dialog',{name:'Create in NetBox',exact:true});
 await dialog.getByLabel('Name *',{exact:true}).fill('Custom platform');await dialog.getByLabel('Slug *',{exact:true}).fill('custom-platform');
 await dialog.getByLabel('Separate temporary catalog write token *',{exact:true}).fill(randomUUID());
 await dialog.getByRole('button',{name:'Confirm creation',exact:true}).click();
 if(outcome==='CREATED'){await expect(dialog).toHaveCount(0);}
 if(outcome==='REFUSED'){
  await expect(dialog.getByRole('alert')).toContainText('NetBox refused access');
  await expect(dialog.getByLabel('Separate temporary catalog write token *')).toBeEmpty();
  await dialog.getByRole('button',{name:'Close',exact:true}).click();
 }
 if(outcome==='UNCERTAIN'){
  await expect(dialog.getByRole('button',{name:'Confirm creation',exact:true})).toBeDisabled();
  await dialog.getByRole('button',{name:'Check operation',exact:true}).click();expect(checks).toBe(1);
 }
 if(['UNCERTAIN','EXISTS_REVIEW_REQUIRED'].includes(outcome)){
  await expect(dialog).toContainText('An object already exists');
  await dialog.getByRole('button',{name:'Choose this existing object',exact:true}).click();
 }
 await expect(page.getByRole('button',{name:'Check parameters again'})).toBeEnabled();
 expect(writes).toBe(1);await expect(page.getByLabel('Display name',{exact:true})).toHaveValue('Retained catalog draft');
 // Created names do not override verified automatic matching; the server resolves again.
 await expect(page.getByRole('combobox',{name:'Platform',exact:true})).toHaveCount(0);
});

for(const lang of ['en','ru'])for(const theme of ['light','dark'] as const)for(const width of [1440,390])test(`catalog dialog ${lang} ${theme} ${width}`,async({page})=>{
 await page.setViewportSize({width,height:900});await page.emulateMedia({colorScheme:theme});await fixture(page,'catalog');
 await setLanguage(page,lang);
 await page.getByRole('button',{name:lang==='ru'?'Создать недостающую запись':'Create missing entry',exact:true}).click();
 const dialog=page.getByRole('dialog',{name:lang==='ru'?'Создать в NetBox':'Create in NetBox',exact:true});
 await expect(dialog).toBeVisible();await expect(dialog.locator('input[type=password]')).toBeEmpty();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
 await page.screenshot({path:`test-results/catalog-${lang}-${theme}-${width}.png`,fullPage:true});
 await page.evaluate(()=>document.documentElement.style.zoom='2');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
 await dialog.getByRole('button',{name:lang==='ru'?'Закрыть':'Close',exact:true}).click();
 await expect(dialog).toHaveCount(0);await expect(page.getByRole('heading',{name:lang==='ru'?'Настройки источника':'Source settings',exact:true})).toBeVisible();
});

test('placement refusal before confirmation retains edited name and points to cluster',async({page})=>{
 const f=await fixture(page);await page.getByLabel('Display name',{exact:true}).fill('ESXi-CM.QA');
 await page.route('**/api/v1/sources/review-placement',route=>route.fulfill({status:409,json:{error:{code:'CATALOG_CLUSTER_SCOPE_MISMATCH'}}}));
 await selectPlacement(page);await expect(page.getByRole('alert')).toContainText('Cluster: its site or type changed.');
 await expect(page.getByLabel('Display name',{exact:true})).toHaveValue('ESXi-CM.QA');
 await expect(page.getByRole('checkbox',{name:'Confirm source registration'})).toHaveCount(0);expect(f.posts()).toBe(0);
});
test('incompatible cluster blocks review without a cluster selector',async({page})=>{
 await fixture(page);await page.route('**/api/v1/sources/resolve-placement',route=>route.fulfill({json:{references:{},host_types:{},sites:[],create_cluster:false,issues:[{kind:'cluster',code:'CONFLICT'}]}}));
 await page.getByLabel('Display name',{exact:true}).fill('Occupied cluster');
 await expect(page.getByText('This source name cannot be used for the selected placement. Change it or ask an administrator to resolve the conflict.')).toBeVisible();
 await expect(page.locator('#source-name').locator('..').locator('xpath=following-sibling::*[1]')).toHaveAttribute('role','alert');
 await page.getByRole('button',{name:'Continue',exact:true}).click();await expect(page).toHaveURL(/step=2/);
 await expect(page.getByRole('combobox',{name:'Cluster',exact:true})).toHaveCount(0);
});
