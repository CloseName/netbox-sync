import {test,expect} from '@playwright/test';
import {source,diagnostics} from '../tests/fixtures.mjs';
import {catalogRow,previewResult} from './source-placement-fixture';
import {randomUUID} from 'node:crypto';
async function setup(page:any,role='operator',provider='esxi',issue=''){
 let posts=0;
 await page.route('**/api/v1/**',async(route:any)=>{
 const path=new URL(route.request().url()).pathname;
 if(path.endsWith('/auth/me'))return route.fulfill({json:{principal_id:'fixture',role,username:role,permissions:['source.read','run.read','diagnostics.read',...(role==='viewer'?[]:['source.register','source.probe']),...(role==='admin'?['source.configure','identity.manage','catalog.create']:[])]}});
 if(path.endsWith('/bootstrap'))return route.fulfill({json:{status:'READY',completed:true,revision:1,checks:[],read_token_present:true,apply_token_present:true}});
 if(path.endsWith('/teams'))return route.fulfill({json:{version:1,revision:1,teams:{},assignments:{}}});
 if(path.endsWith('/test-connection'))return route.fulfill({json:{...previewResult,preview:{...previewResult.preview,provider,name:'Fixture host',hosts:previewResult.preview.hosts.map(host=>({...host,name:provider+'.example.test',version:provider==='esxi'?'8.0 build-1':'8.4'}))}}});
 if(path.endsWith('/resolve-placement')){const data=route.request().postDataJSON();const references=Object.fromEntries(['site','platform','device_role','cluster_type'].map(kind=>[kind,{...catalogRow(kind),...(['platform','cluster_type'].includes(kind)&&provider==='proxmox'?{name:'Proxmox VE'}:{})}]));return route.fulfill({json:{references,host_types:issue?{}:{'host-a':catalogRow('device_type')},sites:[catalogRow('site')],create_cluster:true,issues:issue?[{kind:'device_type',host_id:'host-a',code:issue}]:[]}});}
 if(path.endsWith('/review-placement'))return route.fulfill({json:{valid:true}});
 if(path==='/api/v1/sources'&&route.request().method()==='POST'){posts++;const data=route.request().postDataJSON();expect(data.automatic_placement).toBe(true);expect(data.sync_interval_seconds).toBe(600);return route.fulfill({json:{...source(),name:data.name,source_instance:data.source_instance,type:provider,sync_enabled:false}});}
 if(path==='/api/v1/sources')return route.fulfill({json:{sources:[]}});
 if(path.endsWith('/diagnostics'))return route.fulfill({json:diagnostics([])});
 return route.fulfill({json:{}});
 });
 await page.goto('/sources/add');return ()=>posts;
}
for(const provider of ['esxi','proxmox'])for(const role of ['operator','admin'])test(`automatic wizard ${provider} ${role}`,async({page})=>{
 const posts=await setup(page,role,provider);
 await page.getByLabel('Source type').selectOption(provider);
 await page.getByLabel('Hostname or IPv4 address').fill('fixture.example.test');
 await page.locator('[name=username]').fill(provider==='esxi'?'netbox-sync':'netbox-sync@pve');
 if(provider==='proxmox')await page.locator('[name=token_id]').fill('netbox-sync');
 await page.locator('[name=secret]').fill(randomUUID());
 await page.screenshot({path:test.info().outputPath('connection.png'),fullPage:true});
 await page.getByRole('button',{name:'Continue',exact:true}).click();
 await expect(page.getByText('Checking NetBox parameters…')).toHaveCount(0);
 await expect(page.getByRole('button',{name:'Check parameters again'})).toBeEnabled();
 await expect(page.getByRole('combobox',{name:'Cluster',exact:true})).toHaveCount(0);
 await expect(page.getByRole('checkbox',{name:'Create the cluster when adding this source'})).toHaveCount(0);
 await page.getByText('View NetBox parameters',{exact:true}).click();
 await expect(page.getByText('Cluster will be created: Fixture host')).toBeVisible();expect(posts()).toBe(0);
 await page.screenshot({path:test.info().outputPath('settings.png'),fullPage:true});
 await page.getByRole('button',{name:'Continue',exact:true}).click();await expect(page).toHaveURL(/step=3/);
 await page.screenshot({path:test.info().outputPath('review.png'),fullPage:true});
 await page.getByRole('button',{name:'Add source',exact:true}).click();await expect(page).toHaveURL(/\/sources$/);expect(posts()).toBe(1);
});
test('empty form explains errors and keeps keyboard access',async({page})=>{
 await setup(page);await expect(page.getByRole('button',{name:'Continue',exact:true})).toBeEnabled();
 await page.getByRole('button',{name:'Continue',exact:true}).click();
 await expect(page.locator('#form-error-summary')).toBeFocused();
 await expect(page.locator('input[aria-invalid=true]').first()).toBeVisible();
 await page.locator('#form-error-summary a').first().click();await expect(page.locator('input[aria-invalid=true]').first()).toBeFocused();
 await page.screenshot({path:test.info().outputPath('required-fields.png'),fullPage:true});
});
test('viewer denied registration',async({page})=>{
 await setup(page,'viewer');await expect(page.getByText('You do not have permission to open this section.')).toBeVisible();
});

for(const locale of ['en','ru'])for(const theme of ['light','dark'])test(`floating login ${locale} ${theme}`,async({page},info)=>{
 await page.addInitScript(({locale,theme})=>{localStorage.setItem('netbox-sync.language',locale);localStorage.setItem('netbox-sync.theme',theme);},{locale,theme});
 await page.setViewportSize({width:390,height:844});let writes=0;
 await page.route('**/api/v1/**',route=>{if(route.request().method()==='POST')writes++;return route.request().url().endsWith('/auth/status')?route.fulfill({json:{enrollment_available:false}}):route.fulfill({status:401,json:{error:{code:'AUTH_REQUIRED'}}});});
 await page.goto('/');const user=page.locator('[name=username]'),secret=page.locator('[name=password]');
 await expect(user).toHaveAttribute('autocomplete','username');await expect(secret).toHaveAttribute('autocomplete','current-password');
 await user.fill('netbox-sync');await secret.fill(randomUUID());const before=await secret.boundingBox();
 const show=page.getByRole('button',{name:locale==='ru'?'Показать пароль':'Show password',exact:true});await show.focus();await expect(page.getByRole('tooltip')).toBeVisible();await show.click();await expect(secret).toHaveAttribute('type','text');
 await page.getByRole('button',{name:locale==='ru'?'Скрыть пароль':'Hide password',exact:true}).click();await expect(secret).toHaveAttribute('type','password');expect(await secret.boundingBox()).toEqual(before);expect(writes).toBe(0);
 await page.screenshot({path:info.outputPath('login.png'),fullPage:true});
 await page.evaluate(()=>document.documentElement.style.fontSize='200%');await expect(secret).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});
