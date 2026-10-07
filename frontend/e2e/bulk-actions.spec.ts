import {test,expect} from './auth-fixture';
import {source,diagnostics} from '../tests/fixtures.mjs';

test('bulk schedules preserve selection scope and current settings',async({page})=>{
 const sources=[source(1),source(2)],writes:any[]=[];
 await page.route('**/api/v1/**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path==='/api/v1/bootstrap')return route.fulfill({json:{revision:1,status:'READY',url:'https://netbox.test',completed:true,read_token_present:true,apply_token_present:true,safe_code:null,checks:[],validated_at:1}});
  if(path==='/api/v1/teams')return route.fulfill({json:{version:1,revision:0,teams:{},assignments:{}}});
  if(path==='/api/v1/sources')return route.fulfill({json:{sources}});
  if(path==='/api/v1/diagnostics')return route.fulfill({json:diagnostics(sources)});
  const match=path.match(/sources\/(source-\d+)\/schedule$/);
  if(match){
   const before={source_instance:match[1],sync_enabled:true,sync_interval_seconds:900,sync_calendar:{mode:'daily',time:'20:51',timezone:'Europe/Moscow'},scheduler_state:'WAITING',last_scheduled_run_at:null,next_expected_at:null};
   if(route.request().method()==='PATCH'){
    const update=route.request().postDataJSON();writes.push({source:match[1],...update});
    return route.fulfill({json:{...before,...update}});
   }return route.fulfill({json:before});
  }
  return route.fulfill({status:404,json:{}});
 });
 await page.goto('/sources');
 await page.getByRole('checkbox',{name:'Select Source 001',exact:true}).check();
 await page.getByRole('button',{name:'Disable selected schedules',exact:true}).click();
 await expect(page.getByRole('status').filter({hasText:'Schedule disabled'})).toBeVisible();
 expect(writes).toHaveLength(1);expect(writes[0]).toMatchObject({source:'source-1',sync_enabled:false,sync_interval_seconds:900,sync_calendar:{mode:'daily',time:'20:51'},expected_sync_enabled:true});
 await page.getByRole('checkbox',{name:'Select this page',exact:true}).check();
 await page.getByRole('button',{name:'Set schedule',exact:true}).click();
 const dialog=page.getByRole('dialog');
 await expect(dialog.getByRole('combobox',{name:'Frequency',exact:true})).toHaveValue('600');
 await expect(dialog.getByRole('spinbutton',{name:'Seconds',exact:true})).toHaveCount(0);
 await dialog.getByRole('combobox',{name:'Mode',exact:true}).selectOption('weekly');
 await dialog.getByLabel('MSK',{exact:true}).fill('21:05');
 await dialog.getByLabel('Weekday (1 = Monday)',{exact:true}).fill('5');
 await dialog.getByRole('button',{name:'Apply to selected',exact:true}).click();
 await expect.poll(()=>writes.length).toBe(3);
 expect(writes.slice(1).map(w=>w.source)).toEqual(['source-1','source-2']);
 for(const write of writes.slice(1))expect(write.sync_calendar).toEqual({mode:'weekly',time:'21:05',day:5,timezone:'Europe/Moscow'});
 await page.screenshot({path:'test-results/bulk-schedules.png',fullPage:true});
});

