export interface SourceLifecycle {
  source_instance: string; display_name: string; removed_at: string | null;
  revision: string | null; credential_state: 'RETAINED_BY_REQUEST' | 'REMOVED' | 'RETAINED_SHARED_OR_LEGACY' | 'CLEANUP_FAILED' | null;
}
const messages: Record<string,string> = {
  SOURCE_OPERATION_ACTIVE: 'Wait for active Plan or Discovery to finish.',
  SOURCE_APPLY_ACTIVE: 'Wait for synchronization to finish.',
  SOURCE_APPLY_UNCONFIRMED: 'A synchronization outcome requires reconciliation. Removal is blocked.',
  SOURCE_LIFECYCLE_CONFLICT: 'Source changed. Reload its current state before confirming again.',
  SOURCE_CONFIRMATION_INVALID: 'Enter the exact Source ID.',
  SOURCE_ALREADY_REMOVED: 'Source is already removed. Reload its state.',
};
export async function sourceLifecycle(source: string, signal: AbortSignal, removal?: {revision: string; confirmed_source: string; remove_credentials: boolean}): Promise<SourceLifecycle> {
  const response = await fetch(`/api/v1/sources/${encodeURIComponent(source)}/${removal ? 'remove' : 'lifecycle'}`, {
    method: removal ? 'POST':'GET', signal, credentials:'same-origin', cache:'no-store',
    ...(removal ? {headers:{'Content-Type':'application/json','X-NetBox-Sync-CSRF':'same-origin'},body:JSON.stringify(removal)}:{}),
  });
  const value = await response.json();
  if (!response.ok) throw new Error(Object.hasOwn(messages, value?.error?.code) ? messages[value.error.code] : 'Lifecycle state is unavailable. Reload to check whether removal completed.');
  if (!value || value.source_instance !== source || typeof value.display_name !== 'string'
      || !(value.removed_at === null || (typeof value.removed_at === 'string' && Number.isFinite(Date.parse(value.removed_at))))
      || !(value.revision === null || (typeof value.revision === 'string' && /^[a-f0-9]{64}$/.test(value.revision)))
      || ![null,'RETAINED_BY_REQUEST','REMOVED','RETAINED_SHARED_OR_LEGACY','CLEANUP_FAILED'].includes(value.credential_state)
      || (value.removed_at === null ? value.revision === null : value.revision !== null)) throw new Error('Lifecycle state is invalid.');
  return value;
}
