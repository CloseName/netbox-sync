import {Link} from 'react-router-dom';
import {usePermission} from '../AuthGate';
import {fetchSources} from '../api/sources';
import {fetchDiagnostics} from '../api/diagnostics';
import {fetchRuns} from '../api/runs';
import {useResource} from '../ui/useResource';
import {ResourceNotice} from '../ui/ResourceNotice';
import {Badge,PageHeader,Timestamp} from '../ui/primitives';
import {ProviderIcon} from '../ui/ProviderIcon';
import {composeSources,diagnosticsUsable} from '../ui/operations';
import {runStatus} from '../ui/status';
import {sourcePath,runPath} from '../ui/routes';
import {staleEvidence} from '../ui/runEvidence';
import {tr} from '../ui/i18n';
import {SelectelAttention} from '../ui/SelectelAttention';
export function OverviewPage(){
 const sources=useResource(fetchSources),diagnostics=useResource(fetchDiagnostics),runs=useResource(fetchRuns),selectel=usePermission('bootstrap.manage');
 const data=diagnostics.data,usable=diagnosticsUsable(data),rows=composeSources(sources.data??[],data);
 const concerns=rows.filter(r=>r.attention).sort((a,b)=>a.attention!.priority-b.attention!.priority);
 const componentIssue=data&&Object.values(data.components).some(c=>['DEGRADED','UNAVAILABLE'].includes(c.status));
 const expected=usable?data!.sources.filter(s=>s.enabled&&s.sync_enabled&&s.next_expected_at).sort((a,b)=>a.next_expected_at!.localeCompare(b.next_expected_at!)).slice(0,5):[];
 const running=runs.data?.filter(r=>r.status==='RUNNING'&&!staleEvidence(r,r.source_instance,data));
 const name=(id:string)=>sources.data?.find(s=>s.source_instance===id)?.name??tr('Source');
 const refresh=()=>{sources.refresh();diagnostics.refresh();runs.refresh();};
 return <main className="overview-workspace"><PageHeader title={tr('Overview')} description={tr('Connections, recent results and next actions.')} actions={<button disabled={sources.loading||diagnostics.loading||runs.loading} onClick={refresh}>{tr('Refresh')}</button>}/>
 <ResourceNotice resource={sources} name="Sources" retry={sources.refresh}/><ResourceNotice resource={diagnostics} name="Diagnostics" retry={diagnostics.refresh}/>
 <section className="panel attention-panel"><div className="issue-heading"><div><h2>{tr(concerns.length||componentIssue||data?.stale_runs.length?'Action required':'Connection status')}</h2>{!usable||!sources.data?<p>{tr('Source attention cannot be fully evaluated.')}</p>:concerns.length?<ul className="activity-list">{concerns.slice(0,5).map(r=><li key={r.source.source_instance}><Link to={sourcePath(r.source.source_instance)+(r.diagnostic?.plan_blocked?'/sync':'#diagnostics')}>{r.source.name}</Link><span>{tr(r.attention!.label)}</span></li>)}</ul>:<p>{tr('No source attention items reported.')}</p>}{componentIssue&&<p>{tr('Some application services need checking.')}</p>}{!!data?.stale_runs.length&&<p>{tr('Earlier unfinished runs also need checking.')}</p>}</div><Link className="button-link" to="/diagnostics">{tr('Review problems')} →</Link></div><small>{tr('Checked')} <Timestamp value={data?.generated_at}/></small></section>
 {selectel&&<SelectelAttention/>}
 <div className="overview-grid"><section className="panel"><h2>{tr('Recent runs')}</h2><ResourceNotice resource={runs} name="Run history" retry={runs.refresh}/>{runs.data?.length?<ul className="activity-list">{runs.data.slice(0,5).map(r=><li key={r.run_id}><Link to={runPath(r.run_id)}>{name(r.source_instance)}</Link><span><Badge value={runStatus(r.status,!!staleEvidence(r,r.source_instance,data))}/><small> <Timestamp value={r.finished_at??r.started_at}/></small></span></li>)}</ul>:<p>{tr(runs.loading?'Loading…':'No runs have been recorded yet.')}</p>}<Link to="/runs">{tr('Open run history →')}</Link></section>
 <section className="panel"><h2>{tr('Next scheduled runs')}</h2>{!usable?<p>{tr('Schedule evidence unavailable.')}</p>:expected.length?<ul className="activity-list">{expected.map(s=><li key={s.source_instance}><Link to={sourcePath(s.source_instance)+'/schedule'}>{name(s.source_instance)}</Link><Timestamp value={s.next_expected_at}/></li>)}</ul>:<p>{tr('No upcoming runs reported.')}</p>}<small>{tr('Expected start times; queued or blocked runs may start later.')}</small></section></div>
 {!!running?.length&&<section className="panel"><h2>{tr('Recorded running operations')}</h2><ul>{running.map(r=><li key={r.run_id}><Link to={runPath(r.run_id)}>{name(r.source_instance)}</Link> · <Timestamp value={r.started_at}/></li>)}</ul></section>}
 <nav className="overview-providers" aria-label={tr('Sources')}>{[['esxi','ESXi','/sources?provider=esxi'],['proxmox','Proxmox','/sources?provider=proxmox'],['pfsense','pfSense','/sources/pfsense'],...(selectel?[['selectel','Selectel','/sources/selectel']]:[])].map(([id,title,url])=><Link className="provider-entry" key={id} to={url}><ProviderIcon provider={id}/><strong>{title}</strong><span aria-hidden="true">›</span></Link>)}</nav>
 </main>;
}
