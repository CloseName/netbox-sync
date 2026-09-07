import { isSource } from './sources.ts';
import type { Source } from './sources';

export class SourceIdReservedError extends Error {
  constructor() { super('This Source ID was previously used and is reserved by a removed source.'); }
}

export interface ConnectionInput {
  source_type: 'proxmox' | 'esxi'; address: string; verify_ssl: boolean;
  username: string; secret: string; token_id?: string;
}

export interface RegistrationInput {
  onboarding_token: string; source_type: 'proxmox' | 'esxi'; address: string; verify_ssl: boolean;
  source_instance: string; name: string; sync_interval_seconds: number;
  site_slug: string; cluster_name: string; platform_slug: string; device_role_slug: string;
  device_type_slug: string; cluster_type_slug: string; confirm_sync_disabled: true;
}

async function post(path: string, payload: ConnectionInput | RegistrationInput | { onboarding_token: string }): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(path, { method: 'POST', cache: 'no-store',
      headers: { 'Content-Type': 'application/json', 'X-NetBox-Sync-CSRF': 'same-origin' },
      body: JSON.stringify(payload), signal: AbortSignal.timeout(20000) });
  } catch { throw new Error('Request failed or timed out. Registration outcome may require operator review.'); }
  if (!response.ok) {
    if (response.status === 409) {
      let code='';
      try { const value=await response.json(); if(typeof value?.error?.code==='string') code=value.error.code; } catch { /* safe fallback */ }
      if (code==='SOURCE_ID_RESERVED') throw new SourceIdReservedError();
      throw new Error('Source already exists or onboarding expired. Review before retrying.');
    }
    if (response.status === 403) throw new Error('Write access rejected. Check the configured tunnel origin.');
    throw new Error('Operation failed. Check configuration or ask the operator; credentials are not displayed.');
  }
  try { return await response.json(); }
  catch { throw new Error('Unsupported server response.'); }
}

export async function cancelOnboarding(token: string): Promise<void> {
  const result = await post('/api/v1/sources/cancel-onboarding', { onboarding_token: token });
  if (typeof result !== 'object' || result === null || !('status' in result) || result.status !== 'cancelled') {
    throw new Error('Unsupported cancellation response.');
  }
}

export async function testConnection(input: ConnectionInput): Promise<string> {
  const result = await post('/api/v1/sources/test-connection', input);
  if (typeof result !== 'object' || result === null || !('status' in result) || result.status !== 'success'
    || !('onboarding_token' in result) || typeof result.onboarding_token !== 'string'
    || !/^[A-Za-z0-9_-]{20,128}$/.test(result.onboarding_token)) throw new Error('Unsupported server response.');
  return result.onboarding_token;
}

export async function registerSource(input: RegistrationInput): Promise<Source> {
  if (input.confirm_sync_disabled !== true) throw new Error('Explicit confirmation is required.');
  const result = await post('/api/v1/sources', input);
  if (!isSource(result) || result.source_instance !== input.source_instance || result.sync_enabled
    || !result.enabled || result.legacy_identity_owner) throw new Error('Unexpected registration result; ask the operator.');
  return result;
}
