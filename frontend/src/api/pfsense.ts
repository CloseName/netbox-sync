export interface PfSenseVM {id:number;name:string;cluster:string;site:string;address:string;url:string}
export async function fetchPfSense(signal:AbortSignal):Promise<{items:PfSenseVM[];count:number}>{
  const items:PfSenseVM[]=[]; let total=0;
  do {
    const response=await fetch(`/api/v1/pfsense?offset=${items.length}`,{signal,cache:'no-store'});
    if(!response.ok)throw new Error('pfSense list unavailable');
    const page=await response.json();
    if(!Array.isArray(page.items)||!Number.isSafeInteger(page.count)||page.count<0||page.count>10000||(!page.items.length&&items.length<page.count))throw new Error('Invalid pfSense list');
    total=page.count;items.push(...page.items);
    if(items.length>total)throw new Error('pfSense list changed; refresh');
  } while(items.length<total);
  return {items,count:total};
}
