import {Link} from 'react-router-dom';
import type {SourceDiagnostic} from '../api/diagnostics';
import {attention,completedWithLimitations} from './operations';
import {Badge,Timestamp} from './primitives';
import {runStatus} from './status';
import {sourcePath,runPath} from './routes';
import {tr} from './i18n';

export function SourceResult({evidence}:{evidence?:SourceDiagnostic}) {
 if(!evidence)return <span className="muted">{tr('Status unavailable')}</span>;
 const issue=attention(evidence), run=evidence.latest_run;
 return <>{issue ? <Link to={sourcePath(evidence.source_instance)+(evidence.plan_blocked?'/sync':'#diagnostics')}><Badge value={{label:issue.label,tone:issue.priority<=2||['FAILED','FAILED_BEFORE_WRITE','BLOCKED'].includes(run?.status??'')?'danger':'warning',icon:'!'}}/></Link>
 : run ? <Link to={runPath(run.run_id)}><Badge value={completedWithLimitations(evidence)?{label:'Completed with limitations',tone:'success',icon:'✓'}:runStatus(run.status)}/></Link>
 : <span className="muted">{tr('No recorded run')}</span>}
 {run&&<small><Timestamp value={run.finished_at??run.started_at}/></small>}
 {completedWithLimitations(evidence)&&<small><Link to={sourcePath(evidence.source_instance)+'#diagnostics'}>{tr('View collection limitations')}</Link></small>}</>;
}
