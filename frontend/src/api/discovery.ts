export interface DiscoveryProperties {vcpus?:number|null;memory_bytes?:number|null;cpu?:string|null;status?:string|null;architecture?:string|null;os_type?:string|null;manufacturer?:string|null;model?:string|null;hypervisor_version?:string|null;addresses?:string[];interfaces?:{name:string;addresses:string[];mac_address?:string|null;bridge?:string|null;vlan_id?:number|null}[];disks?:{name:string;size_bytes:number}[];}
export type Classification = 'MANAGED' | 'REVIEW_REQUIRED' | 'WOULD_CREATE' | 'IGNORED' | 'UNSUPPORTED' | 'CONFLICT' | 'NO_CHANGE';
export interface DiscoveryItem { properties?:DiscoveryProperties; object_kind: 'host' | 'host_network' | 'qemu' | 'lxc' | 'vm'; name: string; external_id: string; classification: Classification; reason_code: string; reason: string; future_action: 'none' | 'create' | 'update' | 'review' | 'ignored' | 'unsupported'; matched_object_id: string | number | null; matched_object_name: string | null; }
export interface DiscoveryResult { source_instance: string; source_type: 'proxmox' | 'esxi'; site_slug: string; cluster_name: string; items: DiscoveryItem[]; }
const classifications = ['MANAGED', 'REVIEW_REQUIRED', 'WOULD_CREATE', 'IGNORED', 'UNSUPPORTED', 'CONFLICT', 'NO_CHANGE'];
const actions = ['none', 'create', 'update', 'review', 'ignored', 'unsupported'];
const kinds = ['host', 'host_network', 'qemu', 'lxc', 'vm'];
const record = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value);
const strings = (value: unknown) => Array.isArray(value) && value.every(v=>typeof v==='string');
const optionalString = (value: unknown) => value==null || typeof value==='string';
const optionalNumber = (value: unknown) => value==null || typeof value==='number' && Number.isFinite(value) && value>=0;
const properties = (value: unknown): boolean => value===undefined || record(value)
  && ['vcpus','memory_bytes'].every(k=>optionalNumber(value[k]))
  && ['cpu','status','architecture','os_type','manufacturer','model','hypervisor_version'].every(k=>optionalString(value[k]))
  && (value.addresses===undefined || strings(value.addresses))
  && (value.interfaces===undefined || Array.isArray(value.interfaces) && value.interfaces.every(n=>record(n)
    && typeof n.name==='string' && strings(n.addresses) && optionalString(n.mac_address)
    && optionalString(n.bridge) && optionalNumber(n.vlan_id)))
  && (value.disks===undefined || Array.isArray(value.disks) && value.disks.every(d=>record(d)
    && typeof d.name==='string' && typeof d.size_bytes==='number' && Number.isFinite(d.size_bytes) && d.size_bytes>=0));
const item = (value: unknown): value is DiscoveryItem => record(value)
  && properties(value.properties)
  && typeof value.object_kind === 'string' && kinds.includes(value.object_kind)
  && ['name', 'external_id', 'reason_code', 'reason'].every((key) => typeof value[key] === 'string')
  && typeof value.classification === 'string' && classifications.includes(value.classification)
  && typeof value.future_action === 'string' && actions.includes(value.future_action)
  && (value.matched_object_id === null || typeof value.matched_object_id === 'string' || typeof value.matched_object_id === 'number')
  && (value.matched_object_name === null || typeof value.matched_object_name === 'string');

export const validDiscovery = (value: unknown, instance: string): value is DiscoveryResult =>
  record(value) && value.source_instance === instance && (value.source_type === 'proxmox' || value.source_type === 'esxi') && typeof value.site_slug === 'string' && typeof value.cluster_name === 'string' && Array.isArray(value.items) && value.items.every(item);

export async function runDiscovery(instance: string, signal: AbortSignal): Promise<DiscoveryResult> {
  let response: Response;
  try { response = await fetch(`/api/v1/sources/${encodeURIComponent(instance)}/discovery`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-NetBox-Sync-CSRF': 'same-origin' }, credentials: 'same-origin', body: '{}', signal, cache: 'no-store' }); }
  catch { throw new Error('Discovery worker is unavailable.'); }
  if (!response.ok) {
    let code = '';
    try { const value: unknown = await response.json(); code = record(value) && record(value.error) && typeof value.error.code === 'string' ? value.error.code : ''; } catch { /* safe fallback */ }
    const messages: Record<string,string> = {
      SOURCE_DISABLED: 'Disabled sources cannot be discovered.',
      SOURCE_NOT_FOUND: 'Source not found.', DISCOVERY_TIMEOUT: 'Discovery timed out.',
      PROVIDER_UNAVAILABLE: 'Source discovery is unavailable.',
      REGISTRY_UNAVAILABLE: 'Discovery registry is unavailable.',
      NETBOX_UNAVAILABLE: 'NetBox comparison is unavailable.',
      CREDENTIAL_UNAVAILABLE: 'Source-scoped discovery credentials are unavailable.',
      DISCOVERY_UNAVAILABLE: 'Discovery worker is unavailable.',
    };
    throw new Error(Object.hasOwn(messages, code) ? messages[code] : 'Discovery failed. No changes were made.');
  }
  let value: unknown;
  try { value = await response.json(); } catch { throw new Error('Discovery returned malformed data.'); }
  if (!record(value) || value.source_instance !== instance || (value.source_type !== 'proxmox' && value.source_type !== 'esxi') || typeof value.site_slug !== 'string' || typeof value.cluster_name !== 'string' || !Array.isArray(value.items) || !value.items.every(item)) throw new Error('Discovery returned malformed data.');
  return value as unknown as DiscoveryResult;
}
