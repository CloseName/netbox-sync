import {previewResult} from './source-placement-fixture';
import {test,expect} from '@playwright/test';
for(const lang of ['en','ru'])for(const theme of ['light','dark'] as const)for(const width of [1440,390])
test(`explicit destination permission ${lang} ${theme} ${width}`,async({page})=>{
 await page.setViewportSize({width,height:900});await page.emulateMedia({colorScheme:theme});
 let allowed=false,revision=1,policyWrites=0,probes=0,conflict=true;
 await page.route('**/api/v1/**',async route=>{
  const path=new URL(route.request().url()).pathname,method=route.request().method();
  if(path.endsWith('/auth/me'))return route.fulfill({json:{principal_id:'admin-fixture',username:'admin',permissions:['policy.read','policy.write','source.probe']}});
  if(path.endsWith('/bootstrap'))return route.fulfill({json:{revision:1,status:'READY',completed:true,url:'https://netbox.test',read_token_present:true,apply_token_present:true,safe_code:null,validated_at:1,checks:[]}});
  if(path.endsWith('/policy')){
   if(method==='POST'){
    policyWrites++;const body=route.request().postDataJSON();
    expect(body.host).toBe('esxi.public.example');expect(body.expected_revision).toBe(revision);
    if(conflict){conflict=false;revision++;return route.fulfill({status:409,json:{error:{code:'POLICY_CONFLICT'}}});}
    allowed=body.operation!=='revoke';revision++;return route.fulfill({json:{revision}});
   }
   return route.fulfill({json:{revision,mode:'managed',ceiling:'public-ipv4',allowed_hosts:allowed?['esxi.public.example']:[],denied_cidrs:[],effective:{allowed_cidrs:['10.0.0.0/8'],allowed_hosts:allowed?['esxi.public.example']:[],denied_cidrs:[],allowed_suffixes:[]}}});
  }
  if(path.endsWith('/sources/test-connection')){probes++;return route.fulfill(allowed?{json:previewResult}:{status:422,json:{error:{code:'SOURCE_DESTINATION_DENIED'}}});}
  return route.fulfill({status:503,json:{error:{code:'UNAVAILABLE'}}});
 });
 await page.goto('/sources/add');await page.getByLabel('Language / Язык').selectOption(lang);
 await page.locator('form select').selectOption('esxi');
 await page.locator('form input[pattern]').fill('esxi.public.example');
 async function probe(){await page.locator('input[name=username]').fill('netbox-sync');await page.locator('input[name=secret]').fill('fixture-only-password');await page.locator('form button.primary').click();}
 await probe();
 const allow=page.getByRole('button',{name:lang==='ru'?'Разрешить назначение':'Allow destination',exact:true});
 await expect(allow).toBeVisible();expect(policyWrites).toBe(0);
 await page.screenshot({path:`test-results/auth-policy-denied-${lang}-${theme}-${width}.png`,fullPage:true});
 await allow.click();await expect(page.getByText(lang==='ru'?'Политика изменилась. Обновите и проверьте её перед подтверждением.':'Policy changed. Reload and review before confirming.')).toBeVisible();
 expect(probes).toBe(1);
 await page.getByRole('button',{name:lang==='ru'?'Обновить политику':'Reload policy',exact:true}).click();await allow.click();
 await expect(allow).toHaveCount(0);expect(probes).toBe(1);
 await probe();await expect(page.getByRole('heading',{name:lang==='ru'?'Проверьте параметры источника':'Review source details'})).toBeVisible();
 await page.goto('/policy');await expect(page.getByText('esxi.public.example',{exact:true})).toBeVisible();
 await page.screenshot({path:`test-results/auth-policy-allowed-${lang}-${theme}-${width}.png`,fullPage:true});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.getByRole('button',{name:lang==='ru'?'Отозвать разрешение панели':'Revoke web permission'}).click();
 await expect(page.getByText(lang==='ru'?'Разрешения через панель не добавлены.':'No web permissions added.')).toBeVisible();
 expect(policyWrites).toBe(3);
});
