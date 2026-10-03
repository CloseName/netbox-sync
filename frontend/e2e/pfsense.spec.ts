import {test,expect} from './auth-fixture';
import {source} from '../tests/fixtures.mjs';
test('source categories and pfSense setup keep credentials out of repeated collection',async({page})=>{
 const calls:any[]=[];
 await page.route('**/api/v1/**',route=>{
 const path=new URL(route.request().url()).pathname;
 if(path==='/api/v1/bootstrap')return route.fulfill({json:{status:'READY',completed:true,revision:1,url:'https://nb.test',read_token_present:true,apply_token_present:true,safe_code:null,checks:[],validated_at:1}});
 if(path==='/api/v1/sources')return route.fulfill({json:{sources:[{...source(),type:'esxi'},{...source(2),type:'proxmox'}]}});
 if(path==='/api/v1/pfsense')return route.fulfill({json:{count:1,items:[{id:2609,name:'Service-pfSense',cluster:'PVE-INFRA-TEST',site:'Selectel',address:'10.24.0.1',url:'https://nb.test/virtualization/virtual-machines/2609/'}]}});
 if(path==='/api/v1/policy')return route.fulfill({json:{revision:1}});
 if(path.endsWith('/status'))return route.fulfill({json:{status:'NOT_CONNECTED'}});
 if(path.endsWith('/connect')||path.endsWith('/collect')){calls.push(route.request().postDataJSON());return route.fulfill({json:{status:'CONNECTED',ssh_port:2233,collected_at:'2026-10-04T00:00:00Z'}});}
 return route.fulfill({json:{}});
 });
 await page.goto('/sources/pfsense');
 await expect(page.getByRole('link',{name:'ESXi (1)',exact:true})).toBeVisible();
 await expect(page.getByRole('link',{name:'Proxmox (1)',exact:true})).toBeVisible();
 await expect(page.getByRole('link',{name:'pfSense (1)',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Connection',exact:true}).click();
 await page.getByLabel('Administrator (LDAP or local)',{exact:true}).fill('admin@example.test');
 await page.getByLabel('Password',{exact:true}).fill('not-a-real-password');
 await page.getByRole('button',{name:'Set up and collect',exact:true}).click();
 await expect(page.getByText('Connected',{exact:false})).toBeVisible();
 await expect(page.getByLabel('Password',{exact:true})).toHaveValue('');
 await page.getByRole('button',{name:'Collect now',exact:true}).click();
 await expect.poll(()=>calls.length).toBe(2);
 expect(calls[0].username).toBe('admin@example.test');expect(calls[0].verify_tls).toBe(true);
 expect(calls[1]).toEqual({policy_revision:1});
 await page.getByRole('button',{name:'Close',exact:true}).click();
 await page.getByRole('link',{name:'Proxmox (1)',exact:true}).click();
 await expect(page).toHaveURL(/provider=proxmox/);
});
