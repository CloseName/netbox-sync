import {test, expect} from './auth-fixture';
import {source, diagnostics, run} from '../tests/fixtures.mjs';
test.use({timezoneId:'America/Los_Angeles'});

for (const theme of ['dark','light'] as const) for (const width of [1366,1920,2560,390]) {
  test(`quiet workspace navigation and account evidence ${theme} ${width}`, async ({page})=>{
    await page.setViewportSize({width,height:1080});
    await page.emulateMedia({colorScheme:theme});
    const sources = [source(1),source(2)];
    await page.route('**/api/v1/**', route=>{
      const path=new URL(route.request().url()).pathname;
      if(path==='/api/v1/bootstrap')return route.fulfill({json:{revision:1,status:'READY',completed:true,url:'https://netbox.test',read_token_present:true,apply_token_present:true,checks:[]}});
      if(path==='/api/v1/sources')return route.fulfill({json:{sources}});
      if(path==='/api/v1/diagnostics')return route.fulfill({json:diagnostics(sources)});
      if(path==='/api/v1/runs')return route.fulfill({json:{runs:[run()],next_cursor:null}});
      if(path==='/api/v1/pfsense')return route.fulfill({json:{items:[],count:0}});
      if(path==='/api/v1/selectel')return route.fulfill({json:{import_ready:true,items:[
        {account:'29916',name:'Infrastructure',status:'completed',username:'reader',url:'https://netbox.test/providers/29916',finished_at:1791748800,summary:{projects:2,servers:0,matched:0,unmatched:0,products:[{product:'dns',title:'DNS',state_label:'Данные получены',observations_by_collection:{zones:0}},{product:'swift',title:'Swift',state_label:'Недоступно',observations_by_collection:{}}]}},
        {account:'29917',name:'Development',status:'attention',username:'reader',url:'https://netbox.test/providers/29917',error:'HTTP_403'},
      ]}});
      return route.fulfill({status:404,json:{}});
    });
    await page.goto('/');
    await expect(page.getByRole('heading',{name:'Overview',exact:true})).toBeVisible();
    await expect(page.locator('.overview-providers a')).toHaveCount(4);
    await page.screenshot({path:`test-results/workspace-overview-${theme}-${width}.png`,fullPage:true});
    if(width<801) await page.getByRole('button',{name:'Navigation',exact:true}).click();
    const nav=page.getByRole('navigation',{name:'Main navigation'});
    const sourcesToggle=nav.getByRole('button',{name:'Sources',exact:true});
    await expect(sourcesToggle).toHaveAttribute('aria-expanded','false');
    await sourcesToggle.click();
    await expect(sourcesToggle).toHaveAttribute('aria-expanded','true');
    await nav.getByRole('link',{name:'Selectel',exact:true}).click();
    await expect(page.getByRole('heading',{name:'Selectel',exact:true})).toBeVisible();
    await expect(page.getByText('Недостаточно прав чтения Selectel.',{exact:true})).toBeVisible();
    await expect(page.locator('.selectel-table time')).toContainText('23:00:00 МСК');
    await page.getByRole('button',{name:'Infrastructure',exact:true}).click();
    await expect(page.locator('#selectel-account-detail').getByRole('row').filter({hasText:'DNS'}).getByRole('cell').last()).toHaveText('0');
    await expect(page.locator('#selectel-account-detail').getByRole('row').filter({hasText:'Swift'}).getByRole('cell').last()).toHaveText('—');
    await page.screenshot({path:`test-results/workspace-selectel-${theme}-${width}.png`,fullPage:true});
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    if(width<801) await page.getByRole('button',{name:'Navigation',exact:true}).click();
    await sourcesToggle.click();
    await expect(nav.getByRole('link',{name:'Selectel',exact:true})).toHaveCount(0);
    await expect(nav.getByRole('link',{name:'Settings',exact:true})).toBeVisible();
    await expect(nav.getByRole('button',{name:'Settings',exact:true})).toHaveCount(0);
    await page.getByRole('button',{name:'User menu',exact:true}).click();
    await expect(page.locator('#user-options')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.locator('#user-options')).toHaveCount(0);
    await expect(page.getByRole('button',{name:'User menu',exact:true})).toBeFocused();
    await page.goto('/#diagnostics');
    await expect(page).toHaveURL(/\/diagnostics$/);
    if(width<801) await page.getByRole('button',{name:'Navigation',exact:true}).click();
    await expect(nav.getByRole('link',{name:'Problems',exact:true})).toHaveAttribute('aria-current','page');
    if(width>=801)for(const path of ['/', '/sources', '/sources/pfsense', '/sources/selectel', '/runs', '/diagnostics', '/settings', '/users']){
      await page.goto(path);
      await expect(page.locator('.app-content > main')).toBeVisible();
      const edges=await page.locator('.app-content').evaluate(e=>{
        const r=e.getBoundingClientRect(),style=getComputedStyle(e),main=e.querySelector('main')!.getBoundingClientRect();
        return {left:main.left-r.left-parseFloat(style.paddingLeft),right:r.right-main.right-parseFloat(style.paddingRight)};
      });
      expect(Math.abs(edges.left),path+' left inset').toBeLessThan(2);
      expect(Math.abs(edges.right),path+' unused right strip').toBeLessThan(2);
      expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    }

  });
}
