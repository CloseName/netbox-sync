import {test,expect,type BrowserContext} from './auth-fixture';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
// Derive every visual fixture from the production Python contract; no second field list.
const plans=JSON.parse(execFileSync(process.env.PYTHON??'python',['-X','utf8','-c',`
import json
from netbox_sync.prerequisites import FIELDS,definition,reconcile
rows=[dict(definition(name),id=i+1,status='active') for i,name in enumerate(FIELDS)]
print(json.dumps(dict(missing=reconcile([]),partial=reconcile(rows[:6]),ready=reconcile(rows),conflict=reconcile([dict(rows[0],type='text')]))))
`],{cwd:fileURLToPath(new URL('../../',import.meta.url)),encoding:'utf8'}));
const fields=(status='missing')=>structuredClone(plans[status]);
async function mock(context:BrowserContext){
 const model={fail:false,conflict:false,expireFinish:false,uncertain:false,revocation:'CONFIRMED',state:{revision:0,status:'FRESH',url:'',completed:false,read_token_present:false,apply_token_present:false,safe_code:null,checks:[],validated_at:null,preparation:null} as any};
 await context.route('**/api/v1/**',async route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.startsWith('/api/v1/bootstrap')){
   const body=route.request().method()==='POST'?route.request().postDataJSON():null;
   if(body){expect(body.revision).toBe(model.state.revision);
    if(path.endsWith('/configuration'))model.state={...model.state,revision:model.state.revision+1,url:body.url,status:'CONFIGURED',read_token_present:true,apply_token_present:true,safe_code:null};
    if(path.endsWith('/validate')){const ready=model.state.preparation?.fields.every((f:any)=>f.status==='ready');model.state={...model.state,validated_at:model.fail||!ready?null:Date.now()/1000,status:model.fail||!ready?'ATTENTION':'VALIDATED',safe_code:model.fail?'AUTH_FAILED':ready?null:'PREREQUISITES_MISSING',access_checks:['network','tls','read_auth','apply_auth','permissions','prerequisites'].map(name=>({name,status:name==='permissions'?'preliminary':name==='prerequisites'&&!ready?'pending':'passed'}))};}
    if(path.endsWith('/prerequisites-plan'))model.state.preparation={...model.state.preparation,status:'PLANNED',digest:'a'.repeat(64),fields:model.state.preparation?.fields??fields(model.conflict?'conflict':'missing'),revocation:model.state.preparation?.revocation??'NOT_ATTEMPTED',local_secret:'NOT_STORED'};
    if(path.endsWith('/prerequisites-apply')){expect(body.confirm).toBe(true);expect(body.digest).toBe('a'.repeat(64));expect(body.setup_token).toBe('nbt_ABCDEFGHIJKL.TESTSETUPSECRET');model.state.preparation={...model.state.preparation,status:model.uncertain?'UNCERTAIN':'PREPARED',fields:fields(model.uncertain?'missing':'ready'),uncertain:model.uncertain?'cpu_model':null,revocation:model.uncertain?'UNCONFIRMED':model.revocation,local_secret:'NOT_STORED'};}
    if(path.endsWith('/finish')){if(model.expireFinish){model.expireFinish=false;return route.fulfill({status:409,json:{error:{code:'BOOTSTRAP_NOT_READY'}}});}model.state={...model.state,status:'READY',completed:true};}
   }
   return route.fulfill({json:model.state});
  }
  if(path==='/api/v1/sources')return route.fulfill({json:{sources:[]}});
  if(path.startsWith('/api/v1/runs'))return route.fulfill({json:{runs:[],next_cursor:null}});
  return route.fulfill({status:503,json:{}});
 });return model;
}
async function connect(page:any){
 await page.getByLabel('NetBox HTTPS URL',{exact:true}).fill('https://netbox.example.test');
 await page.getByLabel('Read-only token',{exact:true}).fill('FAKE-READ-TOKEN');
 await page.getByLabel('Apply token',{exact:true}).fill('FAKE-APPLY-TOKEN');
 await page.getByRole('button',{name:'Save and check access',exact:true}).click();
}
for(const width of [1440,768,390])test(`confirmed onboarding across browsers at ${width}`,async({page,context})=>{
 const model=await mock(context);await page.setViewportSize({width,height:900});await page.goto('/setup');
 await expect(page.getByText(/Not checked$/)).toHaveCount(0);
 await connect(page);await expect(page.getByRole('heading',{name:'Access check',exact:true})).toBeVisible();
 await expect(page.getByLabel('Read-only token',{exact:true})).toHaveCount(0);
 await expect(page.getByText('Preliminary check only')).toBeVisible();
 const other=await context.newPage();await other.goto('/setup');await expect(other.getByText('https://netbox.example.test',{exact:true})).toBeVisible();await other.close();
 await page.getByRole('button',{name:'Review preparation plan',exact:true}).click();
 await page.getByLabel('Temporary setup token',{exact:true}).fill('nbt_ABCDEFGHIJKL.TESTSETUPSECRET');
 await page.getByRole('checkbox').check();await page.getByRole('button',{name:'Create missing fields',exact:true}).click();
 await expect(page.getByText('The supplied setup token was revoked.')).toBeVisible();
 expect(await page.evaluate(()=>JSON.stringify(localStorage)+JSON.stringify(sessionStorage))).not.toContain('SECRET');
 await page.reload();await expect(page.getByText('The supplied setup token was revoked.')).toBeVisible();
 await page.getByRole('button',{name:'Recheck and review',exact:true}).click();
 model.expireFinish=true;await page.getByRole('button',{name:'Finish setup',exact:true}).click();
 await expect(page.getByRole('alert')).toContainText('Repeat the access check');
 // Explicit revalidation after expired finish, no credentials re-entry.
 await page.getByRole('button',{name:'Review preparation plan',exact:true}).click();
 await page.getByRole('button',{name:'Recheck and review',exact:true}).click();
 await page.getByRole('button',{name:'Finish setup',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Welcome to NetBox Sync'})).toHaveCount(0);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});
for(const language of ['en','ru'])for(const theme of ['light','dark'])for(const width of [1280,390])
test(`full contract gallery ${language} ${theme} ${width}`,async({page,context},info)=>{
 const model=await mock(context);await page.setViewportSize({width,height:1000});
 for(const scenario of ['missing','partial','conflict','success','unconfirmed']){
  model.state={...model.state,revision:1,status:'ATTENTION',url:'https://netbox.example.test',read_token_present:true,apply_token_present:true,
    preparation:{status:scenario==='success'||scenario==='unconfirmed'?'PREPARED':'PLANNED',fields:fields(['success','unconfirmed'].includes(scenario)?'ready':scenario),digest:'a'.repeat(64),local_secret:'NOT_STORED',revocation:scenario==='unconfirmed'?'UNCONFIRMED':scenario==='success'?'CONFIRMED':'NOT_ATTEMPTED'}};
  await page.goto('/setup');
  await page.getByRole('combobox',{name:'Language / Язык',exact:true}).selectOption(language);
  await page.getByRole('combobox',{name:language==='ru'?'Тема':'Theme',exact:true}).selectOption(theme);
  await expect(page.locator('[data-field]')).toHaveCount(16);
  const label=language==='ru'?'Временный токен подготовки':'Temporary setup token';
  if(scenario==='missing'||scenario==='partial'){
    await expect(page.getByLabel(label,{exact:true})).toBeVisible();
    await expect(page.getByRole('button',{name:language==='ru'?'Создать недостающие поля':'Create missing fields',exact:true})).toBeVisible();
  }
  if(scenario==='conflict'){
    await expect(page.locator('.setup-field-conflict')).toContainText(language==='ru'?'Тип: ожидается JSON, фактически: Текст':'Type: expected JSON, found Text');
    await expect(page.getByLabel(label,{exact:true})).toHaveCount(0);
    await expect(page.locator('.setup-plan-blocker')).toBeVisible();
  }
  if(scenario==='unconfirmed')await expect(page.getByRole('alert')).toContainText(language==='ru'?'Отзыв временного токена не подтверждён':'revocation is not confirmed');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:info.outputPath(`setup-${scenario}-${language}-${theme}-${width}.png`),fullPage:true});
  await page.getByRole('button',{name:language==='ru'?'Просмотреть все поля плана':'Review all field details',exact:true}).click();
  await expect(page.locator('[data-field]:visible')).toHaveCount(16);
  if(scenario==='missing'){
    await page.locator('[data-field]').first().getByText(language==='ru'?'Технические подробности':'Technical details',{exact:true}).click();
    await expect(page.locator('[data-field]').first().locator('code')).toHaveText(plans.missing[0].name);
  }
 }
 if(width===1280){
  await page.setViewportSize({width:780,height:1000});await page.evaluate(()=>document.body.style.zoom='2');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.getByRole('button',{name:language==='ru'?'Обновить состояние настройки':'Reload setup state',exact:true}).focus();
  await page.keyboard.press('Enter');
 }
});

test('conflict, uncertain result and auth replacement remain explicit',async({page,context})=>{
 const model=await mock(context);model.fail=true;await page.goto('/setup');await connect(page);
 await expect(page.getByText('NetBox rejected a token.')).toBeVisible();
 await page.getByRole('button',{name:'Replace credentials',exact:true}).click();model.fail=false;await connect(page);
 model.conflict=true;await page.getByRole('button',{name:'Review preparation plan',exact:true}).click();
 await expect(page.getByText('Type: expected JSON, found Text')).toBeVisible();await expect(page.getByLabel('Temporary setup token',{exact:true})).toHaveCount(0);
 model.conflict=false;model.state.preparation=null;await page.getByRole('button',{name:'Refresh preparation plan',exact:true}).click();
 model.uncertain=true;await page.getByLabel('Temporary setup token',{exact:true}).fill('nbt_ABCDEFGHIJKL.TESTSETUPSECRET');await page.getByRole('checkbox').check();
 await page.getByRole('button',{name:'Create missing fields',exact:true}).click();await expect(page.getByRole('alert').first()).toContainText('A write is uncertain');
 await expect(page.getByRole('button',{name:'Create missing fields',exact:true})).toHaveCount(0);
});
test('setup theme system, keyboard, narrow zoom and honest unchecked evidence',async({page,context})=>{
 const model=await mock(context);model.state={...model.state,status:'CONFIGURED',revision:1,read_token_present:true,apply_token_present:true,url:'https://netbox.example.test'};
 await page.emulateMedia({colorScheme:'dark'});await page.goto('/setup');await expect(page.locator('html')).toHaveAttribute('data-theme','dark');
 await expect(page.getByText(/Not checked$/)).toHaveCount(0);
 await expect(page.getByText('Detailed checks were not recorded in this release. A saved status is not a new access check.')).toBeVisible();
 await page.getByRole('combobox',{name:'Theme',exact:true}).selectOption('light');await page.emulateMedia({colorScheme:'dark'});await expect(page.locator('html')).toHaveAttribute('data-theme','light');
 await page.getByRole('combobox',{name:'Theme',exact:true}).selectOption('system');await expect(page.locator('html')).toHaveAttribute('data-theme','dark');
 await page.setViewportSize({width:780,height:900});await page.evaluate(()=>document.body.style.zoom='2');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.getByRole('button',{name:'Replace credentials',exact:true}).focus();await page.keyboard.press('Enter');
 await expect(page.getByRole('heading',{name:'Connection',exact:true})).toBeFocused();
});

for(const timestamp of [null,1])test(`historical VALIDATED ${timestamp} cannot finish or invent current checks`,async({page,context})=>{
 const model=await mock(context);model.state={...model.state,status:'VALIDATED',revision:4,url:'https://netbox.example.test',read_token_present:true,apply_token_present:true,validated_at:timestamp};
 await page.goto('/setup');
 await expect(page.getByRole('heading',{name:'Access check',exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'Finish setup',exact:true})).toHaveCount(0);
 await expect(page.getByRole('button',{name:'Review preparation plan',exact:true})).toHaveCount(0);
 await expect(page.getByText(/Not checked$/)).toHaveCount(0);
 await expect(page.getByRole('button',{name:'Check access again',exact:true})).toBeEnabled();
 model.state.preparation={fields:fields('ready')};
 await page.getByRole('button',{name:'Check access again',exact:true}).click();
 await expect(page.getByRole('button',{name:'Review preparation plan',exact:true})).toBeEnabled();
});
