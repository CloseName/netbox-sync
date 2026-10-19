import {Link} from 'react-router-dom';
import {useResource} from './useResource';
import {tr} from './i18n';
type Account={account:string;name:string;status:string;error?:string};
async function fetchAttention(signal:AbortSignal):Promise<Account[]>{const r=await fetch('/api/v1/selectel',{signal,cache:'no-store'});if(!r.ok)throw Error();const data=await r.json();if(!Array.isArray(data.items))throw Error();return data.items;}
/** Mounted only for principals with bootstrap.manage (the Selectel capability). */
export function SelectelAttention(){const resource=useResource(fetchAttention),rows=resource.data?.filter(a=>a.error||a.status==='attention');
 if(resource.error)return <p role="status">{tr('Selectel status unavailable.')} <Link to="/sources/selectel">Selectel →</Link></p>;
 return rows?.length?<section className="panel"><h2>Selectel</h2><ul className="issue-list">{rows.map(a=><li key={a.account}><div className="issue-heading"><div><h3>{a.name}</h3><p className="issue-reason">{tr('Collection needs checking.')}</p></div><Link to="/sources/selectel">{tr('Review collection result')} →</Link></div></li>)}</ul></section>:null;
}
