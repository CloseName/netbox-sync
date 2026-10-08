export interface CalendarSchedule {mode:'daily'|'weekly'|'monthly';time:string;timezone:'Europe/Moscow';day?:number;}
export type SchedulerState = 'DISABLED' | 'WAITING' | 'DUE' | 'RUNNING' | 'DELAYED';
export interface Schedule { server_time?:string; sync_calendar?:CalendarSchedule|null; source_instance: string; sync_enabled: boolean; sync_interval_seconds: number; scheduler_state: SchedulerState; last_scheduled_run_at: string | null; next_expected_at: string | null; }
export interface ScheduleUpdate { sync_calendar?:CalendarSchedule|null;expected_sync_calendar?:CalendarSchedule|null; sync_enabled: boolean; sync_interval_seconds: number; expected_sync_enabled: boolean; expected_sync_interval_seconds: number; }

const record = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value);
const time = (value: unknown) => value === null || (typeof value === 'string' && !Number.isNaN(Date.parse(value)));
const calendar = (value:unknown) => value == null || (record(value) && ['daily','weekly','monthly'].includes(String(value.mode)) && value.timezone==='Europe/Moscow' && typeof value.time==='string' && /^(?:[01][0-9]|2[0-3]):[0-5][0-9]$/.test(value.time) && (value.mode==='daily' ? value.day===undefined : Number.isInteger(value.day) && Number(value.day)>=1 && Number(value.day)<=(value.mode==='weekly'?7:31)));
export const isSchedule = (value: unknown): value is Schedule => record(value)
  && typeof value.source_instance === 'string' && typeof value.sync_enabled === 'boolean'
  && Number.isSafeInteger(value.sync_interval_seconds) && Number(value.sync_interval_seconds) > 0
  && typeof value.scheduler_state === 'string' && ['DISABLED', 'WAITING', 'DUE', 'RUNNING', 'DELAYED'].includes(value.scheduler_state)
  && calendar(value.sync_calendar) && (value.server_time===undefined || (typeof value.server_time==='string' && time(value.server_time)))
  && time(value.last_scheduled_run_at) && time(value.next_expected_at);

const safeErrors: Record<string, string> = {
  SCHEDULE_INVALID: 'Choose an interval between 60 seconds and 24 hours.',
  SCHEDULE_CONFLICT: 'This schedule changed since you opened it. Reload the latest value before saving again.',
  SOURCE_NOT_FOUND: 'Source not found. Refresh the source list.',
  CONTROL_WORKER_UNAVAILABLE: 'Scheduling control is unavailable.',
  CONTROL_REQUEST_FAILED: 'Scheduling update failed.',
  SCHEDULE_UNAVAILABLE: 'Scheduling state is unavailable.',
};
export class ScheduleRequestError extends Error {
  code: string;
  constructor(code: string, message: string) { super(message); this.code = code; }
}
async function parse(response: Response, instance: string): Promise<Schedule> {
  if (!response.ok) {
    let value: unknown; try { value = await response.json(); } catch { throw new Error('Scheduling request failed.'); }
    const code = record(value) && record(value.error) && typeof value.error.code === 'string' ? value.error.code : '';
    throw new ScheduleRequestError(code, safeErrors[code] ?? 'Scheduling request failed.');
  }
  let value: unknown; try { value = await response.json(); } catch { throw new Error('Scheduling request failed.'); }
  if (!isSchedule(value) || value.source_instance !== instance) throw new Error('Scheduling request failed.');
  return value;
}
export async function fetchSchedule(instance: string, signal: AbortSignal) {
  let response: Response; try { response = await fetch(`/api/v1/sources/${encodeURIComponent(instance)}/schedule`, { signal, cache: 'no-store' }); } catch { throw new Error('Scheduling request failed.'); }
  return parse(response, instance);
}
export async function updateSchedule(instance: string, update: ScheduleUpdate, signal: AbortSignal) {
  let response: Response; try { response = await fetch(`/api/v1/sources/${encodeURIComponent(instance)}/schedule`, { method: 'PATCH', headers: { 'Content-Type': 'application/json', 'X-NetBox-Sync-CSRF': 'same-origin' }, credentials: 'same-origin', cache: 'no-store', signal, body: JSON.stringify(update) }); } catch { throw new Error('Scheduling request failed.'); }
  return parse(response, instance);
}
