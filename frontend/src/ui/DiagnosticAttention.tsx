import {Link} from 'react-router-dom';
import type {Diagnostics} from '../api/diagnostics';
import {attention,diagnosticsUsable,completedWithLimitations} from './operations';
import {SourceName} from './SourceNames';
import {componentLabels,coverage} from './diagnosticEvidence';
import {Timestamp} from './primitives';
import {sourcePath,runPath} from './routes';
import {tr} from './i18n';
export function DiagnosticAttention({data,source}:{data:Diagnostics;source?:string}){
 const rows=diagnosticsUsable(data)?data.sources.filter(s=>(!source||s.source_instance===source)&&attention(s)).sort((a,b)=>attention(a)!.priority-attention(b)!.priority):[];
 const components=source?[]:Object.entries(data.components).filter(([,c])=>['DEGRADED','UNAVAILABLE'].includes(c.status));
 // Historical stale runs may not be the latest run. Keep them visible, without
 // duplicating the current source warning or claiming a global problem count.
 const historical=data.warnings.filter(w=>(!source||source===w.source_instance)&&!rows.some(s=>s.source_instance===w.source_instance&&s.latest_run?.run_id===w.run_id)&&w.warning_code==='STALE_RUNNING');
 const limited=data.sources.filter(s=>(!source||s.source_instance===source)&&completedWithLimitations(s));
 return <div className="diagnostic-attention">{!diagnosticsUsable(data)&&<p role="status">{tr("Source evidence unavailable. Registry and run history checks must both succeed.")}</p>}<ul className="issue-list">
 {components.map(([key,c])=><li key={key}><div className="issue-heading"><div><h3>{tr(componentLabels[key as keyof typeof componentLabels])}</h3><p className="issue-reason">{tr('Service availability could not be confirmed.')}</p></div><Link to="/system">{tr('Check system health')}</Link></div><details><summary>{tr('Support details')}</summary><p>{c.safe_message}</p><code>{c.safe_code}</code><p><Timestamp value={c.checked_at}/></p></details></li>)}
 {rows.map(s=>{const issue=attention(s)!;const uncertain=issue.priority===1;const delayed=s.warnings.includes('SCHEDULED_ACTIVITY_DELAYED');return <li key={s.source_instance}><div className="issue-heading"><div><h3>{source?<span>{tr('This source')}</span>:<SourceName id={s.source_instance}/>}</h3><p className="issue-reason">{tr(issue.label)}</p><p className="muted">{tr(uncertain?'Some changes may already be in NetBox. Review the journal and current objects before another sync.':s.plan_blocked?'Resolve the conflicting plan rows, then build a new plan.':delayed?'Check the schedule and the last run before changing the interval.':'Open the source to check access and the last operation.')}</p></div><Link className="button-link" to={sourcePath(s.source_instance)+(uncertain?'#configuration':s.plan_blocked?'/sync':delayed?'/schedule':'#diagnostics')}>{tr(uncertain?'Review journal and current objects':s.plan_blocked?'Review plan':delayed?'Open schedule':'Open source')}</Link></div><small><Timestamp value={s.latest_run?.started_at}/></small>{s.latest_run&&<details><summary>{tr('Support details')}</summary><Link to={runPath(s.latest_run.run_id)}>{tr('Open run')}</Link><p>{s.source_instance}</p><p>{s.latest_run.status} · {s.latest_run.run_id}</p></details>}</li>;})}
 {historical.map((w,i)=><li key={'history-'+(w.run_id??i)}><h3>{tr('Completion unconfirmed')}{w.source_instance&&<> · <SourceName id={w.source_instance}/></>}</h3><p>{tr('An earlier run needs checking; a newer result does not prove its outcome.')}</p>{w.run_id&&<Link to={runPath(w.run_id)}>{tr('Open run')}</Link>}</li>)}
 </ul>{!rows.length&&!components.length&&!historical.length&&<p>{tr(diagnosticsUsable(data)?'No attention items reported in this snapshot.':'No source assessment available. Review component evidence.')}</p>}
 {!!limited.length&&<details className="quiet-detail"><summary>{tr('Completed with collection limitations')} ({limited.length})</summary><p>{tr('These runs completed, but some categories were not synchronized. Review their plans for the exact scope.')}</p><ul>{limited.map(s=><li key={s.source_instance}><Link to={s.latest_run?runPath(s.latest_run.run_id):sourcePath(s.source_instance)}>{source?tr('Open run'):<SourceName id={s.source_instance}/>}</Link></li>)}</ul></details>}
 <details className="quiet-detail"><summary>{tr('About this check')}</summary><p>{tr(coverage(data))}</p><p>{tr('Checked')} <Timestamp value={data.generated_at}/></p></details></div>;
}
