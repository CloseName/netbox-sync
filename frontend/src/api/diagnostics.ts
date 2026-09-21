export type DiagnosticStatus = 'HEALTHY' | 'DEGRADED' | 'UNHEALTHY' | 'UNAVAILABLE' | 'UNKNOWN';
export type DiagnosticCode = 'REGISTRY_UNAVAILABLE' | 'RUN_HISTORY_UNAVAILABLE'
  | 'DISCOVERY_WORKER_UNAVAILABLE' | 'APPLY_WORKER_UNAVAILABLE'
  | 'SCHEDULED_ACTIVITY_DELAYED' | 'STALE_RUNNING';
export interface DiagnosticComponent { status: DiagnosticStatus; checked_at: string; safe_code: DiagnosticCode | null; safe_message: string | null; last_seen_at: string | null; last_success_at: string | null; next_expected_at: string | null; }
export interface DiagnosticRun { run_id: string; trigger: 'manual' | 'scheduled'; status: string; started_at: string; finished_at: string | null; }
export interface DiagnosticWarning { warning_code: 'STALE_RUNNING' | 'SCHEDULED_ACTIVITY_DELAYED'; safe_message: string; source_instance: string | null; source_type: 'proxmox' | 'esxi' | null; trigger: 'manual' | 'scheduled' | null; run_id: string | null; started_at: string | null; age_seconds: number | null; }
export interface SourceDiagnostic { plan_blocked?: boolean; plan_checked_at?: string|null; outcome_unconfirmed?: boolean; operation_evidence_available?: boolean; source_instance: string; source_type: 'proxmox' | 'esxi'; enabled: boolean; sync_enabled: boolean; sync_interval_seconds: number; status: DiagnosticStatus; latest_run: DiagnosticRun | null; latest_success_at: string | null; latest_scheduled_run: DiagnosticRun | null; latest_manual_run: DiagnosticRun | null; scheduler_state: 'DISABLED' | 'WAITING' | 'DUE' | 'RUNNING' | 'DELAYED'; last_scheduled_run_at: string | null; next_expected_at: string | null; warning_count: number; warnings: ('STALE_RUNNING' | 'SCHEDULED_ACTIVITY_DELAYED')[]; }
export interface Diagnostics { overall_status: 'HEALTHY' | 'DEGRADED' | 'UNHEALTHY'; generated_at: string; components: Record<'api' | 'registry' | 'run_history' | 'discovery_worker' | 'apply_worker' | 'scheduler', DiagnosticComponent>; sources: SourceDiagnostic[]; stale_runs: DiagnosticWarning[]; warnings: DiagnosticWarning[]; }

const record = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value);
const timestamp = (value: unknown) => typeof value === 'string' && !Number.isNaN(Date.parse(value));
const nullableTime = (value: unknown) => value === null || timestamp(value);
const statuses = new Set(['HEALTHY', 'DEGRADED', 'UNHEALTHY', 'UNAVAILABLE', 'UNKNOWN']);
const componentStatuses = new Set(['HEALTHY', 'DEGRADED', 'UNAVAILABLE', 'UNKNOWN']);
const runStatuses = new Set(['RUNNING', 'SUCCEEDED', 'FAILED_BEFORE_WRITE', 'PARTIALLY_APPLIED', 'OUTCOME_UNCERTAIN', 'BLOCKED', 'LOCKED', 'FAILED']);
const codes = new Set(['REGISTRY_UNAVAILABLE', 'RUN_HISTORY_UNAVAILABLE', 'DISCOVERY_WORKER_UNAVAILABLE', 'APPLY_WORKER_UNAVAILABLE', 'SCHEDULED_ACTIVITY_DELAYED', 'STALE_RUNNING']);
const warnings = new Set(['STALE_RUNNING', 'SCHEDULED_ACTIVITY_DELAYED']);
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const nullableCode = (value: unknown) => value === null || (typeof value === 'string' && codes.has(value));

