import {test,expect} from './auth-fixture';
import {source,diagnostics} from '../tests/fixtures.mjs';

test('list scope, refresh feedback, modal close controls and teams settings',async({page})=>{
 const sources=Array.from({length:20},(_,i)=>source(i+1));let reads=0,fail=false;
 await page.route('**/api/v1/**',async route=>{
  const path=new URL(route.request().url()).pathname;
  if(path==='/api/v1/bootstrap')return route.fulfill({json:{revision:1,status:'READY',url:'https://netbox.test',completed:true,read_token_present:true,apply_token_present:true,checks:[],validated_at:1}});
  if(path==='/api/v1/sources'){reads++;await new Promise(r=>setTimeout(r,150));return route.fulfill(fail?{status:503,json:{}}:{json:{sources}});}
  if(path==='/api/v1/diagnostics')return route.fulfill({json:diagnostics(sources)});
  if(path==='/api/v1/teams')return route.fulfill({json:{version:1,revision:0,teams:{},assignments:{}}});
  return route.fulfill({status:404,json:{}});
 });
 await page.goto('/sources?provider=proxmox&site=obsolete&schedule=off&team=missing&attention=yes');
 await expect(page.getByRole('link',{name:'Source 001',exact:true})).toBeVisible();
 await expect(page.getByRole('link',{name:'Source 002',exact:true})).toHaveCount(0);
 await expect(page.getByText('Registration lifecycle',{exact:true})).toHaveCount(0);
 await expect(page.getByText('More filters',{exact:false})).toHaveCount(0);
 await expect(page.getByRole('button',{name:'Clear filters'})).toHaveCount(0);
 await expect(page.getByRole('button',{name:'Manage teams'})).toHaveCount(0);
 const before=reads;
 await page.getByRole('button',{name:'Refresh',exact:true}).click();
 await expect(page.getByRole('button',{name:'Refreshing…'})).toBeVisible();
 await expect(page.locator('.refresh-control')).toContainText('Updated:');
 expect(reads).toBeGreaterThan(before);
 await page.getByRole('checkbox',{name:'Select this page',exact:true}).check();
 const open=()=>page.getByRole('button',{name:'Set schedule',exact:true}).click();
 await open();const dialog=page.getByRole('dialog');
 await expect(dialog.getByRole('option',{name:'Weekly',exact:true})).toHaveCount(1);
 await dialog.getByRole('heading').click();await expect(dialog).toBeVisible();
 await dialog.evaluate(el=>el.scrollTop=el.scrollHeight);
 await expect(dialog.getByRole('button',{name:'Close',exact:true})).toBeInViewport();
 await dialog.getByRole('button',{name:'Close',exact:true}).click();await expect(dialog).toHaveCount(0);
 await open();await page.mouse.click(5,5);await expect(dialog).toHaveCount(0);
 await open();await page.keyboard.press('Escape');await expect(dialog).toHaveCount(0);
 fail=true;await page.getByRole('button',{name:'Refresh',exact:true}).click();
 await expect(page.locator('.refresh-control')).toContainText('Refresh failed');
 await page.goto('/settings?section=teams');
 await expect(page.getByRole('heading',{name:'Settings — Teams'})).toBeVisible();
 await page.getByText('Manage teams',{exact:true}).click();
 await expect(page.getByRole('button',{name:'Create team'})).toBeVisible();
});

test('pfSense refresh updates statuses and shows Moscow time in another timezone',async({browser})=>{
 const context=await browser.newContext({timezoneId:'America/Los_Angeles'}),page=await context.newPage();let statusReads=0;
 await page.route('**/api/v1/**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path==='/api/v1/bootstrap')return route.fulfill({json:{revision:1,status:'READY',url:'https://netbox.test',completed:true,read_token_present:true,apply_token_present:true,checks:[],validated_at:1}});
  if(path==='/api/v1/pfsense')return route.fulfill({json:{count:1,items:[{id:1,name:'pfSense',cluster:'Test',site:'Test',address:'10.0.0.1',url:'https://netbox.test/1'}]}});
  if(path==='/api/v1/pfsense/1/status'){statusReads++;return route.fulfill({json:{status:'CONNECTED',collected_at:'2026-10-07T23:52:11Z'}});}
  return route.fulfill({status:404,json:{}});
 });
 await page.goto('/sources/pfsense');await expect(page.getByText(/Last collection:.*02:52:11 МСК/)).toBeVisible();
 const before=statusReads;await page.getByRole('button',{name:'Refresh',exact:true}).click();
 await expect(page.locator('.refresh-control')).toContainText('Updated:');await expect.poll(()=>statusReads).toBeGreaterThan(before);
 await page.screenshot({path:'test-results/pfsense-oct8.png',fullPage:true});
 await page.setViewportSize({width:390,height:844});
 await expect(page.getByRole('searchbox')).toBeInViewport();
 await page.screenshot({path:'test-results/pfsense-oct8-mobile.png',fullPage:true});
 await context.close();
});
