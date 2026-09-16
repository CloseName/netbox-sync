import {test,expect} from '@playwright/test';
import {openUserMenu} from './menu-helper';
for(const lang of ['en','ru'])for(const theme of ['light','dark'] as const)for(const width of [1440,390])
test(`unified sign in and session boundary ${lang} ${theme} ${width}`,async({page})=>{
 await page.setViewportSize({width,height:900});await page.emulateMedia({colorScheme:theme});
 let logged=false,code='AUTH_INVALID',attempts=0;
 await page.route('**/api/v1/**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/auth/status'))return route.fulfill({json:{enrollment_available:false}});
  if(path.endsWith('/auth/me'))return route.fulfill({status:logged?200:401,json:logged?{principal_id:'test-admin',username:'admin',role:'admin',permissions:['source.read']}:{error:{code:'AUTH_REQUIRED'}}});
  if(path.endsWith('/auth/login')){attempts++;expect(route.request().postDataJSON()).not.toHaveProperty('provider');if(code==='OK'){logged=true;return route.fulfill({json:{authenticated:true}});}return route.fulfill({status:code==='AUTH_INVALID'?401:503,json:{error:{code}}});}
  if(path.endsWith('/sources'))return route.fulfill({json:[]});
  return route.fulfill({status:503,json:{error:{code:'AUTH_UNAVAILABLE'}}});
 });
 await page.goto('/');await page.getByLabel('Language / Язык').selectOption(lang);
 const t=(en:string,ru:string)=>lang==='ru'?ru:en;
 await expect(page.locator('select[name=provider]')).toHaveCount(0);
 await expect(page.getByRole('button',{name:/invitation|приглашение/})).toHaveCount(0);
 await page.locator('[name=username]').fill('admin');await page.locator('[name=password]').fill('ephemeral-test-password');
 await page.getByRole('button',{name:t('Show password','Показать пароль')}).click();
 await expect(page.locator('[name=password]')).toHaveAttribute('type','text');expect(attempts).toBe(0);
 await page.getByRole('button',{name:t('Hide password','Скрыть пароль')}).click();
 await page.getByRole('button',{name:t('Sign in','Войти'),exact:true}).click();
 await expect(page.getByRole('alert')).toContainText(t('Username or password is incorrect.','Неверный логин или пароль'));
 await expect(page.locator('[name=username]')).toHaveValue('admin');await expect(page.locator('[name=password]')).toHaveValue('');
 await page.screenshot({path:`test-results/unified-login-${lang}-${theme}-${width}.png`,fullPage:true});
 code='AUTH_UNAVAILABLE';await page.locator('[name=password]').fill('ephemeral-test-password');await page.getByRole('button',{name:t('Sign in','Войти'),exact:true}).click();
 await expect(page.getByRole('alert')).toContainText(t('Authentication service is unavailable.','Служба входа недоступна.'));
 code='OK';await page.locator('[name=password]').fill('ephemeral-test-password');await page.getByRole('button',{name:t('Sign in','Войти'),exact:true}).click();
 await openUserMenu(page);await expect(page.getByRole('button',{name:t('Sign out','Выйти')})).toBeVisible();
 await page.keyboard.press('Escape');await expect(page.getByRole('button',{name:/User menu|Меню пользователя/})).toBeFocused();
 await page.evaluate(()=>fetch('/api/v1/policy'));await expect(page.getByRole('button',{name:/User menu|Меню пользователя/})).toBeVisible();
 await expect(page.getByRole('alert').first()).toContainText(t('Authorization is temporarily unavailable.','Проверка доступа временно недоступна.'));
 await page.route('**/api/v1/policy',route=>route.fulfill({status:401,json:{error:{code:'AUTH_REQUIRED'}}}));
 await page.evaluate(()=>fetch('/api/v1/policy'));await expect(page.getByRole('heading',{name:t('Sign in','Вход'),exact:true})).toBeVisible();
 expect(await page.evaluate(()=>JSON.stringify([localStorage,sessionStorage]).includes('ephemeral-test-password'))).toBe(false);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});
test('enrollment availability is server owned; explicit recovery retains invitation verification',async({page})=>{
 let available=true;
 await page.route('**/api/v1/**',r=>new URL(r.request().url()).pathname.endsWith('/status')?r.fulfill({json:{enrollment_available:available}}):r.fulfill({status:401,json:{error:{code:'AUTH_REQUIRED'}}}));
 await page.goto('/');await page.getByRole('button',{name:'I have an administrator invitation'}).click();await expect(page.locator('[name=invitation]')).toBeVisible();
 available=false;await page.reload();await expect(page.getByRole('button',{name:'I have an administrator invitation'})).toHaveCount(0);
 await page.goto('/?recovery=1');await expect(page.locator('[name=invitation]')).toBeVisible();
});
