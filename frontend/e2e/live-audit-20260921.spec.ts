import {test,expect} from './auth-fixture';
import {source,diagnostics} from '../tests/fixtures.mjs';
for(const lang of ['en','ru'])for(const theme of ['light','dark'])test(`directory users ${lang} ${theme}`,async({page},info)=>{
 await page.setViewportSize({width:theme==='dark'?390:1440,height:900});
 await page.addInitScript(({lang,theme})=>{localStorage.setItem('netbox-sync.language',lang);localStorage.setItem('netbox-sync.theme',theme);},{lang,theme});
 let revision=1,error=false;const users=Array.from({length:61},(_,i)=>({id:String(i),username:`user-${String(i).padStart(3,'0')}`,display_name:`Directory person ${i}`,role:'viewer',active:true,access_state:'allowed'}));
 await page.route('**/api/v1/**',async route=>{const url=new URL(route.request().url()),path=url.pathname;
 if(path==='/api/v1/bootstrap')return route.fulfill({json:{revision:1,status:'READY',url:'https://netbox.test',completed:true,read_token_present:true,apply_token_present:true,safe_code:null,checks:[],validated_at:1}});
 if(path==='/api/v1/users/role'){const body=route.request().postDataJSON();expect(body.revision).toBe(revision);users.find(u=>u.id===body.id)!.role=body.role;revision++;return route.fulfill({json:{updated:true}});}
 if(path==='/api/v1/users/sync'){error=true;return route.fulfill({status:503,json:{error:{code:'LDAP_UNAVAILABLE'}}});}
 if(path==='/api/v1/users'){const filtered=users.filter(u=>u.username.includes(url.searchParams.get('q')||'')),offset=Number(url.searchParams.get('offset')||0);return route.fulfill({json:{users:filtered.slice(offset,offset+10),total:filtered.length,offset,revision,enabled:true,sync_interval_seconds:300,sync:{success_at:1789990000,error:error?'LDAP_UNAVAILABLE':null}}});}
 return route.fulfill({json:{}});});
 await page.goto('/users');await expect(page.getByRole('heading',{name:'Directory person 0',exact:true})).toBeVisible();
 await page.getByRole('combobox').first().selectOption('operator');await expect(page.getByRole('combobox').first()).toHaveValue('operator');
 await page.screenshot({path:info.outputPath('users.png'),fullPage:true});
 await page.getByRole('searchbox').fill('user-059');await expect(page.getByRole('heading',{name:'Directory person 59'})).toBeVisible();await expect(page.getByRole('combobox')).toHaveCount(1);
 await page.getByRole('searchbox').fill('absent');await expect(page.getByRole('combobox')).toHaveCount(0);
 await page.getByRole('searchbox').fill('');await expect(page.getByRole('combobox')).toHaveCount(10);
 await page.getByRole('button',{name:lang==='ru'?'Синхронизировать пользователей':'Synchronize users'}).click();await expect(page.getByRole('alert').first()).toBeVisible();await expect(page.getByRole('combobox').first()).toHaveValue('operator');
 await page.keyboard.press('Tab');await expect(page.locator(':focus')).toBeVisible();
 await page.screenshot({path:info.outputPath('users-outage.png'),fullPage:true});
});
for(const lang of ['en','ru'])test(`blocked source discovery and unknown outcome ${lang}`,async({page},info)=>{
 await page.setViewportSize({width:lang==='ru'?390:1440,height:900});await page.addInitScript(lang=>localStorage.setItem('netbox-sync.language',lang),lang);
 const s=source(),diag=diagnostics([s]);Object.assign(diag.sources[0],{latest_run:null,latest_success_at:null,status:'DEGRADED',plan_blocked:true,plan_checked_at:new Date().toISOString(),operation_evidence_available:true});
 let uncertain=false,futurePlan=false,discoveryRequests=0;
 const item={object_kind:'vm',name:'Service - pfSense',external_id:'technical-id',classification:'WOULD_CREATE',reason_code:'NO_IDENTITY_MATCH',reason:'No existing object has this stable source identity.',future_action:'create',matched_object_id:null,matched_object_name:null,properties:{vcpus:4,memory_bytes:8*1024**3,addresses:['192.0.2.7/24'],disks:[{name:'disk0',size_bytes:20*1024**3}],interfaces:[{name:'eth0',addresses:['192.0.2.7/24'],mac_address:'02:00:00:00:00:01'}]}};
 await page.route('**/api/v1/**',route=>{const path=new URL(route.request().url()).pathname;
 if(path==='/api/v1/bootstrap')return route.fulfill({json:{revision:1,status:'READY',url:'https://netbox.test',completed:true,read_token_present:true,apply_token_present:true,safe_code:null,checks:[],validated_at:1}});
 if(path.endsWith('/operations/discovery')){discoveryRequests++;return route.fulfill({status:202,json:{operation_id:'33333333-3333-4333-8333-333333333333',source_instance:s.source_instance,operation_kind:'DISCOVERY',status:'RUNNING',started_at:new Date().toISOString(),updated_at:new Date().toISOString(),finished_at:null,safe_error_code:null,result:null}});}
 if(path.endsWith('/lifecycle'))return route.fulfill({json:{source_instance:s.source_instance,display_name:s.name,removed_at:null,credential_state:null,revision:'a'.repeat(64),removal_blocker:uncertain?'SOURCE_APPLY_UNCONFIRMED':null}});
 if(path.endsWith('/operations'))return route.fulfill({json:{operations:[...(futurePlan?[{operation_id:'22222222-2222-4222-8222-222222222222',source_instance:s.source_instance,operation_kind:'PLAN',status:'RUNNING',started_at:new Date(Date.now()+5000).toISOString(),updated_at:new Date().toISOString(),finished_at:null,safe_error_code:null,result:null}]:[]),{operation_id:'11111111-1111-4111-8111-111111111111',source_instance:s.source_instance,operation_kind:'DISCOVERY',status:'SUCCEEDED',started_at:new Date().toISOString(),updated_at:new Date().toISOString(),finished_at:new Date().toISOString(),safe_error_code:null,result:{source_instance:s.source_instance,source_type:'proxmox',site_slug:s.site_slug,cluster_name:s.cluster_name,items:[item]}}]}});
 if(path==='/api/v1/diagnostics')return route.fulfill({json:diag});
 if(path==='/api/v1/sources')return route.fulfill({json:{sources:[s]}});
 if(path==='/api/v1/runs')return route.fulfill({json:{runs:[],next_cursor:null}});
 if(path==='/api/v1/teams')return route.fulfill({json:{teams:{},assignments:{},revision:0}});
 if(path.endsWith('/schedule'))return route.fulfill({json:{source_instance:s.source_instance,sync_enabled:false,sync_interval_seconds:600,scheduler_state:'DISABLED',last_scheduled_run_at:null,next_expected_at:null}});
 return route.fulfill({json:s});});
 await page.goto('/sources?attention=yes');await expect(page.getByRole('link',{name:lang==='ru'?'План заблокирован: обнаружены конфликты':'Plan blocked: conflicts detected'})).toBeVisible();await page.screenshot({path:info.outputPath('blocked-list.png'),fullPage:true});
 await page.goto(`/sources/${s.source_instance}/sync`);await page.locator('.discovery-tool > summary').click();await expect(page.getByText('192.0.2.7/24',{exact:true}).first()).toBeVisible();await page.getByText('Service - pfSense',{exact:true}).click();await expect(page.getByText('8.00 GiB')).toBeVisible();await expect(page.getByText(lang==='ru'?'Память':'Memory',{exact:true})).toBeVisible();await expect(page.getByText('disk0 · 20.00 GiB')).toBeVisible();await page.getByRole('searchbox').fill('192.0.2.7');await expect(page.getByText('Service - pfSense',{exact:true})).toBeVisible();await page.screenshot({path:info.outputPath('discovery.png'),fullPage:true});
 futurePlan=true;await page.reload();const started=page.locator('p').filter({hasText:lang==='ru'?/^Начат/:/^Started/});await expect(started).toBeVisible();await expect(started).not.toContainText(lang==='ru'?'через':'in 5');futurePlan=false;
 uncertain=true;Object.assign(diag.sources[0],{outcome_unconfirmed:true});await page.reload();await expect(page.getByRole('button',{name:lang==='ru'?'Построить план':'Build plan',exact:true})).toBeDisabled();await expect(page.getByRole('alert').first()).toContainText(lang==='ru'?'Результат прежней':'previous synchronization');await page.screenshot({path:info.outputPath('uncertain.png'),fullPage:true});
 const readOnly=page.getByRole('button',{name:lang==='ru'?'Исследовать источник':'Run discovery',exact:true});await expect(readOnly).toBeEnabled();await readOnly.click();await expect.poll(()=>discoveryRequests).toBe(1);await expect(page.getByRole('button',{name:lang==='ru'?'Построить план':'Build plan',exact:true})).toBeDisabled();
 await page.goto(`/sources/${s.source_instance}#configuration`);await expect(page.getByRole('button',{name:lang==='ru'?'Удалить источник':'Remove Source',exact:true})).toBeDisabled();
});