test('bulk removal requires reviewed confirmation and reports partial failures',async({page})=>{
 const sources=[source(1),source(2)],plans=new Map<string,any>(),writes:any[]=[];
 await page.route('**/api/v1/**',route=>{
  const path=new URL(route.request().url()).pathname,id=path.split('/')[4];
  if(path==='/api/v1/bootstrap')return route.fulfill({json:{revision:1,status:'READY',url:'https://netbox.test',completed:true,read_token_present:true,apply_token_present:true,safe_code:null,checks:[],validated_at:1}});
  if(path==='/api/v1/teams')return route.fulfill({json:{version:1,revision:0,teams:{},assignments:{}}});
  if(path==='/api/v1/sources')return route.fulfill({json:{sources}});
  if(path==='/api/v1/diagnostics')return route.fulfill({json:diagnostics(sources)});
  if(path.endsWith('/lifecycle'))return route.fulfill({json:{source_instance:id,display_name:sources.find(s=>s.source_instance===id)!.name,removed_at:null,credential_state:null,revision:'a'.repeat(64)}});
  if(path.endsWith('/retirement-review')){
   const plan={source_instance:id,operation_id:route.request().postDataJSON().operation_id,state:'READY',revision:'a'.repeat(64),digest:'b'.repeat(64),manifest:{format:2,cluster_id:7,objects:[['vm:10','c'.repeat(64)]]}};
   plans.set(id,plan);return route.fulfill({json:plan});
  }
  if(path.endsWith('/retire')){
   const payload=route.request().postDataJSON();writes.push({id,...payload});
   expect(payload.operation_id).toBe(plans.get(id).operation_id);expect(payload.digest).toBe(plans.get(id).digest);
   expect(payload.confirmed_source).toBe(sources.find(s=>s.source_instance===id)!.name);
   return id==='source-1'?route.fulfill({json:{...plans.get(id),state:'FINALIZED'}}):route.fulfill({status:409,json:{error:{code:'RETIREMENT_CONFLICT'}}});
  }
  return route.fulfill({status:404,json:{}});
 });
 await page.goto('/sources');await page.getByRole('checkbox',{name:'Select this page',exact:true}).check();
 await page.getByRole('button',{name:'Delete resources',exact:true}).click();
 const dialog=page.getByRole('dialog');
 await expect(dialog.getByRole('button',{name:'Yes, delete',exact:true})).toBeDisabled();
 await expect(dialog.getByText('vm:10',{exact:true})).toHaveCount(0);
 expect(writes).toHaveLength(0);
 await dialog.getByRole('button',{name:'Cancel / Close',exact:true}).click();expect(writes).toHaveLength(0);
 await page.getByRole('button',{name:'Delete resources',exact:true}).click();
 await dialog.getByLabel('Confirm source Source 001',{exact:true}).fill('Source 001');
 await expect(dialog.getByRole('button',{name:'Yes, delete',exact:true})).toBeDisabled();
 await dialog.getByLabel('Confirm source Source 002',{exact:true}).fill('Source 002');
 await dialog.getByRole('button',{name:'Yes, delete',exact:true}).click();
 await expect.poll(()=>writes.length).toBe(2);
 await expect(dialog.getByRole('button',{name:'Yes, delete',exact:true})).toBeDisabled();
 await dialog.getByRole('button',{name:'Cancel / Close',exact:true}).click();
 await expect(page.getByText('Source 001: Removed',{exact:true})).toBeVisible();
 await expect(page.getByText(/Source 002: Result requires checking/)).toBeVisible();
});

test('disable all includes filtered-out sources and independent pfSense collection',async({page})=>{
 const sources=[source(1),source(2)],disabled:string[]=[];
 await page.route('**/api/v1/**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path==='/api/v1/bootstrap')return route.fulfill({json:{revision:1,status:'READY',url:'https://netbox.test',completed:true,read_token_present:true,apply_token_present:true,safe_code:null,checks:[],validated_at:1}});
  if(path==='/api/v1/teams')return route.fulfill({json:{version:1,revision:0,teams:{},assignments:{}}});
  if(path==='/api/v1/sources')return route.fulfill({json:{sources}});
  if(path==='/api/v1/diagnostics')return route.fulfill({json:diagnostics(sources)});
  if(path==='/api/v1/pfsense')return route.fulfill({json:{count:1,items:[{id:2609,name:'pfSense',cluster:'PVE',site:'Test',address:'10.24.0.1',url:'https://nb.test/vm/2609/'}]}});
  if(path==='/api/v1/policy')return route.fulfill({json:{revision:5}});
  if(path==='/api/v1/pfsense/2609/status')return route.fulfill({json:{status:'CONNECTED',ssh_port:22,sync_enabled:true,interval_minutes:60}});
  if(path==='/api/v1/pfsense/2609/schedule'){
   expect(route.request().postDataJSON()).toEqual({sync_enabled:false,interval_minutes:60,policy_revision:5});
   disabled.push('pfSense');return route.fulfill({json:{status:'CONNECTED'}});
  }
  const match=path.match(/sources\/(source-\d+)\/schedule$/);
  if(match){
   const state={source_instance:match[1],sync_enabled:true,sync_interval_seconds:900,sync_calendar:null,scheduler_state:'WAITING',last_scheduled_run_at:null,next_expected_at:null};
   if(route.request().method()==='PATCH'){expect(route.request().postDataJSON().sync_enabled).toBe(false);disabled.push(match[1]);}
   return route.fulfill({json:state});
  }
  return route.fulfill({status:404,json:{}});
 });
 await page.goto('/sources?provider=proxmox');
 await expect(page.getByRole('checkbox',{name:'Select Source 002',exact:true})).toHaveCount(0);
 await page.getByRole('button',{name:'Disable all scheduled sync, including pfSense',exact:true}).click();
 await expect.poll(()=>disabled).toEqual(['source-1','source-2','pfSense']);
 await expect(page.getByText('pfSense: pfSense collection disabled',{exact:true})).toBeVisible();
});
