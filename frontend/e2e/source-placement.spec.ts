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
 if(path.endsWith('test-connection'))return route.fulfill({json:preview});
 if(path.includes('/catalog/')){const kind=path.split('/').pop()!;const query=url.searchParams.get('search');
 if(query==='denied')return route.fulfill({status:503,json:{error:{code:'CATALOG_PERMISSION_DENIED'}}});
 if(query==='offline')return route.abort('connectionfailed');
 const empty=query==='absent';const rows=empty?[]:[catalogRow(kind)];
 if(query==='ambiguous')rows.push({...catalogRow(kind,2),manufacturer:{id:10,name:'Other manufacturer'}});
 return route.fulfill({json:{items:rows,count:query==='large'?2000:rows.length,offset:Number(url.searchParams.get('offset')),more:query==='large',url:'https://netbox.example.test/dcim/sites/'}});}
 if(path==='/api/v1/sources'&&route.request().method()==='POST'){posts++;if(rejected){rejected=false;return route.fulfill({status:409,json:{error:{code:'CATALOG_CHANGED'}}});}
 const data=route.request().postDataJSON();return route.fulfill({json:{...data,type:data.source_type,status:'sync_disabled',enabled:true,sync_enabled:false,legacy_identity_owner:false}});}
 return route.fulfill({json:{sources:[]}});
 });
 await page.goto('/sources/add');await page.getByLabel('Source type').selectOption(scenario==='heterogeneous'?'proxmox':'esxi');await page.getByLabel('Hostname or IPv4 address').fill('esxi.example.test');await page.locator('[name=username]').fill(scenario==='heterogeneous'?'netbox-sync@pve':'netbox-sync');if(scenario==='heterogeneous')await page.locator('[name=token_id]').fill('netbox-sync');await page.locator('[name=secret]').fill(randomUUID());await page.getByRole('button',{name:'Test Connection',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Detected hosts',exact:true})).toBeVisible();await expect(page.locator('[name=secret]')).toHaveCount(0);
 return {posts:()=>posts};
}
for(const lang of ['en','ru'])for(const theme of ['light','dark'] as const)for(const width of [1440,390])test(`placement ${lang} ${theme} ${width}`,async({page})=>{
 await page.setViewportSize({width,height:900});await page.emulateMedia({colorScheme:theme});const f=await fixture(page);
 await page.getByLabel('Language / Язык').selectOption(lang);
 const label=lang==='ru'?'Название источника':'Display name';await page.getByLabel(label,{exact:true}).fill('My host');
 await page.getByLabel('Language / Язык').selectOption(lang==='ru'?'en':'ru');await page.getByLabel('Language / Язык').selectOption(lang);await expect(page.getByLabel(label,{exact:true})).toHaveValue('My host');
 await expect(page.getByRole('combobox',{name:lang==='ru'?/^Тип устройства.*для/:/^Device type for/})).toHaveValue('1');
 expect(f.posts()).toBe(0);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
 await page.screenshot({path:`test-results/placement-${lang}-${theme}-${width}.png`,fullPage:true});
 await selectPlacement(page,lang);await page.getByRole('checkbox',{name:lang==='ru'?'Зарегистрировать источник с выключенной автоматической синхронизацией.':'Register a new source with automatic sync OFF.'}).check();
 await page.getByRole('button',{name:lang==='ru'?'Зарегистрировать источник':'Register Source',exact:true}).click();
 await expect(page.getByRole('alert').first()).toContainText(lang==='ru'?'не прошёл проверку':'could not be verified');expect(f.posts()).toBe(1);
 await expect(page.getByLabel(label,{exact:true})).toHaveValue('My host');
 await page.screenshot({path:`test-results/placement-changed-${lang}-${theme}-${width}.png`,fullPage:true});
});
for(const scenario of ['generic','missing','heterogeneous'])test(`no invented model ${scenario}`,async({page})=>{
 await fixture(page,scenario);for(const select of await page.getByRole('combobox',{name:/^Device type for/}).all())await expect(select).toHaveValue('');
 await page.screenshot({path:`test-results/placement-${scenario}.png`,fullPage:true});
});
test('catalog empty, errors, ambiguity, pagination and keyboard preserve draft',async({page})=>{
 await fixture(page);const search=page.getByRole('searchbox',{name:'Search: Site',exact:true});
 for(const term of ['absent','denied','offline','ambiguous','large']){await search.fill(term);
 const section=search.locator('..');if(term==='absent')await expect(section).toContainText('No matches');else if(term==='denied')await expect(section).toContainText('read access was denied');else if(term==='offline')await expect(section).toContainText('Could not load');else if(term==='ambiguous')await expect(section.locator('option')).toHaveCount(3);else {await expect(section).toContainText('2000');await section.getByRole('button',{name:'Next',exact:true}).click();await expect(section).toContainText('21');}}
 await search.fill('');await page.getByRole('combobox',{name:'Site',exact:true}).focus();await page.keyboard.press('ArrowDown');await page.keyboard.press('Enter');await expect(page.getByRole('combobox',{name:'Site',exact:true})).toHaveValue('1');
 await page.evaluate(()=>document.documentElement.style.zoom='2');expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
});

test('session expiry keeps only the non-secret draft and never retries registration',async({page})=>{
 const f=await fixture(page);await page.getByLabel('Display name',{exact:true}).fill('Retained draft');
 await page.route('**/api/v1/catalog/site?*',route=>route.fulfill({status:401,json:{error:{code:'AUTH_REQUIRED'}}}));
 await page.getByRole('searchbox',{name:'Search: Site',exact:true}).fill('expire');
 await expect(page.getByRole('heading',{name:'Sign in',exact:true})).toBeVisible();expect(f.posts()).toBe(0);
 await page.route('**/api/v1/auth/login',route=>route.fulfill({json:{authenticated:true}}));
 await page.getByLabel('Username',{exact:true}).fill('admin');await page.getByLabel('Password',{exact:true}).fill(randomUUID());await page.getByRole('button',{name:'Sign in',exact:true}).click();
 await expect(page.getByLabel('Hostname or IPv4 address')).toHaveValue('esxi.example.test');await expect(page.locator('[name=secret]')).toBeEmpty();
 await page.unroute('**/api/v1/catalog/site?*');await page.locator('[name=username]').fill('netbox-sync');await page.locator('[name=secret]').fill(randomUUID());await page.getByRole('button',{name:'Test Connection',exact:true}).click();
 await expect(page.getByLabel('Display name',{exact:true})).toHaveValue('Retained draft');expect(f.posts()).toBe(0);
});


test('explicit retry after catalog review registers with sync off',async({page})=>{
 const f=await fixture(page);
 for(let attempt=0;attempt<2;attempt++){
  await selectPlacement(page);await page.getByRole('checkbox',{name:'Register a new source with automatic sync OFF.'}).check();
  await page.getByRole('button',{name:'Register Source',exact:true}).click();
  if(attempt===0)await expect(page.getByRole('alert').first()).toContainText('could not be verified');
 }
 await expect(page.getByRole('heading',{name:'Source registered',exact:true})).toBeVisible();expect(f.posts()).toBe(2);
 await page.screenshot({path:'test-results/placement-success.png',fullPage:true});
});
