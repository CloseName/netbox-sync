import {useEffect,useState} from 'react';
import {Link,useLocation} from 'react-router-dom';
import {fetchSources} from '../api/sources';
import {fetchPfSense} from '../api/pfsense';
import {useResource} from './useResource';
import {NavIcon} from './NavIcon';
import {tr} from './i18n';
export function SourceNavigation(){
 const location=useLocation();
 const sources=useResource(fetchSources),pfsense=useResource(fetchPfSense);
 const [open,setOpen]=useState(location.pathname.startsWith('/sources'));
 useEffect(()=>{if(location.pathname.startsWith('/sources'))setOpen(true);sources.refresh();pfsense.refresh();},[location.pathname,location.search]);
 return <div className="source-navigation"><button type="button" className="source-nav-toggle" aria-expanded={open} aria-controls="source-subnavigation" onClick={()=>setOpen(!open)}><NavIcon path="/sources"/>{tr('Sources')} <span aria-hidden="true">{open?'▾':'▸'}</span></button>
 {open&&<div id="source-subnavigation">
 {(['esxi','proxmox'] as const).map(provider=><Link key={provider} to={'/sources?provider='+provider} aria-current={location.pathname==='/sources'&&new URLSearchParams(location.search).get('provider')===provider?'page':undefined}>{provider==='esxi'?'ESXi':'Proxmox'} ({sources.error?'—':sources.data?.filter(s=>s.type===provider).length??'…'})</Link>)}
 <Link to="/sources/pfsense" aria-current={location.pathname==='/sources/pfsense'?'page':undefined}>pfSense ({pfsense.error?'—':pfsense.data?.count??'…'})</Link>
 </div>}</div>;
}
