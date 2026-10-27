import {test,expect} from './auth-fixture';

test('Selectel delete and reconnect can be repeated with automatic first collection and schedules off',async({page})=>{
 let row:any={account:'29916',name:'Cycle account',username:'reader',status:'completed',enabled:true,needs_credentials:false};
 let collections=0;
 await page.route('**/api/v1/**',async route=>{
  const req=route.request(),path=new URL(req.url()).pathname;
  if(path==='/api/v1/selectel')return route.fulfill({json:{items:[row],import_ready:true}});
  if(path.endsWith('/enabled')){row.enabled=req.postDataJSON().enabled;return route.fulfill({json:row});}
  if(path.endsWith('/lifecycle-review'))return route.fulfill({json:{...req.postDataJSON(),fingerprint:'a'.repeat(64),delete:[],retain:[],blockers:[]}});
  if(path.endsWith('/lifecycle-execute')){
   const operation=req.postDataJSON().operation;
   row=operation==='delete'?{account:'29916',name:'Cycle account',status:'deleted',deleted:true,enabled:false,needs_credentials:true}:
    {...row,status:'configured',deleted:false,connection_generation:`00000000-0000-4000-8000-00000000000${collections+1}`};
   return route.fulfill({json:{writes_performed:true}});
  }
  if(path==='/api/v1/selectel/connect'){
   const value=req.postDataJSON();expect(value.connection_generation).toBe(row.connection_generation);
   expect(value.password).toBe('cycle-secret');expect(value.account).toBe('29916');collections++;
   row={...row,username:value.username,status:'running',enabled:true,needs_credentials:false,schedule:{kind:'off'},next_run:null};
   return route.fulfill({json:row});
  }
  if(path.endsWith('/collect'))throw new Error('Reconnection already launches the first collection');
  if(path==='/api/v1/sources')return route.fulfill({json:{sources:[]}});
  if(path==='/api/v1/pfsense')return route.fulfill({json:{items:[],count:0}});
  if(path==='/api/v1/bootstrap')return route.fulfill({json:{revision:1,status:'READY',url:'https://netbox.test',completed:true,read_token_present:true,apply_token_present:true,checks:[]}});
  return route.fulfill({json:{}});
 });
 await page.goto('/sources/selectel');
 for(let cycle=1;cycle<=3;cycle++){
  await page.getByRole('button',{name:'Отключить аккаунт',exact:true}).click();
  const lifecycle=page.locator('details').filter({has:page.locator('summary', {hasText:'Отсоединение и удаление'})});
  await lifecycle.locator('summary').first().click();
  await page.getByRole('button',{name:'Проверить ресурсы перед удалением'}).click();
  await lifecycle.getByRole('checkbox').check();
  await page.getByRole('button',{name:'Применить проверенный план'}).click();
  await expect(page.getByText('Аккаунт удалён; доступ и расписание очищены',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Подготовить повторное подключение'}).click();
  await lifecycle.getByRole('checkbox').check();
  await page.getByRole('button',{name:'Применить проверенный план'}).click();
  await page.getByRole('button',{name:'Указать доступ и запустить сбор'}).click();
  await page.getByLabel('Сервисный пользователь',{exact:true}).fill('reader');
  await page.getByLabel('Пароль',{exact:true}).fill('cycle-secret');
  await page.getByRole('button',{name:'Подключить и собрать'}).click();
  await expect(page.getByRole('button',{name:'Сбор выполняется…'})).toBeDisabled();
  expect(collections).toBe(cycle);expect(row.schedule.kind).toBe('off');expect(row.next_run).toBeNull();
  await expect(page.locator('input[type=password]')).toHaveCount(0);
  row.status='completed';await page.reload();
  await expect(page.getByText('Импорт подтверждён',{exact:true})).toBeVisible();
 }
});

test('Confirmed Selectel refusal displays structural validation evidence without collecting',async({page})=>{
 await page.route('**/api/v1/**',async route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/collect'))throw new Error('Displaying a refusal must not collect');
  if(path==='/api/v1/selectel')return route.fulfill({json:{import_ready:true,items:[{
   account:'29916',name:'Validation account',username:'reader',status:'attention',error:'NETBOX_IMPORT_REFUSED',
   import_diagnostic:{reason:'OBJECT_VALIDATION',http_status:409,event_id:'fe88dd03-cd60-413a-ae8f-533ce23fdd9c',
    validation:{model:'dcim.device',object_id:28,phase:'full_clean',issues:[{field:'serial',code:'max_length'}]}}
  }]}});
  if(path==='/api/v1/sources')return route.fulfill({json:{sources:[]}});
  if(path==='/api/v1/pfsense')return route.fulfill({json:{items:[],count:0}});
  if(path==='/api/v1/bootstrap')return route.fulfill({json:{revision:1,status:'READY',url:'https://netbox.test',completed:true,read_token_present:true,apply_token_present:true,checks:[]}});
  return route.fulfill({json:{}});
 });
 await page.goto('/sources/selectel');
 await expect(page.getByText('Поля, не прошедшие проверку',{exact:true})).toBeVisible();
 await expect(page.locator('body')).toContainText('dcim.device');
 await expect(page.locator('body')).toContainText('max_length');
 await expect(page.locator('body')).toContainText('serial');
 await expect(page.getByRole('button',{name:'Собрать и обновить',exact:true})).toBeEnabled();
});

test('Selectel account onboarding, run and NetBox navigation do not expose saved password',async({page})=>{
 let rows:any[]=[], collections=0;
 await page.route('**/api/v1/**',async route=>{
  const req=route.request(),path=new URL(req.url()).pathname;
  if(path==='/api/v1/selectel/connect'){
    const {account,name,username,password,request_id,connection_generation}=req.postDataJSON();
    expect(password).toBe('fixture-secret');expect(request_id).toMatch(/^[0-9a-f-]{36}$/);expect(connection_generation).toBeNull();
    collections++;rows=[{account,name,username,status:'running',needs_credentials:false,enabled:true,schedule:{kind:'off'},url:'https://netbox.test/plugins/netbox-sync-guard/providers/'+account+'/'}];
    return route.fulfill({json:rows[0]});
  }
  if(path==='/api/v1/selectel'){
   if(req.method()==='POST'){
    const {account,name,username,password}=req.postDataJSON();expect(password).toBe('fixture-secret');
    rows=[{account,name,username,status:'configured',url:'https://netbox.test/plugins/netbox-sync-guard/providers/'+account+'/'}];
    return route.fulfill({json:rows[0]});
   }
   return route.fulfill({json:{items:rows,import_ready:true}});
  }
  if(path.endsWith('/collect')){collections++;rows[0].status='completed';return route.fulfill({json:rows[0]});}
  if(path==='/api/v1/sources')return route.fulfill({json:{sources:[]}});
  if(path==='/api/v1/pfsense')return route.fulfill({json:{items:[],count:0}});
  if(path==='/api/v1/bootstrap')return route.fulfill({json:{revision:1,status:'READY',url:'https://netbox.test',completed:true,read_token_present:true,apply_token_present:true,checks:[]}});
  return route.fulfill({json:{}});
 });
 await page.goto('/sources/selectel');
 await page.getByRole('button',{name:'Подключить аккаунт'}).click();
 await page.getByLabel('Название подключения').fill('Тестовый Selectel');
 await page.getByLabel('Номер аккаунта').fill('29916');
 await page.getByLabel('Сервисный пользователь').fill('reader');
 await page.getByLabel('Пароль',{exact:true}).fill('fixture-secret');
 await page.getByRole('button',{name:'Подключить и собрать'}).click();
 await expect(page.getByRole('button',{name:'Тестовый Selectel'})).toBeVisible();
 await expect(page.getByText('Сбор и импорт выполняются',{exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'Сбор выполняется…'})).toBeDisabled();
 expect(collections).toBe(1);
 await expect(page.locator('input[type=password]')).toHaveCount(0);
 await expect(page.getByRole('link',{name:'Ресурсы в NetBox ↗'})).toHaveAttribute('href','https://netbox.test/plugins/netbox-sync-guard/providers/29916/');
 rows[0].status='completed';
 await page.reload();
 await expect(page.getByText('Импорт подтверждён',{exact:true})).toBeVisible();
 expect(collections).toBe(1);
 await expect(page.locator('body')).not.toContainText('fixture-secret');
 await page.screenshot({path:'test-results/selectel-mvp.png',fullPage:true});
});

for(const error of ['IMPORT_UNCONFIRMED','RUN_INTERRUPTED']){
 test(`Selectel ${error} disables new import and exposes run reference`,async({page})=>{
  await page.route('**/api/v1/**',async route=>{
   const path=new URL(route.request().url()).pathname;
   if(path==='/api/v1/selectel')return route.fulfill({json:{import_ready:true,items:[{
    account:'123',name:'Uncertain account',username:'reader',status:'attention',error,
    run_id:'f5f3efcc-436a-4caf-8d21-d5492ba94f4c',url:'https://netbox.test/'
   }]}});
   if(path==='/api/v1/sources')return route.fulfill({json:{sources:[]}});
   if(path==='/api/v1/pfsense')return route.fulfill({json:{items:[],count:0}});
   if(path==='/api/v1/bootstrap')return route.fulfill({json:{revision:1,status:'READY',url:'https://netbox.test',completed:true,read_token_present:true,apply_token_present:true,checks:[]}});
   return route.fulfill({json:{}});
  });
  await page.goto('/sources/selectel');
  await expect(page.getByRole('button',{name:'Собрать и обновить'})).toBeDisabled();
  await expect(page.getByText('f5f3efcc-436a-4caf-8d21-d5492ba94f4c',{exact:false})).toBeVisible();
 });
}

test('Selectel receipt lookup displays absent evidence without enabling import',async({page})=>{
 let checks=0;
 const row:any={account:'29916',name:'Uncertain account',username:'reader',status:'attention',error:'IMPORT_UNCONFIRMED',
  run_id:'f5f3efcc-436a-4caf-8d21-d5492ba94f4c',url:'https://netbox.test/'};
 await page.route('**/api/v1/**',async route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/collect'))throw new Error('Receipt lookup must not import');
  if(path.endsWith('/reconcile')){checks++;row.reconciliation={outcome:'not_found',checked_at:1792053432,run_id:row.run_id};return route.fulfill({json:row});}
  if(path==='/api/v1/selectel')return route.fulfill({json:{import_ready:true,items:[row]}});
  if(path==='/api/v1/sources')return route.fulfill({json:{sources:[]}});
  if(path==='/api/v1/pfsense')return route.fulfill({json:{items:[],count:0}});
  if(path==='/api/v1/bootstrap')return route.fulfill({json:{revision:1,status:'READY',url:'https://netbox.test',completed:true,read_token_present:true,apply_token_present:true,checks:[]}});
  return route.fulfill({json:{}});
 });
 await page.goto('/sources/selectel');
 await page.getByRole('button',{name:'Проверить результат импорта',exact:true}).click();
 await expect(page.getByText('Квитанция запуска и следы его этапов не найдены.',{exact:false})).toBeVisible();
 await expect(page.getByRole('button',{name:'Собрать и обновить'})).toBeDisabled();
 expect(checks).toBe(1);
});


