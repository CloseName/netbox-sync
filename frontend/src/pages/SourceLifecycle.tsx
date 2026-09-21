import {useLanguage} from '../ui/language';
import {exactTime} from '../ui/format';
import {tr} from "../ui/i18n";
import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import type { Source } from '../api/sources';
import { sourceLifecycle, type SourceLifecycle as Lifecycle } from '../api/lifecycle';
import { useResource } from '../ui/useResource';
import { Alert, LoadingState } from '../ui/primitives';
import { sourcePath } from '../ui/routes';
const credentialText = (state: Lifecycle['credential_state']) => ({
  RETAINED_BY_REQUEST: 'Local stored credentials retained as requested.',
  REMOVED: 'Local stored credentials removed.',
  RETAINED_SHARED_OR_LEGACY: 'Shared or ambiguous credentials retained. Operator follow-up is required.',
  CLEANUP_FAILED: 'Credential cleanup could not be confirmed. Operator follow-up is required; no automatic retry.',
}[state ?? 'RETAINED_BY_REQUEST']);
export function RemovedSource({ value }: { value: Lifecycle }) {
  return <main className="source-workspace"><h1>{tr("Source removed from NetBox Sync")}{" "}</h1>
    <p>{value.display_name}</p><details><summary>{tr("Technical details")}</summary><code>{value.source_instance}</code></details>
    <p>{tr("Removed")}{" "}<time dateTime={value.removed_at??undefined}>{value.removed_at?exactTime(value.removed_at):tr("Unavailable")}</time></p>
    <p>{tr("Historical runs are retained. NetBox infrastructure was not deleted.")}{" "}</p>
    <p>{tr("This Source ID is reserved and cannot be registered again automatically.")}{" "}</p>
    <p>{tr(credentialText(value.credential_state))} {tr("Provider credentials were not revoked.")}{" "}</p>
    <div className="page-actions"><Link to={'/runs?source_instance=' + encodeURIComponent(value.source_instance)}>{tr("View run history")}{" "}</Link><Link to="/sources">{tr("Back to Sources")}{" "}</Link></div>
  </main>;
}
export function RemovedSourceLookup({ source }: { source: string }) {
  const state = useResource(useCallback((signal) => sourceLifecycle(source, signal), [source]));
  if (state.loading) return <main><LoadingState label={tr("Checking source lifecycle...")} /></main>;
  if (state.data?.removed_at) return <RemovedSource value={state.data} />;
  return <main><h1>{tr("Source not found")}{" "}</h1><Alert retry={state.refresh}>{state.error ? tr("Source could not be found. Its removal state could not be verified.") : tr("This source does not exist in the active registry.")}</Alert><Link to="/sources">{tr("Back to Sources")}{" "}</Link></main>;
}
export function SourceLifecyclePanel({ source, onRemoved }: { source: Source; onRemoved: (value: Lifecycle)=>void }) {
  const [language]=useLanguage(),t=(en:string,ru:string)=>language==='ru'?ru:en;

  const state = useResource(useCallback(signal => sourceLifecycle(source.source_instance, signal),[source.source_instance]));
  const [open,setOpen]=useState(false), [busy,setBusy]=useState(false), [error,setError]=useState('');
  const dialog=useRef<HTMLDialogElement>(null), trigger=useRef<HTMLButtonElement>(null), cancel=useRef<HTMLButtonElement>(null);
  useEffect(()=>{ if(open){dialog.current?.showModal();cancel.current?.focus();} else dialog.current?.close(); },[open]);
  const close=()=>{setOpen(false);trigger.current?.focus();};
  const remove=async()=>{
    if(busy || state.data?.removal_blocker || !state.data?.revision) return;
    setBusy(true);setError('');
    try { const result=await sourceLifecycle(source.source_instance,AbortSignal.timeout(20000),{revision:state.data.revision,confirmed_source:state.data.display_name,remove_credentials:true}); if(!result.removed_at) throw new Error(); onRemoved(result); }
    catch(e) { setError(e instanceof Error ? e.message : 'Removal could not be confirmed. Reload state.'); state.refresh(); }
    finally {setBusy(false);}
  };
  useEffect(()=>{if(state.data?.removed_at) onRemoved(state.data);},[state.data,onRemoved]);
  return <section className="source-panel"><h3>{tr("Lifecycle")}{" "}</h3>
    <p>{tr("Removing a source from NetBox Sync does not delete devices, VMs, interfaces, IP addresses or other infrastructure objects from NetBox.")}{" "}</p>
    {state.data?.removal_blocker&&<p role="alert">{state.data.removal_blocker==='SOURCE_APPLY_UNCONFIRMED'?t('Removal is blocked: a previous synchronization is unconfirmed. An administrator must reconcile its effects in NetBox; do not repeat apply.','Удаление заблокировано: результат прежней синхронизации не подтверждён. Администратору нужно сверить её последствия в NetBox; не повторяйте применение.'):t('Wait for the active operation to finish.','Дождитесь завершения выполняющейся операции.')}</p>}
    {state.error && <Alert retry={state.refresh}>{tr("Source lifecycle is unavailable.")}{" "}</Alert>}
    <button className="danger" ref={trigger} disabled={!!state.data?.removal_blocker || !state.data?.revision || state.loading || !!state.error} onClick={()=>setOpen(true)}>{tr("Remove Source")}{" "}</button>
    <dialog ref={dialog} className="sync-dialog" onCancel={event=>{event.preventDefault();if(!busy)close();}} aria-labelledby="remove-title">
      <h2 id="remove-title">{t('Remove source ','Удалить источник ')}{source.name}?</h2>
      <p>{t('Automatic synchronization will stop. NetBox objects and run history are retained.','Автоматическая синхронизация будет остановлена. Объекты в NetBox и история запусков сохранятся.')}</p>
      {error && <p role="alert">{tr(error)} <Link to={sourcePath(source.source_instance)+'/runs'}>{tr("Review run history")}{" "}</Link></p>}
      <div className="page-actions"><button ref={cancel} disabled={busy} onClick={close}>{tr("Cancel")}{" "}</button><button className="danger" disabled={busy || !!state.data?.removal_blocker || !state.data?.revision || !!state.error} onClick={remove}>{busy?tr("Removing source..."):tr("Remove Source")}</button></div>
    </dialog>
  </section>;
}
