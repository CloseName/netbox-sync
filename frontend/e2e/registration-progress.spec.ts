import {test,expect} from './auth-fixture';

for(const language of ['en','ru'])test(`saved registration result is read automatically ${language}`,async({page,context})=>{
 const attempt={source_instance:'esxi-saved-attempt',registration_id:'a5b7ae0b-609a-46f0-bf92-103eaa087dd3',request:null,created_at:'2026-09-28T00:00:00Z'};
 let reads=0,registered=false,writes=0;
 await context.route('**/api/v1/**',route=>route.fulfill({json:new URL(route.request().url()).pathname==='/api/v1/bootstrap'?{revision:1,status:'READY',url:'https://netbox.example.test',completed:true,read_token_present:true,apply_token_present:true,safe_code:null,checks:[],validated_at:1}:{}}));
 await page.addInitScript(language=>localStorage.setItem('netbox-sync.language',language),language);
 await context.route('**/api/v1/registration-attempts',r=>r.fulfill({json:{attempts:[attempt]}}));
 await context.route('**/api/v1/sources/registration-status',r=>{
  expect(r.request().postDataJSON()).toEqual({source_instance:attempt.source_instance,registration_id:attempt.registration_id});reads++;
  return r.fulfill({json:{status:registered?'REGISTERED':'UNCERTAIN',identity_status:'OUTCOME_UNCERTAIN'}});
 });
 await context.route('**/api/v1/sources',r=>{if(r.request().method()==='POST')writes++;return r.fulfill({json:{sources:[]}});});
 await page.goto('/sources/add');
 await page.getByRole('button',{name:attempt.source_instance,exact:true}).click();
 await expect.poll(()=>reads).toBeGreaterThan(0);
 await expect(page.getByRole('button',{name:/Check saved result|Сверить сохранённый результат/})).toHaveCount(0);
 await expect(page.getByText(attempt.registration_id,{exact:true})).toBeHidden();
 registered=true;
 await expect(page.getByRole('link',{name:language==='ru'?'Открыть источник':'Open source',exact:true})).toBeVisible({timeout:12000});
 expect(writes).toBe(0);
});
