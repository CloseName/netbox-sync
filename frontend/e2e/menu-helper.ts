import {expect,type Page} from '@playwright/test';
export async function openUserMenu(page:Page){
 const toggle=page.getByRole('button',{name:/User menu|Меню пользователя/});
 await expect(toggle).toBeVisible();
 if(await toggle.getAttribute('aria-expanded')!=='true')await toggle.click();
}
export async function setLanguage(page:Page,value:string){
 await openUserMenu(page);await page.getByLabel('Language / Язык').selectOption(value);
 await page.keyboard.press('Escape');
}
