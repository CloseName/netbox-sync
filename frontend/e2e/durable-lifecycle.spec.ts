import {test, expect} from '@playwright/test';
import {randomUUID} from 'node:crypto';
import {source, diagnostics, run} from '../tests/fixtures.mjs';
const url='http://127.0.0.1:5179';
const digest='a'.repeat(64);
const canonical=(id:string)=>({source_instance:id,source_type:'proxmox',source_fingerprint:'s',target_fingerprint:'t',provider_fingerprint:'p',netbox_fingerprint:'n',schema_version:1,planner_version:'web-5a-1',digest,apply_allowed:true,items:[]});
function backend(){
  const sources=[source(),{...source(2),enabled:true}], slots=new Map<string,any>(), removed=new Map<string,any>();
  const calls:string[]=[];
  const lifecycle=(id:string)=>removed.get(id)??{source_instance:id,display_name:sources.find(s=>s.source_instance===id)?.name??id,removed_at:null,credential_state:null,revision:'a'.repeat(64)};
  const complete=(id:string,kind:string,status?:string)=>{const key=id+kind,row=slots.get(key);slots.set(key,{...row,status:status??(kind==='PLAN'?'READY':'SUCCEEDED'),finished_at:new Date().toISOString(),result:status?null:kind==='PLAN'?canonical(id):{source_instance:id,source_type:'proxmox',site_slug:'dc1',cluster_name:'Cluster 1',items:[]},safe_error_code:status==='FAILED'?'OPERATION_INTERRUPTED':null});};
  const attach=async(context:any)=>context.route('**/api/v1/**',async(route:any)=>{
    const request=route.request(),path=new URL(request.url()).pathname,id=path.split('/')[4];
    if(path.endsWith('/operations')) return route.fulfill({json:{operations:[...slots.values()].filter(r=>r.source_instance===id)}});
    if(/\/operations\/(plan|discovery)$/.test(path)){
      const kind=path.endsWith('/plan')?'PLAN':'DISCOVERY',key=id+kind;
      if(slots.get(key)?.status!=='RUNNING') {const now=new Date().toISOString();slots.set(key,{operation_id:randomUUID(),source_instance:id,operation_kind:kind,status:'RUNNING',started_at:now,updated_at:now,finished_at:null,result:null,safe_error_code:null});calls.push(key);}
      return route.fulfill({status:202,json:slots.get(key)});
    }
    if(path.endsWith('/lifecycle'))return route.fulfill({json:lifecycle(id)});
    if(path.endsWith('/remove')){
      if([...slots.values()].some(row=>row.source_instance===id&&row.status==='RUNNING'))return route.fulfill({status:409,json:{error:{code:'SOURCE_OPERATION_ACTIVE'}}});
      const body=request.postDataJSON();expect(body.confirmed_source).toBe(id);expect(body.revision).toBe('a'.repeat(64));
      removed.set(id,{...lifecycle(id),revision:null,removed_at:new Date().toISOString(),credential_state:body.remove_credentials?'REMOVED':'RETAINED_BY_REQUEST'});
      return route.fulfill({json:lifecycle(id)});
    }
    if(path==='/api/v1/sources')return route.fulfill({json:{sources:sources.filter(s=>!removed.has(s.source_instance))}});
    if(path==='/api/v1/diagnostics')return route.fulfill({json:diagnostics(sources)});
    if(path==='/api/v1/runs')return route.fulfill({json:{runs:[run()],next_cursor:null}});
    if(path.endsWith('/schedule'))return route.fulfill({json:{source_instance:id,sync_enabled:true,sync_interval_seconds:600,scheduler_state:'WAITING',last_scheduled_run_at:null,next_expected_at:null}});
    const found=sources.find(s=>s.source_instance===id&&!removed.has(id));
    return route.fulfill({status:found?200:404,json:found??{error:{code:'SOURCE_NOT_FOUND'}}});
  });
  return {attach,slots,complete,calls,removed};
}
test('two browsers share Plan and Discovery; close, reopen, deduplicate and isolate sources',async({browser})=>{
  const server=backend(),a=await browser.newContext(),b=await browser.newContext();
  await server.attach(a);await server.attach(b);
  try{
    const first=await a.newPage();await first.goto(url+'/sources/source-1/sync');await first.getByRole('button',{name:'Build plan',exact:true}).click();
    const second=await b.newPage();await second.goto(url+'/sources/source-1/sync');await expect(second.getByText(/Planning in progress/)).toBeVisible();
    await expect(second.getByRole('button',{name:'Build plan',exact:true})).toBeDisabled();
    const original=server.slots.get('source-1PLAN').operation_id;
    const duplicate=await second.evaluate(async()=>{const response=await fetch('/api/v1/sources/source-1/operations/plan',{method:'POST',headers:{'Content-Type':'application/json','X-NetBox-Sync-CSRF':'same-origin'},body:'{}'});return response.json();});
    expect(duplicate.operation_id).toBe(original);expect(server.calls.filter(c=>c==='source-1PLAN')).toHaveLength(1);
    await second.getByRole('button',{name:'Run discovery',exact:true}).click();
    await first.reload();await expect(first.getByText(/Discovering source/)).toBeVisible();
    await expect(first.getByRole('button',{name:'Run discovery',exact:true})).toBeDisabled();
    const discoveryId=server.slots.get('source-1DISCOVERY').operation_id;
    const duplicateDiscovery=await first.evaluate(async()=>{const response=await fetch('/api/v1/sources/source-1/operations/discovery',{method:'POST',headers:{'Content-Type':'application/json','X-NetBox-Sync-CSRF':'same-origin'},body:'{}'});return response.json();});
    expect(duplicateDiscovery.operation_id).toBe(discoveryId);expect(server.calls.filter(c=>c==='source-1DISCOVERY')).toHaveLength(1);
    const other=await b.newPage();await other.goto(url+'/sources/source-2/sync');await other.getByRole('button',{name:'Build plan',exact:true}).click();expect(server.calls).toContain('source-2PLAN');
    await first.close();server.complete('source-1','PLAN');server.complete('source-1','DISCOVERY');
    await expect(second.getByText('Plan ready for review.')).toBeVisible();await second.reload();await expect(second.getByText('Plan ready for review.')).toBeVisible();
    expect(server.slots.get('source-1PLAN').operation_id).toBe(original);expect(server.slots.get('source-2PLAN').status).toBe('RUNNING');
  }finally{await a.close();await b.close();}
});
test('failed and stale generations remain visible after reopening',async({page,context})=>{
  const server=backend();await server.attach(context);await page.goto(url+'/sources/source-1/sync');await page.getByRole('button',{name:'Build plan',exact:true}).click();server.complete('source-1','PLAN','FAILED');await page.reload();await expect(page.getByText(/The operation did not complete/)).toBeVisible();server.complete('source-1','PLAN','STALE');await page.reload();await expect(page.getByText('Plan is no longer current. Build a new plan.')).toBeVisible();await expect(page.getByRole('button',{name:'Review and confirm sync'})).toHaveCount(0);
});
for(const width of [1440,1024,768])test(`Remove Source confirmation, active blocker and tombstone at ${width}`,async({page,context},info)=>{
  const server=backend();await server.attach(context);await page.setViewportSize({width,height:900});
  await page.goto(url+'/sources/source-1/sync');await page.getByRole('button',{name:'Build plan',exact:true}).click();
  await page.getByRole('navigation',{name:'Source sections'}).getByRole('link',{name:'Configuration',exact:true}).click();
  await page.getByRole('button',{name:'Remove Source',exact:true}).click();const dialog=page.getByRole('dialog');
  await expect(dialog.getByRole('button',{name:'Remove Source',exact:true})).toBeDisabled();await dialog.getByLabel('Type the exact Source ID').fill('source-1');
  await page.screenshot({path:info.outputPath('remove-confirmation.png'),fullPage:true});
  await dialog.getByRole('button',{name:'Remove Source',exact:true}).click();await expect(dialog.getByText('Wait for active Plan or Discovery to finish.')).toBeVisible();
  server.complete('source-1','PLAN');await dialog.getByRole('checkbox').check();await dialog.getByRole('button',{name:'Remove Source',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Source removed from NetBox Sync'})).toBeVisible();await expect(page.getByText(/Local stored credentials removed/)).toBeVisible();
  await page.reload();await expect(page.getByRole('heading',{name:'Source removed from NetBox Sync'})).toBeVisible();await expect(page.getByRole('button',{name:'Build plan'})).toHaveCount(0);
  await page.screenshot({path:info.outputPath('removed-source.png'),fullPage:true});await page.getByRole('link',{name:'Back to Sources',exact:true}).click();expect(server.removed.has('source-1')).toBe(true);
});

for(const width of [1440,1024,768])test(`Durable operation states at ${width}`,async({page,context},info)=>{
  const server=backend();await server.attach(context);await page.setViewportSize({width,height:900});
  await page.goto(url+'/sources/source-1/sync');await page.getByRole('button',{name:'Build plan',exact:true}).click();
  await page.getByRole('button',{name:'Run discovery',exact:true}).click();await page.reload();
  await expect(page.getByText(/Discovering source/)).toBeVisible();await expect(page.getByText(/Planning in progress/)).toBeVisible();
  await page.screenshot({path:info.outputPath('operations-running.png'),fullPage:true});
  server.complete('source-1','PLAN');server.complete('source-1','DISCOVERY');await page.reload();
  await expect(page.getByText('Plan ready for review.')).toBeVisible();await page.screenshot({path:info.outputPath('operations-ready.png'),fullPage:true});
  await page.getByRole('button',{name:'Rebuild plan',exact:true}).click();server.complete('source-1','PLAN','FAILED');await page.reload();
  await expect(page.getByText(/The operation did not complete/)).toBeVisible();await page.screenshot({path:info.outputPath('operations-failed.png'),fullPage:true});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
});

for(const width of [1440,1024,768])test(`Reserved Source ID is explained during registration at ${width}`,async({page,context},info)=>{
  const server=backend();await server.attach(context);await page.setViewportSize({width,height:900});
  await page.route('**/api/v1/sources/test-connection',route=>route.fulfill({json:{status:'success',onboarding_token:'test-onboarding-token-123456789'}}));
  await page.route('**/api/v1/sources',route=>route.request().method()==='POST'?route.fulfill({status:409,json:{error:{code:'SOURCE_ID_RESERVED'}}}):route.fallback());
  await page.goto(url+'/sources/add');
  await page.getByRole('textbox',{name:'Hostname or IPv4 address'}).fill('host.example.test');
  await page.getByLabel('Token user (user@realm)').fill('user@realm');
  await page.getByLabel('Token name (without user prefix)').fill('test-token');
  await page.getByLabel('Token secret').fill('FAKE-SECRET');
  await page.getByRole('button',{name:'Test Connection',exact:true}).click();
  for(const [label,value] of Object.entries({'Source ID':'source-1','Display name':'Source 001','Site slug':'dc1','Cluster name':'Cluster 1','Platform slug':'linux','Device role slug':'server','Device type slug':'server','Cluster type slug':'cluster'}))await page.getByRole('textbox',{name:label,exact:true}).fill(value);
  await page.getByRole('checkbox',{name:'Register a new source with automatic sync OFF.'}).check();
  await page.getByRole('button',{name:'Register Source',exact:true}).click();
  await expect(page.getByText('This Source ID was previously used and is reserved by a removed source.')).toBeVisible();
  await expect(page.getByRole('heading',{name:'Source registered',exact:true})).toHaveCount(0);
  await page.screenshot({path:info.outputPath('reserved-source-id.png'),fullPage:true});
});
