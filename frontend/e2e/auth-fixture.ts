// Explicit identity only for pre-existing authenticated-screen fixtures.
import {test as base} from '@playwright/test';
export * from '@playwright/test';
const marked=new WeakSet<object>();
export function installAuthFixture(surface:any){
 if(marked.has(surface))return;marked.add(surface);
 const register=surface.route.bind(surface);
 surface.route=(url:any,handler:any,options:any)=>register(url,(route:any)=>
  new URL(route.request().url()).pathname==='/api/v1/auth/me'
   ?route.fulfill({json:{principal_id:'test-admin',username:'admin',permissions:['source.read','policy.read','policy.write']}})
   :handler(route),options);
 void surface.route('**/api/v1/auth/me',(route:any)=>route.fulfill({json:{principal_id:'test-admin',username:'admin',permissions:['source.read','policy.read','policy.write']}}));
}
export const test=base.extend({
 context:async({context},use)=>{installAuthFixture(context);await use(context);},
 page:async({page},use)=>{installAuthFixture(page);await use(page);},
 browser:async({browser},use)=>{
  const original=browser.newContext.bind(browser);
  browser.newContext=async(options)=>{const context=await original(options);installAuthFixture(context);context.on('page',installAuthFixture);return context;};
  await use(browser);browser.newContext=original;
 },
});
