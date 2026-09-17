import {test,expect} from './auth-fixture';
import {source,run,runId,diagnostics} from '../tests/fixtures.mjs';
import {setLanguage} from './menu-helper';
const digest='a'.repeat(64);
const row=(action:string,extra:any={})=>({action,object_kind:'virtualization.virtual_machines',external_id:'1',name:'VM test',reason:'Existing guarded executor would perform this managed-field mutation.',reason_code:'GUARDED_EXECUTOR_ACTION',matched_object_id:1,before:[['memory',4096]],after:[['memory',8192]],...extra});
const plan=(items:any[])=>({source_instance:'source-1',source_type:'proxmox',source_fingerprint:'s',target_fingerprint:'t',provider_fingerprint:'p',netbox_fingerprint:'n',schema_version:1,planner_version:'test',digest,apply_allowed:true,items});
async function fixture(page:any,items:any[],consumed=false){
 const s=source(),d=diagnostics([s]);const stamp=new Date(Date.now()-60000).toISOString();
 const r={...run('OUTCOME_UNCERTAIN'),started_at:new Date().toISOString(),finished_at:new Date().toISOString(),plan_digest:digest,error_code:'OUTCOME_UNCERTAIN',error_message_safe:'Final state requires verification.'};
 r.actions=Object.fromEntries(Object.keys(r.actions).map(k=>[k,0]));d.sources[0].latest_run=consumed?r:null;d.sources[0].latest_success_at=null;
 const operation={operation_id:'22222222-2222-4222-8222-222222222222',source_instance:'source-1',operation_kind:'PLAN',status:'READY',started_at:stamp,updated_at:stamp,finished_at:stamp,safe_error_code:null,used_run_id:consumed?runId:null,result:plan(items)};
 let writes=0;
 await page.route('**/api/v1/**',route=>{
  const path=new URL(route.request().url()).pathname;if(route.request().method()!=='GET')writes++;
  if(path==='/api/v1/bootstrap')return route.fulfill({json:{revision:1,status:'READY',url:'https://netbox.test',completed:true,read_token_present:true,apply_token_present:true,safe_code:null,checks:[],validated_at:1}});
  if(path==='/api/v1/sources')return route.fulfill({json:{sources:[s]}});
  if(path==='/api/v1/diagnostics')return route.fulfill({json:d});
  if(path.endsWith('/operations'))return route.fulfill({json:{operations:[operation]}});
  if(path.endsWith('/schedule'))return route.fulfill({json:{source_instance:'source-1',sync_enabled:false,sync_interval_seconds:600,scheduler_state:'DISABLED',last_scheduled_run_at:null,next_expected_at:null}});
  // The consumed run is deliberately absent from the first history page.
  if(path==='/api/v1/runs')return route.fulfill({json:{runs:[],next_cursor:null}});
  if(path==='/api/v1/runs/'+runId)return route.fulfill({json:r});
  if(path==='/api/v1/sources/source-1')return route.fulfill({json:s});
  return route.fulfill({status:404,json:{}});
 });return {writes:()=>writes};
}
test('used plan and durable uncertain result survive reload outside bounded history',async({page})=>{
 const f=await fixture(page,[row('UPDATE')],true);
 for(let i=0;i<2;i++){
  await page.goto('/sources/source-1/sync');
  await expect(page.getByText('This plan has been used.',{exact:false})).toBeVisible();
  await expect(page.getByRole('button',{name:'Review and confirm sync'})).toBeDisabled();
  await page.getByRole('link',{name:'Open run',exact:true}).click();
  await expect(page.getByText('Counts unavailable; changes may have been written.')).toBeVisible();
  await expect(page.getByText('No actions recorded',{exact:true})).toHaveCount(0);
  await expect(page.getByText('The recorded terminal result is shown above.')).toBeVisible();
 }
 expect(f.writes()).toBe(0);
});
for(const theme of ['light','dark'])for(const language of ['en','ru'])for(const width of [390,1280])test(`large grouped plan ${language} ${theme} ${width}`,async({page})=>{
 await page.setViewportSize({width,height:900});
 await page.addInitScript(value=>localStorage.setItem('netbox-sync.theme',value),theme);
 const items=[];for(let i=1;i<=60;i++){
  items.push(row('CREATE',{object_kind:'dcim.devices',name:'ESXI-CM.QA-'+i,external_id:'host-'+i,matched_object_id:null,before:[],after:[['id',-i],['name','ESXI-CM.QA-'+i]]}));
  items.push(row('CREATE',{object_kind:'dcim.interfaces',name:'Network adapter 1',external_id:String(-i),matched_object_id:null,before:[],after:[['id',-i],['device',-i]]}));
 }
 items.push(row('NO_CHANGE',{object_kind:'qemu'}),row('NO_CHANGE',{object_kind:'vm'}),row('UNSUPPORTED',{object_kind:'host_network',reason_code:'ESXI_HOST_NETWORK_UNSUPPORTED'}));
 const f=await fixture(page,items);await page.goto('/sources/source-1/sync');if(language==='ru')await setLanguage(page,'ru');
 await expect(page.locator('.plan-review')).toBeVisible();await expect(page.locator('.plan-review')).toContainText('ESXI-CM.QA-1');
 const options=await page.locator('.plan-review select').nth(1).locator('option').allTextContents();expect(new Set(options).size).toBe(options.length);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
 await page.screenshot({path:`test-results/live-audit-grouped-${language}-${theme}-${width}.png`,fullPage:true});
 await page.getByRole('button',{name:language==='ru'?'Показать неподдерживаемые категории':'Show unsupported categories'}).click();await expect(page.locator('.plan-row')).toHaveCount(1);
 await page.screenshot({path:`test-results/live-audit-plan-${language}-${theme}-${width}.png`,fullPage:true});expect(f.writes()).toBe(0);
});
test('no-op remains distinct from unsupported and cannot confirm writes',async({page})=>{
 await fixture(page,[row('NO_CHANGE'),row('UNSUPPORTED',{object_kind:'host_network',reason_code:'ESXI_HOST_NETWORK_UNSUPPORTED'})]);await page.goto('/sources/source-1/sync');
 await expect(page.locator('.plan-review .badge').filter({hasText:'No changes to apply'})).toBeVisible();await expect(page.getByRole('button',{name:'Review and confirm sync'})).toBeDisabled();
 await page.getByRole('button',{name:'Show unsupported categories'}).click();await expect(page.locator('.plan-row')).toHaveCount(1);
});

