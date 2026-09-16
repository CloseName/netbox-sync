import {test,expect} from '@playwright/test';
const read=['source.read','run.read','diagnostics.read'];
const operate=[...read,'source.plan','source.apply'];
const admin=[...operate,'identity.manage','bootstrap.manage','policy.read','policy.write','source.register','source.configure','source.schedule','source.remove'];
const config={enabled:false,host:'directory.example.test',port:636,bind_dn:'cn=reader,dc=example,dc=test',user_base:'ou=people,dc=example,dc=test',group_base:'ou=groups,dc=example,dc=test',user_attribute:'sAMAccountName',user_object_class:'user',group_object_class:'group',member_attribute:'member',identity_attribute:'objectGUID',account_control_attribute:'userAccountControl',ca_pem:'',mappings:[{dn:'cn=operators,ou=groups,dc=example,dc=test',role:'operator'}]};
for(const lang of ['en','ru'])for(const theme of ['light','dark'] as const)for(const width of [1440,390])
test(`LDAP settings test save and roles ${lang} ${theme} ${width}`,async({page})=>{
 await page.setViewportSize({width,height:900});await page.emulateMedia({colorScheme:theme});
 let saved=structuredClone(config),revision=1,tests=0,writes=0;
 await page.route('**/api/v1/**',async route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/auth/me'))return route.fulfill({json:{principal_id:'admin',username:'admin',role:'admin',provider:'local',permissions:admin}});
  if(path.endsWith('/bootstrap'))return route.fulfill({json:{revision:1,status:'READY',completed:true,url:'https://netbox.example.test',read_token_present:true,apply_token_present:true,safe_code:null,checks:[],validated_at:1}});
  if(path.endsWith('/settings/ldap/test')){tests++;return route.fulfill({json:{ok:true,expires_in:300}});}
  if(path.endsWith('/settings/ldap')){
   if(route.request().method()==='POST'){writes++;const body=route.request().postDataJSON();expect(body.expected_revision).toBe(revision);expect(body.bind_password).toBe('');saved=body.config;revision++;}
   return route.fulfill({json:{revision,config:saved,bind_secret_present:true,roles:{viewer:read,operator:operate,admin}}});
  }
  return route.fulfill({status:503,json:{error:{code:'UNAVAILABLE'}}});
 });
 await page.goto('/settings');await page.getByLabel('Language / Язык').selectOption(lang);
 const t=(en:string,ru:string)=>lang==='ru'?ru:en;
 const password=page.getByLabel(t('Bind account password','Пароль служебной записи'),{exact:true});
 await expect(password).toHaveValue('');
 await page.getByLabel(t('Enable corporate sign-in','Включить корпоративный вход')).check();
 const save=page.getByRole('button',{name:t('Save settings','Сохранить настройки'),exact:true});
 await expect(save).toBeDisabled();
 await page.getByRole('button',{name:t('Check configuration','Проверить конфигурацию'),exact:true}).click();
 await expect(save).toBeEnabled();await save.click();
 await expect(page.getByRole('status')).toContainText(t('Saved.','Сохранено.'));
 await expect(password).toHaveValue('');expect(tests).toBe(1);expect(writes).toBe(1);
 await page.screenshot({path:`test-results/ldap-saved-${lang}-${theme}-${width}.png`,fullPage:true});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.getByRole('button',{name:t('Access / Roles','Доступ / Роли'),exact:true}).click();
 await expect(page.getByRole('heading',{name:t('Built-in roles','Встроенные роли')})).toBeVisible();
 await expect(page.locator('article')).toHaveCount(3);
 await page.screenshot({path:`test-results/ldap-roles-${lang}-${theme}-${width}.png`,fullPage:true});
});
for(const role of ['viewer','operator'])test(`restricted navigation ${role}`,async({page})=>{
 let privilegedReads=0;
 await page.route('**/api/v1/**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path.endsWith('/auth/me'))return route.fulfill({json:{principal_id:'person',username:'person',role,provider:'ldap',permissions:role==='viewer'?read:operate}});
  if(path.includes('/settings/')||path.endsWith('/bootstrap'))privilegedReads++;
  if(path.endsWith('/sources'))return route.fulfill({json:[]});
  return route.fulfill({status:503,json:{error:{code:'UNAVAILABLE'}}});
 });
 await page.goto('/settings');await page.getByLabel('Language / Язык').selectOption('en');
 await expect(page.getByText('You do not have permission to open this section.')).toBeVisible();
 await expect(page.getByRole('link',{name:'Settings',exact:true})).toHaveCount(0);
 await page.goto('/sources/add');await expect(page.getByText('You do not have permission to open this section.')).toBeVisible();
 expect(privilegedReads).toBe(0);
});
