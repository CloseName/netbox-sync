import { isSource } from './sources.ts';
import type { Source } from './sources';

export class SourceIdReservedError extends Error {
  constructor() { super('This Source ID was previously used and is reserved by a removed source.'); }
}

export const connectionMessages = {
  SOURCE_ADDRESS_INVALID: ['Use a bare hostname or IPv4 address, without a scheme, path or port.', 'Введите имя узла или IPv4 без схемы, пути и порта.'],
  SOURCE_DNS_FAILED: ['The source hostname could not be resolved. Check its spelling and ask the deployment operator to verify DNS.', 'Не удалось разрешить имя источника. Проверьте написание; оператор установки должен проверить DNS.'],
  SOURCE_CONNECTION_FAILED: ['Could not reach the source. Check hostname, DNS, routing and HTTPS service.', 'Не удалось подключиться к источнику. Проверьте имя, DNS, маршрутизацию и службу HTTPS.'],
  SOURCE_TIMEOUT: ['The source connection timed out. Check reachability and retry.', 'Источник не ответил вовремя. Проверьте доступность и повторите проверку.'],
  SOURCE_TLS_FAILED: ['TLS verification failed. Check certificate, hostname and trusted CA.', 'Ошибка проверки TLS. Проверьте сертификат, имя узла и доверенный центр сертификации.'],
  SOURCE_AUTH_FAILED: ['Authentication was rejected. Check username and password or token.', 'Источник отклонил вход. Проверьте пользователя и пароль или API-токен.'],
  SOURCE_DESTINATION_DENIED: ['The destination is blocked by policy. Ask the operator to review the allowlist.', 'Адрес запрещён политикой доступа. Попросите оператора проверить разрешённые назначения.'],
} as const;
export class SourceConnectionError extends Error {
  readonly code: keyof typeof connectionMessages;
  constructor(code: keyof typeof connectionMessages) { super(connectionMessages[code][0]); this.code = code; }
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
    if (path === '/api/v1/sources/test-connection') {
      let code: unknown;
      try { code = (await response.clone().json())?.error?.code; } catch { /* safe fallback */ }
      if (typeof code === 'string' && Object.hasOwn(connectionMessages, code)) {
        throw new SourceConnectionError(code as keyof typeof connectionMessages);
      }
    }
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
