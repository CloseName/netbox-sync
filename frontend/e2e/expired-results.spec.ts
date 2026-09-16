import {test,expect} from '@playwright/test';
import {source,diagnostics,run} from '../tests/fixtures.mjs';
for(const role of ['viewer','operator','admin'])test(`expired evidence with successful scheduled run ${role}`,async({page})=>{
 const item={...source(),enabled:true};let writes=0;
 const old='2025-01-01T00:00:00Z';
 await page.route('**/api/v1/**',r=>{
  const path=new URL(r.request().url()).pathname;
  if(r.request().method()!=='GET')writes++;
  if(path.endsWith('/auth/me'))return r.fulfill({json:{principal_id:'person',username:'person',role,permissions:['source.read','run.read','diagnostics.read',...(role==='viewer'?[]:['source.plan','source.apply'])]}});
  if(path.endsWith('/operations'))return r.fulfill({json:{operations:['PLAN','DISCOVERY'].map((kind,i)=>({operation_id:`00000000-0000-4000-8000-00000000000${i}`,source_instance:item.source_instance,operation_kind:kind,status:kind==='PLAN'?'STALE':'FAILED',started_at:old,updated_at:old,finished_at:old,result:null,safe_error_code:'RESULT_EXPIRED'}))}});
  if(path==='/api/v1/sources')return r.fulfill({json:{sources:[item]}});
  if(path==='/api/v1/sources/source-1')return r.fulfill({json:item});
  if(path.endsWith('/diagnostics'))return r.fulfill({json:diagnostics([item])});
  if(path.includes('/runs'))return r.fulfill({json:{runs:[{...run(),trigger:'scheduled'}],next_cursor:null}});
  if(path.endsWith('/schedule'))return r.fulfill({json:{source_instance:item.source_instance,sync_enabled:true,sync_interval_seconds:600,scheduler_state:'WAITING',last_scheduled_run_at:null,next_expected_at:null}});
  return r.fulfill({status:404,json:{}});
 });
 await page.goto('/sources/source-1/sync');
 await expect(page.getByText('The saved plan has expired. This is not a synchronization failure.')).toBeVisible();
 await expect(page.getByText('The discovery result has expired. Run history is unchanged.')).toBeVisible();
 await expect(page.getByRole('alert').filter({hasText:/RESULT_EXPIRED|Plan could not/})).toHaveCount(0);
 if(role==='viewer'){await expect(page.getByText('An Operator or Admin can build a new plan.')).toBeVisible();await expect(page.getByRole('button',{name:'Build plan',exact:true})).toBeDisabled();}
 else await expect(page.getByRole('button',{name:'Build plan',exact:true})).toBeEnabled();
 await page.reload();await expect(page.getByText('The saved plan has expired. This is not a synchronization failure.')).toBeVisible();expect(writes).toBe(0);
 await page.screenshot({path:`test-results/expired-results-${role}.png`,fullPage:true});
});
