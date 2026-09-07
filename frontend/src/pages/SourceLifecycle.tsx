import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import type { Source } from '../api/sources';
import { sourceLifecycle, type SourceLifecycle as Lifecycle } from '../api/lifecycle';
import { useResource } from '../ui/useResource';
import { Timestamp, Alert, LoadingState } from '../ui/primitives';
import { sourcePath } from '../ui/routes';
const credentialText = (state: Lifecycle['credential_state']) => ({
  RETAINED_BY_REQUEST: 'Local stored credentials retained as requested.',
  REMOVED: 'Local stored credentials removed.',
  RETAINED_SHARED_OR_LEGACY: 'Shared or ambiguous credentials retained. Operator follow-up is required.',
  CLEANUP_FAILED: 'Credential cleanup could not be confirmed. Operator follow-up is required; no automatic retry.',
}[state ?? 'RETAINED_BY_REQUEST']);
export function RemovedSource({ value }: { value: Lifecycle }) {
  return <main className="source-workspace"><h1>Source removed from NetBox Sync</h1>
    <p>{value.display_name} <code>{value.source_instance}</code></p>
    <p>Removed <Timestamp value={value.removed_at} /></p>
    <p>Historical runs are retained. NetBox infrastructure was not deleted.</p>
    <p>This Source ID is reserved and cannot be registered again automatically.</p>
    <p>{credentialText(value.credential_state)} Provider credentials were not revoked.</p>
    <div className="page-actions"><Link to={'/runs?source_instance=' + encodeURIComponent(value.source_instance)}>View run history</Link><Link to="/sources">Back to Sources</Link></div>
  </main>;
}
export function RemovedSourceLookup({ source }: { source: string }) {
  const state = useResource(useCallback((signal) => sourceLifecycle(source, signal), [source]));
  if (state.loading) return <main><LoadingState label="Checking source lifecycle..." /></main>;
  if (state.data?.removed_at) return <RemovedSource value={state.data} />;
  return <main><h1>Source not found</h1><Alert retry={state.refresh}>{state.error ? 'Source could not be found. Its removal state could not be verified.' : 'This source does not exist in the active registry.'}</Alert><Link to="/sources">Back to Sources</Link></main>;
}
export function SourceLifecyclePanel({ source, onRemoved }: { source: Source; onRemoved: (value: Lifecycle)=>void }) {
  const state = useResource(useCallback(signal => sourceLifecycle(source.source_instance, signal),[source.source_instance]));
  const [open,setOpen]=useState(false), [typed,setTyped]=useState(''), [cleanup,setCleanup]=useState(false), [busy,setBusy]=useState(false), [error,setError]=useState('');
  const dialog=useRef<HTMLDialogElement>(null), trigger=useRef<HTMLButtonElement>(null), cancel=useRef<HTMLButtonElement>(null);
  useEffect(()=>{ if(open){dialog.current?.showModal();cancel.current?.focus();} else dialog.current?.close(); },[open]);
  const close=()=>{setOpen(false);setTyped('');setCleanup(false);trigger.current?.focus();};
  const remove=async()=>{
    if(busy || typed!==source.source_instance || !state.data?.revision) return;
    setBusy(true);setError('');
    try { const result=await sourceLifecycle(source.source_instance,AbortSignal.timeout(20000),{revision:state.data.revision,confirmed_source:typed,remove_credentials:cleanup}); if(!result.removed_at) throw new Error(); onRemoved(result); }
    catch(e) { setError(e instanceof Error ? e.message : 'Removal could not be confirmed. Reload state.'); state.refresh(); }
    finally {setBusy(false);}
  };
  useEffect(()=>{if(state.data?.removed_at) onRemoved(state.data);},[state.data,onRemoved]);
  return <section className="source-panel"><h3>Lifecycle</h3>
    <p>Removing a source from NetBox Sync does not delete devices, VMs, interfaces, IP addresses or other infrastructure objects from NetBox.</p>
    {state.error && <Alert retry={state.refresh}>Source lifecycle is unavailable.</Alert>}
    <button ref={trigger} disabled={!state.data?.revision || state.loading || !!state.error} onClick={()=>setOpen(true)}>Remove Source</button>
    <dialog ref={dialog} className="sync-dialog" onCancel={event=>{event.preventDefault();if(!busy)close();}} aria-labelledby="remove-title">
      <h2 id="remove-title">Remove &quot;{source.name}&quot; from NetBox Sync?</h2>
      <p>Source ID: <code>{source.source_instance}</code></p>
      <dl className="source-facts">{[['NetBox objects','Retained'],['Run history','Retained'],['Source identity','Reserved'],['Automatic sync','Stopped']].map(([label,value])=><div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
      <p>No NetBox infrastructure objects will be deleted.</p>
      <label><input type="checkbox" checked={cleanup} disabled={busy} onChange={e=>setCleanup(e.target.checked)} /> Remove local stored credentials only if exclusive broker ownership is proven</label>
      <p>Shared or ambiguous credentials are retained. Provider-side token revocation is not performed.</p>
      <label htmlFor="remove-source-id">Type the exact Source ID</label><input id="remove-source-id" value={typed} onChange={e=>setTyped(e.target.value)} autoComplete="off" disabled={busy} />
      {error && <p role="alert">{error} <Link to={sourcePath(source.source_instance)+'/runs'}>Review run history</Link></p>}
      <div className="page-actions"><button ref={cancel} disabled={busy} onClick={close}>Cancel</button><button className="danger" disabled={busy || typed!==source.source_instance || !state.data?.revision || !!state.error} onClick={remove}>{busy?'Removing source...':'Remove Source'}</button></div>
    </dialog>
  </section>;
}
