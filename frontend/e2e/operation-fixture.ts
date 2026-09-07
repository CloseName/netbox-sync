// Adapt the existing deterministic provider fixtures to the durable operation API.
// Provider completion updates shared mock state after the start response is returned.
import { test as base, expect } from '@playwright/test';
import { randomUUID } from 'node:crypto';
export { expect };
export * from '@playwright/test';
const installed = new WeakSet();
export function installOperationFixtures(page: any) {
    if (installed.has(page)) return; installed.add(page);
    const entries: {url:any;handler:any}[] = [];
    const matches = (pattern: any, url: string) => pattern instanceof RegExp ? pattern.test(url) : new RegExp('^'+pattern.replace(/[.+?^${}()|[\]\\]/g,'\\$&').replace(/\*\*/g,'@@').replace(/\*/g,'[^/]*').replace(/@@/g,'.*')+'$').test(url);
    const slots = new Map<string, any>();
    const register = page.route.bind(page);
    page.route = ((url: any, handler: any, options: any) => {
      const index=entries.push({url,handler})-1;
      return register(url, async (route: any) => {
      const path = new URL(route.request().url()).pathname;
      const source = path.split('/')[4];
      if (route.request().method() === 'GET' && path.endsWith('/operations'))
        return route.fulfill({json:{operations:[...slots.values()].filter(row=>row.source_instance===source)}});
      if (route.request().method() === 'GET' && path.endsWith('/lifecycle'))
        return route.fulfill({json:{source_instance:source,display_name:source,removed_at:null,credential_state:null,revision:'a'.repeat(64)}});
      if (route.request().method() !== 'POST' || !/\/operations\/(plan|discovery)$/.test(path)) return handler(route);
      const kind = path.endsWith('/plan') ? 'PLAN' : 'DISCOVERY';
      const key = source+':'+kind;
      const prior = slots.get(key);
      if (prior?.status === 'RUNNING') return route.fulfill({json:prior,status:202});
      const now = new Date().toISOString();
      const row = {operation_id:randomUUID(),source_instance:source,operation_kind:kind,status:'RUNNING',started_at:now,updated_at:now,finished_at:null,result:null,safe_error_code:null};
      slots.set(key,row);
      await route.fulfill({json:row,status:202});
      const finish = (result: any, code: string | null = null) => {
        if (slots.get(key)?.operation_id !== row.operation_id) return;
        slots.set(key,{...row,status:code?'FAILED':kind==='PLAN'?'READY':'SUCCEEDED',result:code?null:result,safe_error_code:code,finished_at:new Date().toISOString(),updated_at:new Date().toISOString()});
      };
      let fallbackIndex = index;
      const proxy = new Proxy(route, {get(target, prop) {
        if (prop === 'fulfill') return async (payload: any) => {
          let value=payload.json;
          if (value===undefined && payload.body) {try{value=JSON.parse(payload.body);}catch{value=null;}}
          finish(value, payload.status >= 400 ? value?.error?.code ?? 'OPERATION_FAILED' : null);
        };
        if (prop === 'fallback') return async () => {
          while (--fallbackIndex >= 0) { const entry=entries[fallbackIndex]; if(matches(entry.url,route.request().url())) return entry.handler(proxy); }
          finish(null,'OPERATION_FAILED');
        };
        if (prop === 'abort') return async () => finish(null,'OPERATION_FAILED');
        const member=target[prop];return typeof member==='function'?member.bind(target):member;
      }});
      try {await handler(proxy);} catch {finish(null,'OPERATION_FAILED');}
    }, options); }) as typeof page.route;
}
export const test = base.extend({page: async ({page},use)=>{installOperationFixtures(page);await use(page);}});
