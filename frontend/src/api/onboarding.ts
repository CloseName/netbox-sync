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
  SOURCE_DESTINATION_DENIED: ['The destination is blocked by policy. Review the separate destination permission below.', 'Адрес запрещён политикой доступа. Проверьте отдельное разрешение назначения ниже.'],
} as const;
export class SourceConnectionError extends Error {
  readonly code: keyof typeof connectionMessages;
  constructor(code: keyof typeof connectionMessages) { super(connectionMessages[code][0]); this.code = code; }
}

export interface ConnectionInput {
  source_type: 'proxmox' | 'esxi'; address: string; verify_ssl: boolean;
  username: string; secret: string; token_id?: string; preview?: boolean;
}

export interface RegistrationInput {
  onboarding_token: string; source_type: 'proxmox' | 'esxi'; address: string; verify_ssl: boolean;
  source_instance: string; name: string; sync_interval_seconds: number;
  site_slug: string; cluster_name: string; platform_slug: string; device_role_slug: string;
  device_type_slug: string; cluster_type_slug: string; confirm_sync_disabled: true;
  references?: Record<string, CatalogItem>; host_types?: Record<string, CatalogItem>;
}

async function post(path: string, payload: ConnectionInput | RegistrationInput | { onboarding_token: string }): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(path, { method: 'POST', cache: 'no-store',
      headers: { 'Content-Type': 'application/json', 'X-NetBox-Sync-CSRF': 'same-origin' },
      body: JSON.stringify(payload), signal: AbortSignal.timeout(path==='/api/v1/sources'?40000:20000) });
  } catch { throw new Error('Request failed or timed out. Registration outcome may require operator review.'); }
  if (!response.ok) {
    if (path === '/api/v1/sources/test-connection') {
      let code: unknown;
      try { code = (await response.clone().json())?.error?.code; } catch { /* safe fallback */ }
      if (typeof code === 'string' && Object.hasOwn(connectionMessages, code)) {
        throw new SourceConnectionError(code as keyof typeof connectionMessages);
      }
    }
    if(path==='/api/v1/sources'){
      let code='';try{code=(await response.clone().json()).error.code;}catch{}
      if(code.startsWith('CATALOG_'))throw new CatalogFailure(code);
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

export interface CatalogItem { id:number; name:string; slug:string; fingerprint:string;
 manufacturer:{id:number;name:string}|null; type:{id:number;name:string}|null;
 scope_type:string|null;scope_id:number|null;site:{id:number;name:string}|null;scope:{id:number;name:string}|null; }
export interface HostPreview {id:string;name:string|null;manufacturer:string|null;model:string|null;version:string|null;cpu:string|null;memory_bytes:number;}
export interface SourcePreview {provider:'esxi'|'proxmox';name:string|null;cluster:string|null;hosts:HostPreview[];}
export interface CatalogPage {items:CatalogItem[];count:number;offset:number;more:boolean;url:string;}
const catalogCodes=['CATALOG_CHANGED','CATALOG_SELECTION_REQUIRED','CATALOG_HOST_MAPPING_REQUIRED','CATALOG_CLUSTER_SCOPE_MISMATCH','CATALOG_CLUSTER_AMBIGUOUS','CATALOG_PERMISSION_DENIED','CATALOG_AUTH_FAILED','CATALOG_TLS_FAILED','CATALOG_NETWORK_UNREACHABLE','CATALOG_RESPONSE_INVALID','CATALOG_UNAVAILABLE'];
export class CatalogFailure extends Error {readonly code:string;constructor(code:string){const safe=catalogCodes.includes(code)?code:'CATALOG_UNAVAILABLE';super(safe);this.code=safe;}}
let activeCatalog=0;const catalogQueue:Array<()=>void>=[];
export async function catalog(kind:string,search:string,offset:number,signal:AbortSignal):Promise<CatalogPage>{
 if(activeCatalog>=3)await new Promise<void>(resolve=>catalogQueue.push(resolve));
 activeCatalog++;
 try {signal.throwIfAborted();
 const response=await fetch(`/api/v1/catalog/${kind}?${new URLSearchParams({search,offset:String(offset)})}`,{cache:'no-store',signal});
 if(!response.ok){let code='CATALOG_UNAVAILABLE';try{code=(await response.json()).error.code;}catch{}throw new CatalogFailure(code);}
 const value=await response.json();
 if(!Array.isArray(value.items)||value.items.length>20||!Number.isInteger(value.count)||typeof value.more!=='boolean')throw new CatalogFailure('CATALOG_RESPONSE_INVALID');
 return value;
 } finally {activeCatalog--;catalogQueue.shift()?.();}
}
export async function inspectConnection(input:ConnectionInput):Promise<{onboarding_token:string;preview:SourcePreview;suggested_source_instance:string}>{
 const value=await post('/api/v1/sources/test-connection',{...input,preview:true}) as {onboarding_token:string;preview:SourcePreview;suggested_source_instance:string};
 if(!value||typeof value.onboarding_token!=='string'||!value.preview||!Array.isArray(value.preview.hosts)||!value.preview.hosts.length||value.preview.hosts.length>16)throw new Error('Host information is unavailable; no source was registered.');
 return value;
}
