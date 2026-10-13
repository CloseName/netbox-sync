import {test,expect} from './auth-fixture';
import {source,diagnostics} from '../tests/fixtures.mjs';

test('sidebar stays attached through page scroll and provider assets load locally',async({page})=>{
 const sources=Array.from({length:25},(_,i)=>source(i+1));
 await page.route('**/api/v1/**',r=>{const p=new URL(r.request().url()).pathname;
  if(p.endsWith('/bootstrap'))return r.fulfill({json:{revision:1,status:'READY',completed:true,url:'https://netbox.test',read_token_present:true,apply_token_present:true,checks:[]}});
  if(p==='/api/v1/sources')return r.fulfill({json:{sources}});
  if(p==='/api/v1/diagnostics')return r.fulfill({json:diagnostics(sources)});
  return r.fulfill({json:{items:[],count:0}});
 });
 await page.setViewportSize({width:1440,height:800});
 await page.goto('/sources');
 await expect(page.locator('.source-list-table tbody tr')).toHaveCount(25);
 await expect(page.getByRole('button',{name:'Set schedule',exact:true})).not.toBeVisible();
 for(const height of [800,600]){
  await page.setViewportSize({width:1440,height});
  for(const fraction of [0,.5,1]){
   await page.evaluate(f=>window.scrollTo(0,(document.documentElement.scrollHeight-innerHeight)*f),fraction);
   await expect.poll(()=>page.locator('.sidebar').evaluate(e=>Math.abs(e.getBoundingClientRect().bottom-innerHeight))).toBeLessThan(2);
   const header=await page.locator('.app-header').boundingBox(),sidebar=await page.locator('.sidebar').boundingBox();
   expect(Math.abs(sidebar!.y-(header!.y+header!.height))).toBeLessThan(2);
  }
 }
 const toggle=page.getByRole('button',{name:'Sources',exact:true});
 if(await toggle.getAttribute('aria-expanded')==='false')await toggle.click();
 await expect(page.locator('.sidebar img.provider-icon')).toHaveCount(4);
 for(const img of await page.locator('.sidebar img.provider-icon').all())expect(await img.evaluate((e:HTMLImageElement)=>e.complete&&e.naturalWidth>0&&e.src.includes('/assets/providers/'))).toBe(true);
 await page.screenshot({path:'test-results/ux-sources-bottom.png'});
});

test('user role is explicit and failed refresh prevents stale edits',async({page})=>{
 let writes=0,fail=false;
 await page.route('**/api/v1/**',r=>{const p=new URL(r.request().url()).pathname;
  if(p.endsWith('/bootstrap'))return r.fulfill({json:{revision:1,status:'READY',completed:true,url:'https://netbox.test',read_token_present:true,apply_token_present:true,checks:[]}});
  if(p.endsWith('/users/role')){writes++;expect(r.request().postDataJSON()).toEqual({id:'11111111-1111-4111-8111-111111111111',role:'operator',revision:7});fail=true;return r.fulfill({json:{}});}
  if(p.endsWith('/users'))return r.fulfill({status:fail?503:200,json:fail?{}:{users:[{id:'11111111-1111-4111-8111-111111111111',username:'person',display_name:'Test person',role:'viewer',active:true,access_state:'allowed'}],total:1,offset:0,revision:7,enabled:true,sync_interval_seconds:600,sync:{}}});
  return r.fulfill({json:{sources:[],items:[]}});
 });
 await page.goto('/users');await page.reload();
 await page.getByRole('button',{name:'Change role',exact:true}).click();
 await page.getByLabel('Role for person').selectOption('operator');expect(writes).toBe(0);
 await page.getByRole('button',{name:'Save role',exact:true}).click();
 await expect(page.getByRole('alert')).toContainText('Users could not be loaded');
 await expect(page.getByRole('button',{name:'Change role',exact:true})).toBeDisabled();
 expect(writes).toBe(1);
});
