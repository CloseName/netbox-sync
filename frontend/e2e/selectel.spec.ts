import {test,expect} from './auth-fixture';

test('Selectel account onboarding, run and NetBox navigation do not expose saved password',async({page})=>{
 let rows:any[]=[], collections=0;
 await page.route('**/api/v1/**',async route=>{
  const req=route.request(),path=new URL(req.url()).pathname;
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
 await page.getByRole('button',{name:'Сохранить подключение'}).click();
 await expect(page.getByRole('button',{name:'Тестовый Selectel'})).toBeVisible();
 expect(collections).toBe(0);
 await expect(page.locator('input[type=password]')).toHaveCount(0);
 await expect(page.getByRole('link',{name:'Ресурсы в NetBox ↗'})).toHaveAttribute('href','https://netbox.test/plugins/netbox-sync-guard/providers/29916/');
 await page.getByRole('button',{name:'Собрать и обновить'}).click();
 await expect(page.getByText('Данные обновлены',{exact:true})).toBeVisible();
 expect(collections).toBe(1);
 await expect(page.locator('body')).not.toContainText('fixture-secret');
 await page.screenshot({path:'test-results/selectel-mvp.png',fullPage:true});
});
