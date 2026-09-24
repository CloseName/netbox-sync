import {SourceInventoryAudit} from '../components/SourceInventoryAudit';
import {RunReconciliation} from '../components/RunReconciliation';
import {usePermission} from '../AuthGate';
import {useLanguage} from '../ui/language';
import {exactTime} from '../ui/format';
import {tr} from "../ui/i18n";
import {useCallback,useState} from 'react';
import {SourceRetirementPanel} from './SourceRetirementPanel';
import { Link } from 'react-router-dom';
import { sourceLifecycle, type SourceLifecycle as Lifecycle } from '../api/lifecycle';
import { useResource } from '../ui/useResource';
import { Alert, LoadingState } from '../ui/primitives';
const credentialText = (state: Lifecycle['credential_state']) => ({
  RETAINED_BY_REQUEST: 'Local stored credentials retained as requested.',
  REMOVED: 'Local stored credentials removed.',
  RETAINED_SHARED_OR_LEGACY: 'Shared or ambiguous credentials retained. Operator follow-up is required.',
  CLEANUP_FAILED: 'Credential cleanup could not be confirmed. Operator follow-up is required; no automatic retry.',
}[state ?? 'RETAINED_BY_REQUEST']);
export function RemovedSource({ value:initial }: { value: Lifecycle }) {
  const [value,setValue]=useState(initial);
  const [reviewGeneration,setReviewGeneration]=useState(0);
  const [language]=useLanguage();const canResolve=usePermission('source.remove');
  return <main className="source-workspace"><h1>{tr("Source removed from NetBox Sync")}{" "}</h1>
    <p>{value.display_name}</p><details><summary>{tr("Technical details")}</summary><code>{value.source_instance}</code></details>
    <p>{tr("Removed")}{" "}<time dateTime={value.removed_at??undefined}>{value.removed_at?exactTime(value.removed_at):tr("Unavailable")}</time></p>
    <p>{value.retirement?.state==='FINALIZED'
      ?(language==='ru'?'История запусков сохранена. Удаление проверенного списка объектов NetBox подтверждено квитанцией.':'Run history is retained. The reviewed NetBox objects were deleted with a confirmed receipt.')
      :tr("Historical runs are retained. NetBox infrastructure was not deleted.")}</p>
    <p>{tr("This Source ID is reserved and cannot be registered again automatically.")}{" "}</p>
    <p>{tr(credentialText(value.credential_state))} {tr("Provider credentials were not revoked.")}{" "}</p>
    {canResolve&&value.retirement?.state!=='FINALIZED'&&<SourceRetirementPanel key={reviewGeneration} retained source={{source_instance:value.source_instance,name:value.display_name}} onRemoved={setValue}/>}
    {canResolve&&value.retirement?.state==='FINALIZED'&&<SourceInventoryAudit source={value.source_instance}/> }
    {canResolve&&<RunReconciliation source={value.source_instance} onSaved={()=>setReviewGeneration(g=>g+1)}/>}
    <div className="page-actions"><Link to={'/runs?source_instance=' + encodeURIComponent(value.source_instance)}>{tr("View run history")}{" "}</Link><Link to="/sources">{tr("Back to Sources")}{" "}</Link></div>
  </main>;
}
export function RemovedSourceLookup({ source }: { source: string }) {
  const state = useResource(useCallback((signal) => sourceLifecycle(source, signal), [source]));
  if (state.loading) return <main><LoadingState label={tr("Checking source lifecycle...")} /></main>;
  if (state.data?.removed_at) return <RemovedSource value={state.data} />;
  return <main><h1>{tr("Source not found")}{" "}</h1><Alert retry={state.refresh}>{state.error ? tr("Source could not be found. Its removal state could not be verified.") : tr("This source does not exist in the active registry.")}</Alert><Link to="/sources">{tr("Back to Sources")}{" "}</Link></main>;
}
export {SourceRetirementPanel as SourceLifecyclePanel} from './SourceRetirementPanel';