test('Historical baseline requires three confirmations and never starts collection',async({page})=>{
 let accepted=0;
 const run='f5f3efcc-436a-4caf-8d21-d5492ba94f4c';
 const row:any={account:'29916',name:'Old run',username:'reader',enabled:false,status:'attention',error:'IMPORT_UNCONFIRMED',run_id:run,url:'https://netbox.test/'};
 await page.route('**/api/v1/**',async route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/collect'))throw new Error('Baseline must not collect');
  if(path.endsWith('/lifecycle-review'))return route.fulfill({json:{operation:'baseline',key:run,fingerprint:'a'.repeat(64),retain:[],inventory_count:0,native_counts:{}}});
  if(path.endsWith('/lifecycle-execute')){
   expect(route.request().postDataJSON()).toEqual({operation:'baseline',key:run,fingerprint:'a'.repeat(64),confirmed:true});
   accepted++;row.status='baseline_accepted';row.error=null;
   return route.fulfill({json:{baseline_accepted:true}});
  }
  if(path==='/api/v1/selectel')return route.fulfill({json:{import_ready:true,items:[row]}});
  if(path==='/api/v1/sources')return route.fulfill({json:{sources:[]}});
  if(path==='/api/v1/pfsense')return route.fulfill({json:{items:[],count:0}});
  if(path==='/api/v1/bootstrap')return route.fulfill({json:{revision:1,status:'READY',url:'https://netbox.test',completed:true,read_token_present:true,apply_token_present:true,checks:[]}});
  return route.fulfill({json:{}});
 });
 await page.goto('/sources/selectel');
 await page.getByText('Принять текущее состояние после сверки',{exact:true}).click();
 await page.getByRole('button',{name:'Проверить текущее состояние NetBox'}).click();
 const accept=page.getByRole('button',{name:'Принять состояние и разрешить новый ручной сбор'});
 await expect(accept).toBeDisabled();
 const area=page.getByRole('region',{name:'Сверка исторического импорта'});
 for(const box of await area.getByRole('checkbox').all())await box.check();
 await accept.click();
 await expect(page.getByText('Текущее состояние принято; старый результат неизвестен',{exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'Собрать и обновить'})).toBeDisabled();
 expect(accepted).toBe(1);
});
