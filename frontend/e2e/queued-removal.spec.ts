import {test,expect} from './auth-fixture';
import {source,diagnostics} from '../tests/fixtures.mjs';
for(const language of ['en','ru'])test(`confirmed removal waits across reload ${language}`,async({page,context})=>{
 const item=source();let operation:string|null=null,writes=0,finished=false;
 await page.addInitScript(language=>localStorage.setItem('netbox-sync.language',language),language);
 await context.route('**/api/v1/**',async r=>{
  const path=new URL(r.request().url()).pathname;
  if(path==='/api/v1/bootstrap')return r.fulfill({json:{revision:1,status:'READY',url:'https://netbox.test',completed:true,read_token_present:true,apply_token_present:true,safe_code:null,checks:[],validated_at:1}});
  if(path.endsWith('/lifecycle'))return r.fulfill({json:{source_instance:item.source_instance,display_name:item.name,removed_at:null,credential_state:null,revision:'a'.repeat(64),removal_blocker:operation?'SOURCE_RETIREMENT_PENDING':'SOURCE_OPERATION_ACTIVE',retirement:operation?{operation_id:operation,state:'WAITING',queued:true}:null}});
  if(path.endsWith('/removal-request')){const body=r.request().postDataJSON();expect(body.confirmed).toBe(true);expect(body.revision).toBe('a'.repeat(64));operation=body.operation_id;writes++;return r.fulfill({json:{source_instance:item.source_instance,operation_id:operation,state:'WAITING',queued:true}});}
  if(path.endsWith('/removal-status')){expect(r.request().postDataJSON().operation_id).toBe(operation);return r.fulfill({json:{source_instance:item.source_instance,operation_id:operation,state:finished?'FINALIZED':'WAITING',purged:finished}});}
  if(path==='/api/v1/sources')return r.fulfill({json:{sources:finished?[]:[item]}});
  if(path==='/api/v1/diagnostics')return r.fulfill({json:diagnostics([item])});
  if(path==='/api/v1/runs')return r.fulfill({json:{runs:[],next_cursor:null}});
  if(path.endsWith('/operations'))return r.fulfill({json:{operations:[]}});
  if(path.endsWith('/schedule'))return r.fulfill({json:{source_instance:item.source_instance,sync_enabled:true,sync_interval_seconds:600,scheduler_state:'WAITING',last_scheduled_run_at:null,next_expected_at:null}});
  return r.fulfill({json:item});
 });
 await page.setViewportSize({width:768,height:900});await page.goto('/sources/source-1/configuration');
 await page.getByRole('button',{name:language==='ru'?'Удалить источник':'Remove source',exact:true}).click();
 await page.getByRole('button',{name:language==='ru'?'Подтвердить удаление':'Confirm removal',exact:true}).click();
 await expect(page.getByText(language==='ru'?'Ожидаем завершения текущей операции…':'Waiting for the active operation…')).toBeVisible();
 await page.reload();await expect(page.getByText(language==='ru'?'Ожидаем завершения текущей операции…':'Waiting for the active operation…')).toBeVisible();
 expect(writes).toBe(1);finished=true;await expect(page).toHaveURL(/\/sources$/,{timeout:12000});expect(writes).toBe(1);
});
