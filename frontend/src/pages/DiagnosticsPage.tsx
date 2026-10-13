import {SelectelAttention} from '../ui/SelectelAttention';
import {usePermission} from '../AuthGate';
import {useState} from 'react';
import {Link} from 'react-router-dom';
import {SourceNames,useSourceNames} from '../ui/SourceNames';
import {tr} from '../ui/i18n';
import {fetchDiagnostics} from '../api/diagnostics';
import {useResource} from '../ui/useResource';
import {ResourceFeedback} from '../ui/ResourceFeedback';
import {PageHeader,Badge,Timestamp} from '../ui/primitives';
import {DiagnosticAttention} from '../ui/DiagnosticAttention';
import {componentLabels,componentReason} from '../ui/diagnosticEvidence';
import type {ComponentKey} from '../ui/diagnosticEvidence';
import {healthStatus} from '../ui/status';
export function DiagnosticsPage(){return <SourceNames><Problems/></SourceNames>;}
function Problems(){
 const resource=useResource(fetchDiagnostics),data=resource.data,names=useSourceNames();
 const [search,setSearch]=useState('');
 const selectel=usePermission('bootstrap.manage');
 const matches=(id:string|null)=>!search||!!id&&[id,names.find(s=>s.source_instance===id)?.name].some(v=>v?.toLowerCase().includes(search.toLowerCase()));
 const filtered=data?{...data,sources:data.sources.filter(s=>matches(s.source_instance)),warnings:data.warnings.filter(w=>matches(w.source_instance))}:null;
 return <main className="operations-workspace"><PageHeader title={tr('Problems')} description={tr('What needs your attention and what to do next.')} actions={<button disabled={resource.loading} onClick={resource.refresh}>{tr('Refresh')}</button>}/>
 <ResourceFeedback resource={resource} label={tr('diagnostics')} evidenceAt={data?.generated_at}/>
 <label>{tr('Search sources')}<input type="search" value={search} onChange={e=>setSearch(e.target.value)}/></label>
 {filtered&&<section className="panel"><DiagnosticAttention data={filtered}/></section>}
 {selectel&&<SelectelAttention/>}
 <p><Link to="/system">{tr('Check system health')} →</Link></p>
 {data&&<details className="quiet-detail"><summary>{tr('Component checks')}</summary>{(Object.keys(componentLabels) as ComponentKey[]).map(key=><section id={'component-'+key} className="panel" key={key}><h2>{tr(componentLabels[key])}</h2><Badge value={healthStatus(data.components[key].status)}/><p>{tr(componentReason(key,data.components[key]))}</p><small><Timestamp value={data.components[key].checked_at}/></small></section>)}</details>}
 </main>;
}
