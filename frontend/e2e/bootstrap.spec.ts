import {test,expect} from '@playwright/test';
for(const width of [1440,1024,768])test(`first-run recovery and completion at ${width}`,async({page,context},info)=>{
 let state:any={revision:0,status:'FRESH',url:'',completed:false,read_token_present:false,apply_token_present:false,safe_code:null,checks:[],validated_at:null};let fail=true;
 await context.route('**/api/v1/**',async route=>{const path=new URL(route.request().url()).pathname;
  if(path.startsWith('/api/v1/bootstrap')){
   const body=route.request().method()==='POST'?route.request().postDataJSON():null;
   if(body){expect(body.revision).toBe(state.revision);
    if(path.endsWith('/configuration'))state={...state,revision:state.revision+1,url:body.url,status:'CONFIGURED',read_token_present:true,apply_token_present:true,safe_code:null};
    if(path.endsWith('/validate'))state={...state,status:fail?'ATTENTION':'VALIDATED',safe_code:fail?'AUTH_FAILED':null};
    if(path.endsWith('/finish'))state={...state,status:'READY',completed:true};
   }return route.fulfill({json:state});
  }
  if(path==='/api/v1/sources')return route.fulfill({json:{sources:[]}});
  if(path.startsWith('/api/v1/runs'))return route.fulfill({json:{runs:[],next_cursor:null}});
  return route.fulfill({status:503,json:{}});
 });
 await page.setViewportSize({width,height:900});await page.goto('/sources');
 await expect(page.getByRole('heading',{name:'Welcome to NetBox Sync'})).toBeVisible();
 await page.getByLabel('NetBox HTTPS URL').fill('https://netbox.example.test');
 await page.getByLabel('Read-only token',{exact:true}).fill('FAKE-READ-TOKEN');await page.getByLabel('Apply token',{exact:true}).fill('FAKE-APPLY-TOKEN');
 await page.getByRole('button',{name:'Save connection',exact:true}).click();
 await expect(page.getByLabel('Read-only token',{exact:true})).toHaveValue('');
 await page.reload();await expect(page.getByText('Setup: configured')).toBeVisible();
 const other=await context.newPage();await other.goto('/runs');await expect(other.getByText('Setup: configured')).toBeVisible();await other.close();
 await page.getByRole('button',{name:'Test connection and prerequisites'}).click();await expect(page.getByText('NetBox rejected a token.')).toBeVisible();
 await page.getByLabel('Read-only token',{exact:true}).fill('FAKE-CORRECTED-READ-TOKEN');
 await page.getByLabel('Apply token',{exact:true}).fill('FAKE-CORRECTED-APPLY-TOKEN');
 await page.getByLabel('Deliberately replace existing stored credentials').check();
 await page.getByRole('button',{name:'Save connection',exact:true}).click();
 await expect(page.getByText('Setup: configured')).toBeVisible();
 fail=false;await page.getByRole('button',{name:'Test connection and prerequisites'}).click();
 await expect(page.getByRole('heading',{name:'Review and finish'})).toBeVisible();
 await page.screenshot({path:info.outputPath('bootstrap-review.png'),fullPage:true});
 expect(await page.evaluate(()=>JSON.stringify(localStorage)+JSON.stringify(sessionStorage))).not.toContain('FAKE-');
 await page.getByRole('button',{name:'Finish setup'}).click();await expect(page.getByRole('heading',{name:'Welcome to NetBox Sync'})).toHaveCount(0);
 await page.goto('/sources');await expect(page.getByRole('heading',{name:'Welcome to NetBox Sync'})).toHaveCount(0);
});