test('address policy check sends no credentials and reports success separately from errors',async({page})=>{
 await fixture(page,[]);const requests=[];
 await page.route('**/api/v1/sources/check-destination',route=>{requests.push(route.request().postDataJSON());return route.fulfill({json:{allowed:true}});});
 await page.goto('/sources/add');await page.getByLabel('Source type').selectOption('esxi');await page.getByLabel('Hostname or IPv4 address').fill('esxi.example.test');
 await page.getByRole('button',{name:'Check address without credentials'}).click();
 await expect(page.getByText('Address allowed by current DNS and destination policy.',{exact:false})).toBeVisible();
 await expect(page.locator('[name=secret]')).toBeEmpty();await expect(page.locator('[name=username]')).toBeEmpty();
 expect(requests).toEqual([{source_type:'esxi',address:'esxi.example.test',port:443}]);await expect(page.locator('.source-error')).toHaveCount(0);
});

test('unavailable history is explicit and cannot make an old plan actionable',async({page})=>{
 await fixture(page,[row('UPDATE')]);await page.route('**/api/v1/runs?*',r=>r.fulfill({status:503,json:{}}));
 await page.goto('/sources/source-1/sync');await expect(page.getByText('Run history unavailable. Confirmation is disabled until it can be checked.')).toBeVisible();
 await expect(page.getByRole('button',{name:'Review and confirm sync'})).toBeDisabled();
});
