import { validPlan, type SyncPlan } from './sync.ts';
import { validDiscovery, type DiscoveryResult } from './discovery.ts';
export type OperationFailure = 'TIMEOUT' | 'TRANSPORT' | 'ACCESS_DENIED' | 'HTTP_ERROR' | 'INVALID_RESPONSE' | 'UNKNOWN';
const requestMessages: Record<OperationFailure,string> = {
 TIMEOUT:'The state request timed out. Reload to check the operation.',
 TRANSPORT:'No response received. Check connectivity and reload the operation state.',
 ACCESS_DENIED:'Access to operation state was denied. Check access before retrying.',
 HTTP_ERROR:'The server could not return operation state. Reload or ask the operator.',
 INVALID_RESPONSE:'The operation response could not be validated. Reload its state.',
 UNKNOWN:'Operation state is unavailable. Reload to check current state.',
};
export class OperationRequestError extends Error {
 readonly reason:OperationFailure;
 constructor(reason:OperationFailure){super(requestMessages[reason]);this.reason=reason;}
}
export const operationRequestMessage=(error:unknown)=>requestMessages[error instanceof OperationRequestError?error.reason:'UNKNOWN'];
export type OperationKind = 'PLAN' | 'DISCOVERY';
export interface SourceOperation {
  operation_id: string; source_instance: string; operation_kind: OperationKind;
  status: 'RUNNING' | 'READY' | 'SUCCEEDED' | 'FAILED' | 'STALE';
  started_at: string; updated_at: string; finished_at: string | null;
  safe_error_code: string | null; result: SyncPlan | DiscoveryResult | null;
}
const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
export function parseOperation(v: unknown, source: string): SourceOperation {
  if (!record(v) || v.source_instance !== source || typeof v.operation_id !== 'string'
      || !/^[a-f0-9-]{36}$/i.test(v.operation_id) || !['PLAN','DISCOVERY'].includes(String(v.operation_kind))
      || !['RUNNING','READY','SUCCEEDED','FAILED','STALE'].includes(String(v.status))
      || typeof v.started_at !== 'string' || !Number.isFinite(Date.parse(v.started_at))
      || typeof v.updated_at !== 'string' || !Number.isFinite(Date.parse(v.updated_at))
      || !(v.finished_at === null || (typeof v.finished_at === 'string' && Number.isFinite(Date.parse(v.finished_at))))
      || !(v.safe_error_code === null || typeof v.safe_error_code === 'string')) throw new OperationRequestError('INVALID_RESPONSE');
  const ready = v.operation_kind === 'PLAN' ? v.status === 'READY' : v.status === 'SUCCEEDED';
  if ((v.operation_kind === 'PLAN' && v.status === 'SUCCEEDED') || (v.operation_kind === 'DISCOVERY' && ['READY','STALE'].includes(String(v.status)))
      || (ready ? !(v.operation_kind === 'PLAN' ? validPlan(v.result, source) : validDiscovery(v.result, source)) : v.result !== null)) throw new OperationRequestError('INVALID_RESPONSE');
  return v as unknown as SourceOperation;
}
const messages: Record<string,string> = {
  OPERATION_INTERRUPTED: 'The operation did not complete. Start a new operation when ready.',
  RESULT_EXPIRED: 'This result is no longer current. Build a new result.',
  SOURCE_DISABLED: 'Source is disabled.',
  CREDENTIAL_UNAVAILABLE: 'Source credentials are unavailable.',
  REGISTRY_UNAVAILABLE: 'Source registry is unavailable.',
  NETBOX_UNAVAILABLE: 'NetBox comparison is unavailable.',
  DISCOVERY_TIMEOUT: 'The operation timed out.',
};
export const operationReason = (code: string | null) => code && Object.hasOwn(messages, code) ? messages[code] : 'The operation could not complete. No automatic retry was performed.';
async function request(source: string, signal: AbortSignal, kind?: OperationKind) {
  let response:Response;
  try { response = await fetch(`/api/v1/sources/${encodeURIComponent(source)}/operations${kind ? '/' + kind.toLowerCase() : ''}`, {
    method: kind ? 'POST' : 'GET', signal, credentials: 'same-origin', cache: 'no-store',
    ...(kind ? {headers: {'Content-Type':'application/json','X-NetBox-Sync-CSRF':'same-origin'}, body:'{}'} : {}),
  });
  } catch(error) {
    throw new OperationRequestError(signal.aborted&&signal.reason?.name==='TimeoutError'?'TIMEOUT':error instanceof TypeError?'TRANSPORT':'UNKNOWN');
  }
  if (!response.ok) throw new OperationRequestError(response.status===401||response.status===403?'ACCESS_DENIED':'HTTP_ERROR');
  try {return await response.json() as unknown;} catch(error) {throw new OperationRequestError(signal.aborted&&signal.reason?.name==='TimeoutError'?'TIMEOUT':error instanceof TypeError?'TRANSPORT':'INVALID_RESPONSE');}
}
export async function fetchOperations(source: string, signal: AbortSignal) {
  const value = await request(source, signal);
  if (!record(value) || !Array.isArray(value.operations) || value.operations.length > 2) throw new OperationRequestError('INVALID_RESPONSE');
  const rows = value.operations.map(v => parseOperation(v,source));
  if (new Set(rows.map(v=>v.operation_kind)).size !== rows.length) throw new OperationRequestError('INVALID_RESPONSE');
  return rows;
}
export async function startOperation(source: string, kind: OperationKind, signal: AbortSignal) {
  const result = parseOperation(await request(source, signal, kind), source);
  if (result.operation_kind !== kind) throw new OperationRequestError('INVALID_RESPONSE');
  return result;
}
