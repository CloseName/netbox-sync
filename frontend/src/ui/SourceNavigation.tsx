import {useEffect,useState} from 'react';
import {Link,useLocation} from 'react-router-dom';
import {fetchSources} from '../api/sources';
import {fetchPfSense} from '../api/pfsense';
import {useResource} from './useResource';
import {NavIcon} from './NavIcon';
import {ProviderIcon} from './ProviderIcon';
import {tr} from './i18n';
import {usePermission} from '../AuthGate';
export function SourceNavigation(){
 const selectel=usePermission('bootstrap.manage');
 const location=useLocation();
 const sources=useResource(fetchSources),pfsense=useResource(fetchPfSense);
 const [open,setOpen]=useState(location.pathname.startsWith('/sources'));
 useEffect(()=>{if(location.pathname.startsWith('/sources'))setOpen(true);sources.refresh();pfsense.refresh();},[location.pathname,location.search]);
 return <div className="source-navigation"><button type="button" className="source-nav-toggle" aria-expanded={open} aria-controls="source-subnavigation" onClick={()=>setOpen(!open)}><NavIcon path="/sources"/>{tr('Sources')} <svg className="nav-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="m9 5 7 7-7 7"/></svg></button>
 {open&&<div id="source-subnavigation">
 {(['esxi','proxmox'] as const).map(provider=><Link key={provider} to={'/sources?provider='+provider} aria-current={location.pathname==='/sources'&&new URLSearchParams(location.search).get('provider')===provider?'page':undefined}><ProviderIcon provider={provider}/><span>{provider==='esxi'?'ESXi':'Proxmox'}</span><span className="nav-count">({sources.error?'—':sources.data?.filter(s=>s.type===provider).length??'…'})</span></Link>)}
 <Link to="/sources/pfsense" aria-current={location.pathname==='/sources/pfsense'?'page':undefined}><ProviderIcon provider="pfsense"/><span>pfSense</span><span className="nav-count">({pfsense.error?'—':pfsense.data?.count??'…'})</span></Link>
 {selectel&&<Link to="/sources/selectel" aria-current={location.pathname==='/sources/selectel'?'page':undefined}><ProviderIcon provider="selectel"/>Selectel</Link>}
 </div>}</div>;
}
