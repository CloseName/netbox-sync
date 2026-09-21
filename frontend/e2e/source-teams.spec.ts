import {test,expect} from './auth-fixture';
import {source,diagnostics} from '../tests/fixtures.mjs';
import {setLanguage} from './menu-helper';
for(const language of ['en','ru'])test(`source team create assign filter conflict ${language}`,async({page})=>{
 await page.setViewportSize({width:390,height:900});
 const a=source(),b={...source(),source_instance:'source-2',name:'Other source'};
 let data:any={version:1,revision:0,teams:{},assignments:{}},conflict=false;
 await page.route('**/api/v1/**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path==='/api/v1/bootstrap')return route.fulfill({json:{revision:1,status:'READY',url:'https://netbox.test',completed:true,read_token_present:true,apply_token_present:true,safe_code:null,checks:[],validated_at:1}});
  if(path==='/api/v1/teams'){
   if(route.request().method()==='POST'){
    if(conflict)return route.fulfill({status:409,json:{error:'TEAM_CONFLICT'}});
    const p=route.request().postDataJSON();expect(p.revision).toBe(data.revision);
    if(p.operation==='create')data.teams['team-1']={id:'team-1',name:p.name};
    if(p.operation==='assign')data.assignments[p.source_instance]=p.team_id;
    data.revision++;
   }return route.fulfill({json:data});
  }
  if(path==='/api/v1/sources')return route.fulfill({json:{sources:[a,b]}});
  if(path==='/api/v1/sources/source-1')return route.fulfill({json:a});
  if(path==='/api/v1/diagnostics')return route.fulfill({json:diagnostics([a,b])});
  if(path.endsWith('/runs'))return route.fulfill({json:{runs:[],next_cursor:null}});
  return route.fulfill({status:404,json:{}});
 });
 await page.goto('/sources');if(language==='ru')await setLanguage(page,'ru');
 await expect(page.getByRole('combobox',{name:language==='ru'?'Команда':'Team',exact:true})).toHaveCount(0);
 await page.getByRole('button',{name:language==='ru'?'Управление командами':'Manage teams',exact:true}).click();
 await page.getByRole('dialog').getByText(language==='ru'?'Управление командами':'Manage teams',{exact:true}).click();
 await page.getByLabel(language==='ru'?'Название команды':'Team name',{exact:true}).fill('Compute QA');
 await page.getByRole('button',{name:language==='ru'?'Создать команду':'Create team',exact:true}).click();
 await expect(page.getByLabel(language==='ru'?'Команда для переименования':'Team to rename')).toContainText('Compute QA');
 await page.goto('/sources/source-1/configuration');
 await page.getByLabel(language==='ru'?'Назначенная команда':'Assigned team').selectOption('team-1');
 await expect(page.getByLabel(language==='ru'?'Назначенная команда':'Assigned team')).toHaveValue('team-1');
 await page.reload();await expect(page.getByLabel(language==='ru'?'Назначенная команда':'Assigned team')).toHaveValue('team-1');
 conflict=true;await page.getByLabel(language==='ru'?'Назначенная команда':'Assigned team').selectOption('');
 await expect(page.getByText(language==='ru'?'Изменение не подтверждено или команды изменены другим администратором. Обновите перед повтором.':'Change not confirmed or another administrator changed teams. Reload before retrying.')).toBeVisible();
 await expect(page.getByLabel(language==='ru'?'Назначенная команда':'Assigned team')).toBeDisabled();
 await page.goto('/sources?team=team-1');await expect(page.getByRole('link',{name:a.name,exact:true})).toBeVisible();await expect(page.getByRole('link',{name:b.name,exact:true})).toHaveCount(0);
 await page.getByRole('combobox',{name:language==='ru'?'Команда':'Team',exact:true}).selectOption('none');await expect(page.getByRole('link',{name:b.name,exact:true})).toBeVisible();await expect(page.getByRole('link',{name:a.name,exact:true})).toHaveCount(0);
 await page.screenshot({path:`test-results/source-teams-${language}.png`,fullPage:true});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
});