const isComponent = (value: unknown): value is DiagnosticComponent => record(value)
  && typeof value.status === 'string' && componentStatuses.has(value.status) && timestamp(value.checked_at)
  && nullableCode(value.safe_code) && (value.safe_message === null || typeof value.safe_message === 'string')
  && nullableTime(value.last_seen_at) && nullableTime(value.last_success_at) && nullableTime(value.next_expected_at);
const isRun = (value: unknown): value is DiagnosticRun => record(value)
  && typeof value.run_id === 'string' && uuid.test(value.run_id)
  && (value.trigger === 'manual' || value.trigger === 'scheduled')
  && typeof value.status === 'string' && runStatuses.has(value.status)
  && timestamp(value.started_at) && nullableTime(value.finished_at);
const isWarning = (value: unknown): value is DiagnosticWarning => record(value)
  && typeof value.warning_code === 'string' && warnings.has(value.warning_code)
  && typeof value.safe_message === 'string'
  && (value.source_instance === null || typeof value.source_instance === 'string')
  && (value.source_type === null || value.source_type === 'proxmox' || value.source_type === 'esxi')
  && (value.trigger === null || value.trigger === 'manual' || value.trigger === 'scheduled')
  && (value.run_id === null || (typeof value.run_id === 'string' && uuid.test(value.run_id)))
  && nullableTime(value.started_at)
  && (value.age_seconds === null || (Number.isSafeInteger(value.age_seconds) && Number(value.age_seconds) >= 0));
const isSource = (value: unknown): value is SourceDiagnostic => record(value)
  && ['plan_blocked','outcome_unconfirmed','operation_evidence_available'].every(k=>value[k]===undefined||typeof value[k]==='boolean')
  && (value.plan_checked_at===undefined||nullableTime(value.plan_checked_at))
  && typeof value.source_instance === 'string' && (value.source_type === 'proxmox' || value.source_type === 'esxi')
  && typeof value.enabled === 'boolean' && typeof value.sync_enabled === 'boolean'
  && Number.isSafeInteger(value.sync_interval_seconds) && Number(value.sync_interval_seconds) > 0
  && typeof value.status === 'string' && statuses.has(value.status)
  && (value.latest_run === null || isRun(value.latest_run)) && nullableTime(value.latest_success_at)
  && (value.latest_scheduled_run === null || isRun(value.latest_scheduled_run))
  && (value.latest_manual_run === null || isRun(value.latest_manual_run))
  && typeof value.scheduler_state === 'string' && ['DISABLED', 'WAITING', 'DUE', 'RUNNING', 'DELAYED'].includes(value.scheduler_state)
  && nullableTime(value.last_scheduled_run_at) && nullableTime(value.next_expected_at)
  && Number.isSafeInteger(value.warning_count) && Number(value.warning_count) >= 0
  && Array.isArray(value.warnings) && value.warnings.every((item) => typeof item === 'string' && warnings.has(item));

export function isDiagnostics(value: unknown): value is Diagnostics {
  if (!record(value) || typeof value.overall_status !== 'string'
    || !['HEALTHY', 'DEGRADED', 'UNHEALTHY'].includes(value.overall_status)
    || !timestamp(value.generated_at) || !record(value.components)) return false;
  const entries = value.components;
  const componentNames = ['api', 'registry', 'run_history', 'discovery_worker', 'apply_worker', 'scheduler'];
  return componentNames.every((name) => isComponent(entries[name]))
    && Array.isArray(value.sources) && value.sources.every(isSource)
    && Array.isArray(value.stale_runs) && value.stale_runs.every(isWarning)
    && Array.isArray(value.warnings) && value.warnings.every(isWarning);
}

export async function fetchDiagnostics(signal: AbortSignal): Promise<Diagnostics> {
  let response: Response;
  try { response = await fetch('/api/v1/diagnostics', { signal, cache: 'no-store' }); }
  catch { throw new Error('Diagnostics unavailable.'); }
  if (!response.ok) throw new Error('Diagnostics unavailable.');
  let value: unknown;
  try { value = await response.json(); } catch { throw new Error('Diagnostics unavailable.'); }
  if (!isDiagnostics(value)) throw new Error('Diagnostics unavailable.');
  return value;
}
