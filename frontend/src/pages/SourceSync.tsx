import {runStatus} from '../ui/status';
import {fetchSourceRuns,fetchRun,type SyncRun} from '../api/runs';
import {usePermission} from '../AuthGate';
import {staleReason} from '../ui/planStale';
import {hasChanges} from '../ui/plan';
import {publicError} from '../ui/publicErrors';
import {OperationFeedback} from "../ui/OperationFeedback";
import {tr} from "../ui/i18n";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import type { Source } from "../api/sources";
import { fetchOperations, startOperation, operationReason, operationRequestMessage, type SourceOperation } from "../api/operations";
import type { DiscoveryResult } from "../api/discovery";
import {
  applySync,
  ManualSyncRequestError,
  prepareSync,
} from "../api/sync";
import type { SyncPlan } from "../api/sync";
import { applyOutcome, failedOutcome } from "../ui/syncOutcome";
import type { SyncOutcome } from "../ui/syncOutcome";
import { Badge, Timestamp } from "../ui/primitives";
import { sourcePath, runPath } from "../ui/routes";
import { PlanReview, PlanSummary } from "../components/PlanReview";
import { DiscoveryReview } from "../components/DiscoveryReview";
type Phase = "idle" | "planning" | "validating" | "applying";
export function SourceSync({
  detail,
  active = true,
  latestRunFinishedAt,
  onRunChange,
  onPlanBlocked,
}: {
  detail: Source;
  active?: boolean;
  latestRunFinishedAt?: string;
  onRunChange?:()=>void;
  onPlanBlocked?:(blocked:boolean)=>void;
}) {
  const canPlan = usePermission('source.plan'), canApply = usePermission('source.apply');
  const [phase, setPhase] = useState<Phase>("idle"),
    [started, setStarted] = useState(0);
  const [plan, setPlan] = useState<{
      value: SyncPlan;
      received: string;
      operationId: string;
    } | null>(null),
    [usable, setUsable] = useState(false);
  const [planningError, setPlanningError] =
    useState<ManualSyncRequestError | null>(null);
  const [result, setResult] = useState<SyncOutcome | null>(null);
  const [discovery, setDiscovery] = useState<{
    value: DiscoveryResult;
    received: string;
  } | null>(null);
  const [discovering, setDiscovering] = useState(false),
    [discoveryStarted, setDiscoveryStarted] = useState(0),
    [discoveryError, setDiscoveryError] = useState("");
  const [discoveryOpen, setDiscoveryOpen] = useState(false),
    [confirmOpen, setConfirmOpen] = useState(false);
  const busy = useRef(false),
    discoveryBusy = useRef(false),
    alive = useRef(true);
  const dialog = useRef<HTMLDialogElement>(null),
    confirmButton = useRef<HTMLButtonElement>(null),
    cancelButton = useRef<HTMLButtonElement>(null);
  const feedback = useRef<HTMLDivElement>(null);
  const selected = detail.source_instance;
  const [operations, setOperations] = useState<SourceOperation[]>([]);
  const [operationError, setOperationError] = useState('');
  const [loaded, setLoaded] = useState(false);
  const [refreshOperations, setRefreshOperations] = useState(0);
  const reportBlocked = useRef(onPlanBlocked); reportBlocked.current = onPlanBlocked;
  const reviewedId = useRef('');
  const inspectedId = useRef('');
  const [runs,setRuns]=useState<SyncRun[]>([]),[runId,setRunId]=useState(''),[historyLoaded,setHistoryLoaded]=useState(false),[historyError,setHistoryError]=useState(false);
  const runChanged=useRef(onRunChange); runChanged.current=onRunChange;
  useEffect(()=>{
    if(!active)return;
    let stopped=false;const controller=new AbortController();
    let previous='';
    const read=async()=>{try{const rows=await fetchSourceRuns(selected,controller.signal);if(stopped)return;
      const used=operations.find(row=>row.operation_kind==='PLAN')?.used_run_id;
      if(used&&!rows.some(row=>row.run_id===used))rows.push(await fetchRun(used,controller.signal));
      if(stopped)return;setRuns(rows);setHistoryLoaded(true);setHistoryError(false);const signature=rows.map(r=>r.run_id+r.status).join();
      if(signature!==previous){previous=signature;runChanged.current?.();}
    }catch{if(!stopped){setHistoryLoaded(false);setHistoryError(true);}}};
    void read();const timer=setInterval(read,5000);return()=>{stopped=true;controller.abort();clearInterval(timer);};
  },[selected,active,refreshOperations,operations]);
  const acceptedRun=runs.find(r=>r.run_id===runId)??runs.find(r=>r.trigger==='manual'&&r.plan_digest===plan?.value.digest&&Date.parse(r.started_at)>=Date.parse(plan?.received??''));
  const planOperation = operations.find(item => item.operation_kind === 'PLAN');
  const consumed=!!planOperation?.used_run_id||runs.some(r=>r.trigger==='manual'&&r.plan_digest===plan?.value.digest&&Date.parse(r.started_at)>=Date.parse(plan?.received??''));
  const historicalPlan=!!latestRunFinishedAt&&!!planOperation?.finished_at&&Date.parse(latestRunFinishedAt)>Date.parse(planOperation.finished_at);
  const expiredPlan=planOperation?.safe_error_code==='RESULT_EXPIRED';
  const expiredDiscovery=operations.find(row=>row.operation_kind==='DISCOVERY'&&row.safe_error_code==='RESULT_EXPIRED');
  const inspectionOperation=operations.find(row=>row.operation_kind==='DISCOVERY');
  const historicalDiscovery=!!latestRunFinishedAt&&!!inspectionOperation?.finished_at&&Date.parse(latestRunFinishedAt)>Date.parse(inspectionOperation.finished_at);
  useEffect(() => {
    if (!active) return;
    const reconnect = () => setRefreshOperations(value=>value+1);
    window.addEventListener('focus', reconnect);
    return () => window.removeEventListener('focus', reconnect);
  }, [active]);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const rows = await fetchOperations(selected, AbortSignal.any([controller.signal, AbortSignal.timeout(10000)]));
        if (controller.signal.aborted) return;
        setOperations(rows); setLoaded(true); setOperationError('');
        const latest = rows.find(row => row.operation_kind === 'PLAN');
        reportBlocked.current?.(latest?.status === 'READY' && !!latest.result && !(latest.result as SyncPlan).apply_allowed);
        if (rows.some(row => row.status === 'RUNNING')) timer = setTimeout(poll, 2500);
      } catch (error) {
        if (!controller.signal.aborted) { setOperationError(operationRequestMessage(error)); setLoaded(false); setUsable(false); }
      }
    };
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [selected, active, refreshOperations]);
  useEffect(() => {
    const current = operations.find(row => row.operation_kind === 'PLAN');
    if (current) {
      setPhase(previous => previous === 'validating' || previous === 'applying' ? previous : current.status === 'RUNNING' ? 'planning' : 'idle');
      if (current.status === 'RUNNING') { setStarted(Date.parse(current.started_at)); setUsable(false); setPlanningError(null); }
      else if (current.status === 'READY' && current.result && reviewedId.current !== current.operation_id) {
        reviewedId.current = current.operation_id;
        setPlan({value: current.result as SyncPlan, received: current.finished_at!, operationId: current.operation_id}); setUsable(true); setPlanningError(null); setResult(previous=>previous && ['OUTCOME_UNCERTAIN','PARTIALLY_APPLIED'].includes(previous.state)?previous:null); setConfirmOpen(false);
      } else if (current.status === 'FAILED' || current.status === 'STALE') {
        setUsable(false); if(current.safe_error_code==='RESULT_EXPIRED'){setPlanningError(null);}else setPlanningError(new ManualSyncRequestError(current.status === 'STALE' ? 'Plan is no longer current. Build a new plan.' : operationReason(current.safe_error_code),current.safe_error_code??"OPERATION_FAILED"));
      }
    }
    if (!current && !busy.current) setPhase(previous => previous === 'planning' ? 'idle' : previous);
    const inspection = operations.find(row => row.operation_kind === 'DISCOVERY');
    if (!inspection && !discoveryBusy.current) setDiscovering(false);
    if (inspection) {
      if (inspectedId.current !== inspection.operation_id) { inspectedId.current = inspection.operation_id; setDiscoveryOpen(inspection.status==='RUNNING'||inspection.status==='FAILED'); }
      setDiscovering(inspection.status === 'RUNNING'); setDiscoveryStarted(Date.parse(inspection.started_at));
      if (inspection.status === 'SUCCEEDED' && inspection.result) { setDiscovery({value: inspection.result as DiscoveryResult, received: inspection.finished_at!}); setDiscoveryError(''); }
      if (inspection.status === 'FAILED') setDiscoveryError(inspection.safe_error_code==='RESULT_EXPIRED'?'':operationReason(inspection.safe_error_code));
    }
  }, [operations]);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    const element = dialog.current;
    if (confirmOpen && active && !element?.open) {
      element?.showModal();
      cancelButton.current?.focus();
    }
    if ((!confirmOpen || !active) && element?.open) element.close();
    if (!active) setConfirmOpen(false);
  }, [confirmOpen, active]);
  useEffect(() => {
    if (active && (result || planningError) && feedback.current?.offsetParent)
      { feedback.current.focus(); feedback.current.scrollIntoView({block:'nearest'}); }
  }, [result, planningError, active]);
  const closeDialog = () => {
    setConfirmOpen(false);
    dialog.current?.close();
    if (active) confirmButton.current?.focus();
  };
  const launch = async (kind: 'PLAN' | 'DISCOVERY') => {
    if (!canPlan || !detail.enabled || !loaded || operations.some(row => row.operation_kind === kind && row.status === 'RUNNING')) return;
    if (kind === 'PLAN') { if (busy.current) return; busy.current = true; setPhase('planning'); setStarted(Date.now()); setUsable(false); setPlanningError(null); setResult(previous=>previous && ['OUTCOME_UNCERTAIN','PARTIALLY_APPLIED'].includes(previous.state)?previous:null); setConfirmOpen(false); }
    else { if (discoveryBusy.current) return; discoveryBusy.current = true; setDiscovering(true); setDiscoveryOpen(true); setDiscoveryStarted(Date.now()); setDiscoveryError(''); }
    try {
      const operation = await startOperation(selected, kind, AbortSignal.timeout(15000));
      if (alive.current) { setOperations(rows => [...rows.filter(row => row.operation_kind !== kind), operation]); setRefreshOperations(value=>value+1); }
    } catch (error) {
      if (alive.current) { setOperationError(operationRequestMessage(error)); setLoaded(false); setRefreshOperations(value=>value+1); }
    } finally {
      if (kind === 'PLAN') busy.current = false; else discoveryBusy.current = false;
    }
  };
  const buildPlan = () => launch('PLAN');
  const discover = () => launch('DISCOVERY');
  const submit = async () => {
    if (
      !canApply || !active ||
      busy.current ||
      !confirmOpen ||
      !plan ||
      !usable || consumed || !historyLoaded ||
      !planOperation || planOperation.status !== 'READY' || planOperation.operation_id !== plan.operationId ||
      !plan.value.apply_allowed || !hasChanges(plan.value.items) ||
      !detail.enabled
    )
      return;
    const reviewed = plan.value;
    const reviewedOperationId = plan.operationId;
    setResult(null);
    busy.current = true;
    setPhase("validating");
    setStarted(Date.now());
    setUsable(false);
    let stage: "validating" | "applying" = "validating";
    try {
      const token = await prepareSync(
        selected,
        reviewed.digest,
        AbortSignal.timeout(330000),
        reviewedOperationId,
      );
      // Navigation to another source must not cause a later prepare response to submit apply.
      if (!alive.current) return;
      stage = "applying";
      setPhase("applying");
      const nextRunId=crypto.randomUUID();setRunId(nextRunId);
      const value = await applySync(
        selected,
        token,
        AbortSignal.timeout(330000),
        reviewedOperationId,
        nextRunId,
      );
      if (alive.current) setResult(applyOutcome(value, reviewed.digest));
    } catch (error) {
      if (alive.current) setResult(failedOutcome(error, stage));
    } finally {
      busy.current = false;
      if (alive.current) {
        setPhase("idle");
        runChanged.current?.();
        setRefreshOperations(value=>value+1);
        setConfirmOpen(false);
        dialog.current?.close();
      }
    }
  };
  const applying = phase === "validating" || phase === "applying";
  return (
    <section className="sync-workspace" aria-labelledby="sync-title">
      <h2 id="sync-title">{tr("Sync")}{" "}</h2>
      <p>{tr("Build plan → Review → Sync to NetBox → Result")}{" "}</p>
      <p className="muted">
        {detail.name} {tr("→ Site")}{" "}{detail.site_slug} / {detail.cluster_name}
      </p>
      {operationError && <p role="alert">{tr(operationError)} <button onClick={() => setRefreshOperations(value=>value+1)}>{tr("Reload operations")}{" "}</button></p>}
      {!loaded && !operationError && <p role="status">{tr("Loading operation state...")}{" "}</p>}
      {planOperation && <p className="muted">{tr("Started")}{" "}<Timestamp value={planOperation.started_at} />{planOperation.status === 'READY' && <> {tr("Built")}{" "}<Timestamp value={planOperation.finished_at} /></>}</p>}
      <div className="page-actions">
        <button
          className="primary"
          disabled={!canPlan || !loaded || phase !== "idle" || confirmOpen || !detail.enabled}
          onClick={buildPlan}
        >
          {plan ? tr("Rebuild plan") : tr("Build plan")}
        </button>
        <button
          disabled={
            !canPlan || !loaded || applying || discovering || confirmOpen || !detail.enabled
          }
          onClick={discover}
        >
          {tr("Run discovery")}{" "}</button>
      </div>
      {!detail.enabled && (
        <p className="sync-attention">
          {tr("Source disabled. Planning, discovery and manual sync are unavailable for this source.")}{" "}</p>
      )}
      {phase !== 'idle' && !applying && <OperationFeedback operation={phase==='planning'?tr('Build plan'):phase==='validating'?tr('Preparing / validating reviewed plan'):tr('Sync to NetBox')} phase={operationError?'uncertain':phase==='planning'&&planOperation?.status==='RUNNING'?'running':'sending'} started={started}/>}
      {(runId||acceptedRun)&&!result?.runId&&<p role="status">{acceptedRun&&<Badge value={runStatus(acceptedRun.status)}/>} {tr(acceptedRun?.status==='RUNNING'?'Run accepted; execution is in progress.':acceptedRun?'Stored run result is available.':'Waiting for durable acceptance; do not resubmit.')} <Link to={runPath(acceptedRun?.run_id??runId)}>{tr('Open run')}</Link></p>}
      {!historyLoaded&&<p role={historyError?'alert':'status'}>{tr(historyError?'Run history unavailable. Confirmation is disabled until it can be checked.':'Loading run history…')}</p>}
      {consumed&&<p className="sync-attention">{tr('This plan has been used. Inspect the run and build a fresh plan from current NetBox state before confirming further changes.')}</p>}
      <div ref={feedback} tabIndex={-1}>
        {expiredPlan&&<p className="sync-attention" role="status">{tr('The saved plan has expired. This is not a synchronization failure.')} {planOperation?.finished_at&&<Timestamp value={planOperation.finished_at}/>}<br/>{canPlan?tr('Build a new plan when you want to sync manually.'):tr('An Operator or Admin can build a new plan.')}</p>}
        {planningError && (
          <div className={historicalPlan?"sync-attention":"source-error"} role={historicalPlan?"status":"alert"}>
            {historicalPlan&&<p>{tr("Earlier planning attempt; a newer run is shown in history.")}</p>}
            {planOperation?.finished_at&&<Timestamp value={planOperation.finished_at}/>}
            <strong>{planOperation?.status === 'STALE' ? tr("Plan is no longer current.") : tr("Plan could not be built.")}</strong>
            <p>{tr(planningError.message)}</p>
            <details>
              <summary>{tr("Technical details")}{" "}</summary>
              <code>{planningError.code}</code>
              <p>{publicError(planningError.code).stage} · {planOperation?.operation_id}</p>
              <p>{publicError(planningError.code).action}</p>
            </details>
            <p>
              {tr("This was a read-only planning request. Build a new plan to try planning again.")}{" "}</p>
          </div>
        )}
        {result && (
          <section
            className={
              "sync-result " +
              (["PARTIALLY_APPLIED", "OUTCOME_UNCERTAIN"].includes(result.state)
                ? "sync-attention"
                : "source-panel")
            }
            role={result.state === "SUCCEEDED" ? "status" : "alert"}
            aria-label={tr("Sync result")}
            data-state={result.state}
          >
            <h3>
              <Badge value={result.status} />
            </h3>
            <p>{result.state === 'STALE' ? staleReason(result.reason) : tr(result.message)}</p>
            {result.state === 'STALE' && <p>{tr('Rejected before write. Build and review a new plan.')}</p>}
            {["FAILED", "OUTCOME_UNCERTAIN", "PARTIALLY_APPLIED"].includes(
              result.state,
            ) && (
              <p>
                {tr("No automatic retry. Review recorded history and source diagnostics before continuing.")}{" "}</p>
            )}
            <div className="page-actions">
              {result.runId && (
                <Link className="button" to={runPath(result.runId)}>
                  {tr("Open run")}{" "}</Link>
              )}
              <Link to={sourcePath(selected) + "/runs"}>
                {tr("Source run history")}{" "}</Link>
              <Link to={sourcePath(selected) + "/diagnostics"}>
                {tr("Source diagnostics")}{" "}</Link>
            </div>
            {result.code && (
              <details>
                <summary>{tr("Technical details")}{" "}</summary>
                <code>{result.code}</code><p>{result.reason}</p><p>{result.categories?.join(" · ")}</p><p>{result.eventId}</p>
              </details>
            )}
          </section>
        )}
      </div>
      {!plan && phase !== "planning" && !planningError && (
        <div className="source-panel">
          <h3>{tr("No plan yet")}{" "}</h3>
          <p>
            {tr("Build a plan to review the proposed changes. Discovery is an optional, separate inspection.")}{" "}</p>
        </div>
      )}
      {usable && plan?.value.apply_allowed && !consumed && historyLoaded && phase === "idle" && (
        <p role="status">{tr("Plan ready for review.")}{" "}</p>
      )}
      {plan && (
        <PlanReview
          key={plan.received}
          plan={plan.value}
          received={plan.received}
          previous={!usable || consumed}
          toolbar={<button
            ref={confirmButton}
            className="primary"
            disabled={
              !canApply || phase !== "idle" ||
              !usable || consumed || !historyLoaded ||
              !plan.value.apply_allowed || !hasChanges(plan.value.items) ||
              !detail.enabled
            }
            onClick={() => { if (canApply) setConfirmOpen(true); }}
          >
            {tr("Review and confirm sync")}{" "}</button>}
        />
      )}
      {plan && (
        <div className="sync-action-bar">
          <p>
            {tr("Missing objects are retained in NetBox. No deletes. Only the reviewed plan is submitted.")}{" "}</p>
        </div>
      )}
      <details
        className="source-panel discovery-tool"
        open={discoveryOpen}
        onToggle={(e) => setDiscoveryOpen(e.currentTarget.open)}
      >
        <summary>{tr("Discovery · optional read-only inspection")}{" "}</summary>
        <p>
          {tr("Inspect discovered objects and how they match NetBox. No NetBox changes are made.")}{" "}</p>
        {discovering && <OperationFeedback operation={tr('Run discovery')} phase={operationError?'uncertain':operations.some(row=>row.operation_kind==='DISCOVERY'&&row.status==='RUNNING')?'running':'sending'} started={discoveryStarted}/>}
        {expiredDiscovery&&<p className="sync-attention" role="status">{tr('The discovery result has expired. Run history is unchanged.')} {expiredDiscovery.finished_at&&<Timestamp value={expiredDiscovery.finished_at}/>}<br/>{canPlan?tr('Run discovery to refresh this result.'):tr('An Operator or Admin can refresh this result.')}</p>}
        {discoveryError && (
          <p role={historicalDiscovery?"status":"alert"} className={historicalDiscovery?"sync-attention":"source-error"}>
            {historicalDiscovery&&<>{tr("Earlier discovery attempt; a newer run is shown in history.")}<br/></>}{inspectionOperation?.finished_at&&<Timestamp value={inspectionOperation.finished_at}/>}<br/>
            {tr(discoveryError)}<br/><code>{operations.find(row=>row.operation_kind==='DISCOVERY')?.safe_error_code}</code><br/>
            {operations.find(row=>row.operation_kind==='DISCOVERY')?.operation_id}
          </p>
        )}
        {discovery && (
          <DiscoveryReview
            result={discovery.value}
            received={discovery.received}
            previous={discovering}
          />
        )}
        {!discovery && !discovering && (
          <p>
            {tr("Run discovery to inspect matching and classification evidence independently of planning.")}{" "}</p>
        )}
      </details>
      <dialog
        ref={dialog}
        className="sync-dialog"
        aria-labelledby="confirm-title"
        aria-describedby="confirm-description"
        onKeyDown={(event) => {
          if (event.key !== "Tab") return;
          const controls = Array.from(
            event.currentTarget.querySelectorAll<HTMLButtonElement>(
              "button:not(:disabled)",
            ),
          );
          const first = controls[0],
            last = controls.at(-1);
          if (!first) {
            event.preventDefault();
            return;
          }
          if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last?.focus();
          } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
          }
        }}
        onCancel={(e) => {
          e.preventDefault();
          if (!applying) closeDialog();
        }}
      >
        <h2 id="confirm-title">{tr("Sync changes to NetBox")}{" "}</h2>
        <p id="confirm-description">
          {tr("Confirm the complete reviewed plan for this source.")}{" "}</p>
        {plan && (
          <>
            <dl className="source-facts">
              <div>
                <dt>{tr("Source")}{" "}</dt>
                <dd>
                  {detail.name} <code>{selected}</code>
                </dd>
              </div>
              <div>
                <dt>{tr("Target")}{" "}</dt>
                <dd>
                  {detail.site_slug} / {detail.cluster_name}
                </dd>
              </div>
              <div>
                <dt>{tr("Plan received")}{" "}</dt>
                <dd>
                  <Timestamp value={plan.received} />
                </dd>
              </div>
            </dl>
            <PlanSummary plan={plan.value} />
          </>
        )}
        <p>
          {tr("Review rows are isolated, not automatically adopted or applied as normal updates. The plan is checked again before sync; changes to the source or NetBox can invalidate it.")}{" "}</p>
        <ul>
          <li>{tr("Missing objects are retained. No deletes.")}{" "}</li>
          <li>{tr("Only this reviewed plan is submitted.")}{" "}</li>
          <li>{tr("No automatic retry after an uncertain outcome.")}{" "}</li>
        </ul>
        {applying && (
          <div className="sync-pending">
            <OperationFeedback operation={phase==='validating'?tr('Preparing / validating reviewed plan'):tr('Sync to NetBox')} phase="sending" started={started}/>
            <p>
              {tr("Leaving a page does not cancel work already accepted by the backend.")}{" "}</p>
          </div>
        )}
        <div className="page-actions">
          <button ref={cancelButton} disabled={applying} onClick={closeDialog}>
            {tr("Cancel")}{" "}</button>
          <button className="primary" disabled={!canApply || applying} onClick={submit}>
            {tr("Sync to NetBox")}{" "}</button>
        </div>
      </dialog>
    </section>
  );
}
