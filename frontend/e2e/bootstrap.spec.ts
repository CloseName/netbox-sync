import {test,expect,type BrowserContext} from '@playwright/test';
const field=(status='missing')=>({name:'cpu_model',type:'text',models:['dcim.device'],status,differences:status==='conflict'?['type']:[],label:{en:'Host CPU model',ru:'Модель CPU хоста'},purpose:{en:'Observed physical host hardware.',ru:'Обнаруженное оборудование физического хоста.'}});
async function mock(context:BrowserContext){
 const model={fail:false,conflict:false,expireFinish:false,uncertain:false,revocation:'CONFIRMED',state:{revision:0,status:'FRESH',url:'',completed:false,read_token_present:false,apply_token_present:false,safe_code:null,checks:[],validated_at:null,preparation:null} as any};
 await context.route('**/api/v1/**',async route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.startsWith('/api/v1/bootstrap')){
   const body=route.request().method()==='POST'?route.request().postDataJSON():null;
   if(body){expect(body.revision).toBe(model.state.revision);
    if(path.endsWith('/configuration'))model.state={...model.state,revision:model.state.revision+1,url:body.url,status:'CONFIGURED',read_token_present:true,apply_token_present:true,safe_code:null};
    if(path.endsWith('/validate')){const ready=model.state.preparation?.fields.every((f:any)=>f.status==='ready');model.state={...model.state,status:model.fail||!ready?'ATTENTION':'VALIDATED',safe_code:model.fail?'AUTH_FAILED':ready?null:'PREREQUISITES_MISSING',access_checks:['network','tls','read_auth','apply_auth','permissions','prerequisites'].map(name=>({name,status:name==='permissions'?'preliminary':name==='prerequisites'&&!ready?'pending':'passed'}))};}
    if(path.endsWith('/prerequisites-plan'))model.state.preparation={...model.state.preparation,status:'PLANNED',digest:'a'.repeat(64),fields:model.state.preparation?.fields??[field(model.conflict?'conflict':'missing')],revocation:model.state.preparation?.revocation??'NOT_ATTEMPTED',local_secret:'NOT_STORED'};
    if(path.endsWith('/prerequisites-apply')){expect(body.confirm).toBe(true);expect(body.digest).toBe('a'.repeat(64));expect(body.setup_token).toBe('nbt_ABCDEFGHIJKL.TESTSETUPSECRET');model.state.preparation={...model.state.preparation,status:model.uncertain?'UNCERTAIN':'PREPARED',fields:[field(model.uncertain?'missing':'ready')],uncertain:model.uncertain?'cpu_model':null,revocation:model.uncertain?'UNCONFIRMED':model.revocation,local_secret:'NOT_STORED'};}
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
for(const theme of ['light','dark'])test(`onboarding visual states ${theme}`,async({page,context},info)=>{
 const model=await mock(context);await page.goto('/setup');await page.getByRole('combobox',{name:'Theme',exact:true}).selectOption(theme);
 await page.screenshot({path:info.outputPath(`setup-connection-${theme}.png`),fullPage:true});
 await connect(page);await page.getByRole('button',{name:'Review preparation plan',exact:true}).click();
 await page.screenshot({path:info.outputPath(`setup-plan-${theme}.png`),fullPage:true});
 model.revocation='UNCONFIRMED';await page.getByLabel('Temporary setup token',{exact:true}).fill('nbt_ABCDEFGHIJKL.TESTSETUPSECRET');
 await page.getByRole('checkbox').check();await page.getByRole('button',{name:'Create missing fields',exact:true}).click();
 await expect(page.getByRole('alert')).toContainText('revocation is not confirmed');
 await page.screenshot({path:info.outputPath(`setup-result-${theme}.png`),fullPage:true});
 await page.getByRole('combobox',{name:'Language',exact:true}).selectOption('ru');
 await expect(page.getByRole('heading',{name:'Подготовка NetBox',exact:true})).toBeVisible();
 await expect(page.getByRole('alert')).toContainText('Отзыв setup-token не подтверждён');
 await page.screenshot({path:info.outputPath(`setup-result-ru-${theme}.png`),fullPage:true});
});
test('conflict, uncertain result and auth replacement remain explicit',async({page,context})=>{
 const model=await mock(context);model.fail=true;await page.goto('/setup');await connect(page);
 await expect(page.getByText('NetBox rejected a token.')).toBeVisible();
 await page.getByRole('button',{name:'Replace credentials',exact:true}).click();model.fail=false;await connect(page);
 model.conflict=true;await page.getByRole('button',{name:'Review preparation plan',exact:true}).click();
 await expect(page.getByText('Conflict — review in NetBox')).toBeVisible();await expect(page.getByLabel('Temporary setup token',{exact:true})).toHaveCount(0);
 model.conflict=false;model.state.preparation=null;await page.getByRole('button',{name:'Refresh preparation plan',exact:true}).click();
 model.uncertain=true;await page.getByLabel('Temporary setup token',{exact:true}).fill('nbt_ABCDEFGHIJKL.TESTSETUPSECRET');await page.getByRole('checkbox').check();
 await page.getByRole('button',{name:'Create missing fields',exact:true}).click();await expect(page.getByRole('alert').first()).toContainText('A write is uncertain');
 await expect(page.getByRole('button',{name:'Create missing fields',exact:true})).toHaveCount(0);
});
test('setup theme system, keyboard, narrow zoom and honest unchecked evidence',async({page,context})=>{
 const model=await mock(context);model.state={...model.state,status:'CONFIGURED',revision:1,read_token_present:true,apply_token_present:true,url:'https://netbox.example.test'};
 await page.emulateMedia({colorScheme:'dark'});await page.goto('/setup');await expect(page.locator('html')).toHaveAttribute('data-theme','dark');
 await expect(page.getByText(/Not checked$/)).toHaveCount(6);
 await page.getByRole('combobox',{name:'Theme',exact:true}).selectOption('light');await page.emulateMedia({colorScheme:'dark'});await expect(page.locator('html')).toHaveAttribute('data-theme','light');
 await page.getByRole('combobox',{name:'Theme',exact:true}).selectOption('system');await expect(page.locator('html')).toHaveAttribute('data-theme','dark');
 await page.setViewportSize({width:780,height:900});await page.evaluate(()=>document.body.style.zoom='2');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.getByRole('button',{name:'Replace credentials',exact:true}).focus();await page.keyboard.press('Enter');
 await expect(page.getByRole('heading',{name:'Connection',exact:true})).toBeFocused();
});
