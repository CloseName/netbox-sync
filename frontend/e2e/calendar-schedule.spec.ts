import {test,expect} from '@playwright/test';
import {source,diagnostics} from '../tests/fixtures.mjs';

test('Moscow calendar saves explicitly and survives reload',async({page})=>{
 let schedule:any={source_instance:'source-1',sync_enabled:true,sync_interval_seconds:600,sync_calendar:null,
   scheduler_state:'WAITING',last_scheduled_run_at:null,next_expected_at:null,server_time:new Date().toISOString()};
 const writes:any[]=[];
 await page.route('**/api/v1/**',route=>{
   const path=new URL(route.request().url()).pathname;
   if(path.endsWith('/auth/me'))return route.fulfill({json:{principal_id:'fixture',role:'admin',username:'admin',permissions:['source.read','source.schedule','run.read','diagnostics.read']}});
   if(path.endsWith('/bootstrap'))return route.fulfill({json:{status:'READY',completed:true,revision:1,checks:[],read_token_present:true,apply_token_present:true}});
   if(path.endsWith('/schedule')){
     if(route.request().method()==='PATCH'){
       const body=route.request().postDataJSON();writes.push(body);
       schedule={...schedule,sync_calendar:body.sync_calendar,next_expected_at:'2026-10-07T15:00:00Z'};
     }
     return route.fulfill({json:schedule});
   }
   if(path.endsWith('/diagnostics'))return route.fulfill({json:diagnostics([source()])});
   if(path.endsWith('/runs'))return route.fulfill({json:{runs:[],next_cursor:null}});
   if(path==='/api/v1/sources/source-1')return route.fulfill({json:source()});
   if(path==='/api/v1/sources')return route.fulfill({json:{sources:[source()]}});
   return route.fulfill({json:{}});
 });
 await page.goto('/sources/source-1/schedule');
 await page.getByRole('button',{name:'Edit schedule',exact:true}).click();
 await page.getByLabel('Schedule mode').selectOption('monthly');
 await page.getByLabel('Day of month').fill('32');
 await expect(page.getByRole('button',{name:'Save schedule',exact:true})).toBeDisabled();
 await page.getByLabel('Schedule mode').selectOption('daily');
 await page.getByLabel('Moscow time (MSK)').fill('18:00');
 await page.screenshot({path:test.info().outputPath('calendar-edit.png'),fullPage:true});
 await page.getByRole('button',{name:'Save schedule',exact:true}).click();
 await expect(page.getByText('Daily  · 18:00 MSK')).toBeVisible();
 expect(writes[0].sync_calendar).toEqual({mode:'daily',time:'18:00',timezone:'Europe/Moscow'});
 expect(writes[0].expected_sync_calendar).toBeNull();
 await page.reload();
 await expect(page.getByText('Daily  · 18:00 MSK')).toBeVisible();
 await expect(page.locator('time[datetime="2026-10-07T15:00:00Z"]')).toContainText('18:00');
 await page.screenshot({path:test.info().outputPath('calendar-saved.png'),fullPage:true});
});
