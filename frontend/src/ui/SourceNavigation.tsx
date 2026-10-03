import {useEffect,useState} from 'react';
import {NavLink,useLocation} from 'react-router-dom';
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
 {(['esxi','proxmox'] as const).map(provider=><NavLink key={provider} to={'/sources?provider='+provider} className={()=>location.pathname==='/sources'&&location.search.includes('provider='+provider)?'active':''}>{provider==='esxi'?'ESXi':'Proxmox'} ({sources.error?'—':sources.data?.filter(s=>s.type===provider).length??'…'})</NavLink>)}
 <NavLink to="/sources/pfsense">pfSense ({pfsense.error?'—':pfsense.data?.count??'…'})</NavLink>
 </div>}</div>;
}
