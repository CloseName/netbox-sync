import { test, expect } from './operation-fixture';
import { randomUUID } from 'node:crypto';
async function fixture(page, code = 'SOURCE_TLS_FAILED') {
 await page.route('**/api/v1/**', route => route.fulfill({status: route.request().method() === 'POST' ? 400 : 200, json: route.request().method() === 'POST' ? {error:{code,message:'REMOTE_DETAIL_MUST_NOT_ESCAPE'}} : {sources:[]}}));
 await page.goto('/sources/add');
}
for (const language of ['en','ru']) for (const theme of ['light','dark']) {
 test(`access guidance ${language} ${theme} narrow and zoom`, async ({page, context}) => {
  await context.grantPermissions(['clipboard-read','clipboard-write']);
  await page.setViewportSize({width:390,height:844});
  await page.emulateMedia({colorScheme:theme});
  await fixture(page);
  await page.getByLabel('Language / Язык').selectOption(language);
  await page.getByLabel('Hostname or IPv4 address').fill('pve.example.test');
  await page.locator('[name=username]').fill('netbox-sync@pve');
  await page.locator('[name=token_id]').fill('netbox-sync');
  const secret=randomUUID();
  await page.locator('[name=secret]').fill(secret);
  await page.getByText(language==='ru'?'Как подготовить доступ':'How to prepare access',{exact:true}).click();
  await page.getByText(language==='ru'?'Команды Proxmox CLI':'Proxmox CLI commands',{exact:true}).click();
  await page.getByRole('button',{name:language==='ru'?'Копировать':'Copy',exact:true}).first().click();
  await expect.poll(()=>page.evaluate(()=>navigator.clipboard.readText())).toBe('pveversion');
  await page.getByLabel('Language / Язык').selectOption(language==='ru'?'en':'ru');
  await page.getByLabel('Language / Язык').selectOption(language);
  await expect(page.locator('[name=username]')).toHaveValue('netbox-sync@pve');
  // Never put secret values in an assertion failure or screenshot.
  expect(await page.locator('[name=secret]').evaluate((input:HTMLInputElement,value)=>input.value===value,secret)).toBe(true);
  await page.locator('[name=secret]').fill('');
  await expect(page.locator('#source-user-hint')).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await page.screenshot({path:`test-results/access-${language}-${theme}-proxmox.png`,fullPage:true});
  await page.getByLabel('Source type').selectOption('esxi');
  await expect(page.locator('.source-access-help')).toContainText('Read-only');
  await expect(page.locator('.source-access-help')).toContainText('lockdown');
  await page.evaluate(()=>document.documentElement.style.zoom='1.5');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await page.screenshot({path:`test-results/access-${language}-${theme}-esxi.png`,fullPage:true});
 });
}
for (const [code, text] of [['SOURCE_TLS_FAILED','TLS verification failed'],['SOURCE_TIMEOUT','timed out'],['SOURCE_AUTH_FAILED','Authentication was rejected'],['SOURCE_CONNECTION_FAILED','Could not reach'],['SOURCE_DESTINATION_DENIED','blocked by policy']]) {
 test(`connection safe UI ${code}`,async({page})=>{
  await fixture(page,code);
  await page.getByLabel('Source type').selectOption('esxi');
  await page.getByLabel('Hostname or IPv4 address').fill('esxi.example.test');
  await page.locator('[name=username]').fill('netbox-sync');
  await page.locator('[name=secret]').fill(randomUUID());
  await page.getByRole('button',{name:'Test Connection'}).click();
  await expect(page.getByRole('alert')).toContainText(text);
  await expect(page.getByRole('alert')).not.toContainText('REMOTE_DETAIL');
  await expect(page.locator('[name=secret]')).toBeEmpty();
 });
}

test('Russian connection failure uses safe local explanation',async({page})=>{
 await fixture(page,'SOURCE_TLS_FAILED');
 await page.getByLabel('Language / Язык').selectOption('ru');
 await page.getByLabel('Source type').selectOption('esxi');
 await page.getByLabel('Hostname or IPv4 address').fill('esxi.example.test');
 await page.locator('[name=username]').fill('netbox-sync');
 await page.locator('[name=secret]').fill(randomUUID());
 await page.getByRole('button',{name:'Test Connection'}).click();
 await expect(page.getByRole('alert')).toContainText('Ошибка проверки TLS');
 await expect(page.getByRole('alert')).not.toContainText('REMOTE_DETAIL');
});
