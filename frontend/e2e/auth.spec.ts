import {test,expect} from '@playwright/test';
for(const lang of ['en','ru'])for(const theme of ['light','dark'] as const)for(const width of [1440,390])
test(`local sign in and expiry ${lang} ${theme} ${width}`,async({page})=>{
 await page.setViewportSize({width,height:900});await page.emulateMedia({colorScheme:theme});
 let logged=false,writes=0,businessCode='UNAVAILABLE';
 await page.route('**/api/v1/**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/auth/me'))return route.fulfill({status:logged?200:401,json:logged?{principal_id:'test-admin',username:'admin',permissions:['policy.write']}:{error:{code:'AUTH_REQUIRED'}}});
  if(path.endsWith('/auth/login')){logged=true;return route.fulfill({json:{authenticated:true}});}
  if(path.endsWith('/auth/logout')){logged=false;return route.fulfill({json:{logged_out:true}});}
  if(route.request().method()==='POST')writes++;
  if(path.endsWith('/bootstrap'))return route.fulfill({json:{revision:1,status:'READY',completed:true,url:'https://netbox.test',read_token_present:true,apply_token_present:true,safe_code:null,checks:[],validated_at:1}});
  return route.fulfill({status:businessCode==='AUTH_REQUIRED'?401:businessCode==='AUTH_DENIED'?403:503,json:{error:{code:businessCode}}});
 });
 await page.goto('/');await page.getByLabel('Language / Язык').selectOption(lang);
 await expect(page.getByRole('heading',{name:lang==='ru'?'Вход':'Sign in',exact:true})).toBeVisible();
 await page.screenshot({path:`test-results/auth-login-${lang}-${theme}-${width}.png`,fullPage:true});
 await page.locator('input[name=username]').fill('admin');await page.locator('input[name=password]').fill('test-only-password-9284');
 await page.getByRole('button',{name:lang==='ru'?'Войти':'Sign in',exact:true}).click();
 await expect(page.getByRole('button',{name:lang==='ru'?'Выйти':'Sign out'})).toBeVisible();
 businessCode='AUTH_REQUIRED';await page.evaluate(()=>fetch('/api/v1/sources'));
 await expect(page.getByRole('heading',{name:lang==='ru'?'Вход':'Sign in',exact:true})).toBeVisible();
 await page.screenshot({path:`test-results/auth-expired-${lang}-${theme}-${width}.png`,fullPage:true});
 expect(writes).toBe(0);
 expect(await page.evaluate(()=>Object.values(localStorage).some(value=>String(value).includes('test-only-password')))).toBe(false);
 await page.getByRole('button',{name:lang==='ru'?'У меня есть приглашение администратора':'I have an administrator invitation'}).click();
 await expect(page.locator('input[name=invitation]')).toBeVisible();
 await page.screenshot({path:`test-results/auth-enrollment-${lang}-${theme}-${width}.png`,fullPage:true});
 for(const [code,label] of [['AUTH_UNAVAILABLE','unavailable'],['AUTH_DENIED','denied']]){
  businessCode=code;await page.evaluate(()=>fetch('/api/v1/policy'));
  await expect(page.getByRole('alert')).toBeVisible();
  await page.screenshot({path:`test-results/auth-${label}-${lang}-${theme}-${width}.png`,fullPage:true});
 }
 expect(writes).toBe(0);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});
