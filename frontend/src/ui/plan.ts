import {tr} from './i18n.ts';
import type { SyncPlanItem, SyncAction } from "../api/sync.ts";
import type { Status } from "./status.ts";
export const actionLabels: Record<SyncAction, string> = {
  CREATE: "Create",
  UPDATE: "Update",
  NO_CHANGE: "Unchanged",
  REVIEW_REQUIRED: "Needs review",
  BLOCKED: "Blocked",
  IGNORED: "Ignored",
  UNSUPPORTED: "Unsupported",
  RETAIN_ONLY: "Retained",
};
export function actionStatus(action: SyncAction): Status {
  return {
    label: actionLabels[action],
    tone:
      action === "BLOCKED"
        ? "danger"
        : action === "REVIEW_REQUIRED"
          ? "warning"
          : action === "CREATE" || action === "UPDATE"
            ? "info"
            : "neutral",
    icon:
      action === "BLOCKED" || action === "REVIEW_REQUIRED"
        ? "!"
        : action === "CREATE"
          ? "+"
          : action === "UPDATE"
            ? "↻"
            : "−",
  };
}
export const policyRow = (item: SyncPlanItem) =>
  item.action === "RETAIN_ONLY" && item.object_kind === "source";
export function planCounts(items: SyncPlanItem[]) {
  const result: Record<SyncAction, number> = {
    CREATE: 0,
    UPDATE: 0,
    NO_CHANGE: 0,
    REVIEW_REQUIRED: 0,
    BLOCKED: 0,
    IGNORED: 0,
    UNSUPPORTED: 0,
    RETAIN_ONLY: 0,
  };
  for (const item of items) if (!policyRow(item)) result[item.action]++;
  return result;
}
export const countLabels: Record<SyncAction, string> = {
  CREATE: "Create operations",
  UPDATE: "Update operations",
  REVIEW_REQUIRED: "Needs review rows",
  BLOCKED: "Blocking rows",
  NO_CHANGE: "Unchanged rows",
  RETAIN_ONLY: "Retained rows",
  IGNORED: "Ignored rows",
  UNSUPPORTED: "Unsupported rows",
};
/** Presentation only: never change actions, payloads, digests or apply eligibility. */
export function observationRefreshOnly(item: SyncPlanItem): boolean {
  if (item.action !== 'UPDATE' || item.object_kind !== 'dcim.devices') return false;
  const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
  const before = Object.fromEntries(item.before), after = Object.fromEntries(item.after);
  if (Object.keys(before).length !== item.before.length || Object.keys(after).length !== item.after.length) return false;
  const hardware = (v: Record<string, unknown>) => object(v.custom_fields) && object(v.custom_fields.hardware_identity) ? v.custom_fields.hardware_identity : null;
  const old = hardware(before), next = hardware(after);
  if (!old || !next || old.version !== 1 || next.version !== 1 ||
      !['esxi','proxmox'].includes(String(old.source)) || old.source !== next.source ||
      typeof old.observed_at !== 'string' || !old.observed_at ||
      typeof next.observed_at !== 'string' || !next.observed_at || old.observed_at === next.observed_at) return false;
  const stable = (v: unknown): string => {
    if (Array.isArray(v)) return '[' + v.map(stable).join(',') + ']';
    if (object(v)) return '{' + Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+stable(v[k])).join(',') + '}';
    return JSON.stringify(v) ?? 'undefined';
  };
  const withoutClock = (v: Record<string,unknown>, doc: Record<string,unknown>) => {
    const {observed_at: _clock, ...content} = doc;
    return {...v, custom_fields: {...v.custom_fields as Record<string,unknown>, hardware_identity: content}};
  };
  return stable(withoutClock(before, old)) === stable(withoutClock(after, next));
}
export type PlanView = "Changes" | "Attention" | "All" | "Observation time";
export function filterPlan(
  items: SyncPlanItem[],
  view: PlanView,
  action: string,
  kind: string,
  search: string,
) {
  const query = search.toLocaleLowerCase().trim();
  return items.filter(
    (item) =>
      !policyRow(item) &&
      (view === "All" ||
        (view === "Observation time" ? observationRefreshOnly(item) : view === "Changes"
          ? ["CREATE", "UPDATE"].includes(item.action) && !observationRefreshOnly(item)
          : ["REVIEW_REQUIRED", "BLOCKED", "UNSUPPORTED"].includes(item.action))) &&
      (!action || item.action === action) &&
      (!kind || item.object_kind === kind) &&
      (!query ||
        [item.name, item.object_kind, item.reason, item.external_id].some(
          (value) => value.toLocaleLowerCase().includes(query),
        )),
  );
}
export interface FieldValue {
  provided: boolean;
  value?: unknown;
}
export function managedFields(item: SyncPlanItem) {
  const before = new Map(item.before as [string, unknown][]),
    after = new Map(item.after as [string, unknown][]);
  return [...new Set([...before.keys(), ...after.keys()])].filter(field=>!['matching_candidates','replacement_evidence','replacement_card_url'].includes(field)).map((field) => ({
    field,
    before: {
      provided: before.has(field),
      value: before.get(field),
    } as FieldValue,
    after: {
      provided: after.has(field),
      value: after.get(field),
    } as FieldValue,
  }));
}
export function fieldText(field: FieldValue): string {
  if (!field.provided) return "Not provided";
  if (field.value === null) return "null";
  if (field.value === "") return '"" (empty string)';
  return typeof field.value === "string"
    ? field.value
    : JSON.stringify(field.value);
}
export function kindLabel(kind: string) {
  const labels: Record<string, string> = {
    host: "Host",
    host_network: "Host networking",
    qemu: "Discovered VM (QEMU)",
    vm: "Discovered VM",
    lxc: "Container",
    "virtualization.virtual_machines": "Virtual machine",
    "dcim.devices": "Device",
    "dcim.mac_addresses": "MAC address",
    "ipam.ip_addresses": "IP address",
    "virtualization.interfaces": "VM interface",
    "dcim.interfaces": "Device interface",
    source: "Source policy",
  };
  return labels[kind] ?? kind;
}

export const hasChanges = (items:SyncPlanItem[]) => items.some(i=>i.action==='CREATE'||i.action==='UPDATE');
export function emptyPlanLabel(items:SyncPlanItem[]) {
  const objects=items.filter(i=>!policyRow(i));

  if(objects.length&&objects.every(i=>i.action==='IGNORED'))return 'All discovered objects are excluded';
  if(objects.some(i=>i.action==='REVIEW_REQUIRED'))return 'Objects require separate review';
  return 'No changes to apply';
}

export function planReason(item:{reason_code:string;reason:string;action?:SyncAction}) {
 const reasons:Record<string,string>={
  NO_IDENTITY_MATCH:'No existing object has this stable source identity.',
  IDENTITY_MATCH:'Stable source identity matches an existing NetBox object.',
  SELECTEL_HARDWARE_MATCH:'Unique hardware identity matches the existing Selectel device. Its provider fields are preserved.',
  SELECTEL_HARDWARE_IDENTITY_CONFLICT:'Hardware identifiers disagree. Check the serial number and system UUID before linking the Selectel device.',
  SELECTEL_HOST_ALREADY_MANAGED:'The Selectel device already belongs to another Sync source. Review that source instead of creating a duplicate.',
  SELECTEL_HARDWARE_REVIEW_REQUIRED:'Refresh Selectel inventory to verify the hardware identity before linking this host.',
  SELECTEL_MULTIPLE_HARDWARE_MATCHES:'Several Selectel devices share this hardware identity. Resolve the duplicate bindings before synchronization.',
  SELECTEL_PLACEMENT_REVIEW_REQUIRED:'Select the existing Selectel device site and a compatible cluster before synchronizing.',
  IDENTITY_SCOPE_CONFLICT:'The stable identity is duplicated or outside the configured target.',
  NAME_ONLY_CANDIDATE:'A name match exists but names are not identity evidence.',
  MANAGEMENT_IP_CONFLICT:'Management IP evidence is ambiguous or outside the configured target.',
  MANAGEMENT_IP_CANDIDATE:'Management IP matches, but network evidence alone does not establish ownership.',
  SAFE_ADOPTION_CANDIDATE:'Stable evidence exists, but Web discovery never adopts objects.',
  LEGACY_REVIEW_REQUIRED:'Legacy evidence requires operator review and is not adopted.',
  AMBIGUOUS_LEGACY_MATCH:'Legacy evidence is ambiguous; processing is blocked.',

  OTHER_SOURCE_OWNERSHIP:'A matching object retains another source identity. Re-registration does not restore ownership.',
  VM_IDENTITY:'Shared VM identifier',
  IP_ASSIGNMENT:'Conflicting IP assignment',
  MAC_ASSIGNMENT:'Conflicting MAC assignment',
  MAC_OBSERVATION_ONLY:'Stored on NetBox interfaces for review; disputed MAC assignments are not synchronized.',
  NETWORK_SCOPE_REVIEW_REQUIRED:'Selected network scope changed or no longer exists. Review the source VRF mapping.',
  IP_OBSERVATION_ONLY:'Stored on NetBox interfaces for review; disputed IPAM assignments are not synchronized.',
  DISK_SIZE_UNKNOWN:'The source did not report a positive disk capacity. Check this disk in the hypervisor and build a new plan. Existing NetBox data is preserved.',
  HOST_NETWORK_FIELD_REQUIRED:'Prepare the ESXi host network field in NetBox settings before synchronization.',
  OBSERVATION_FIELD_REQUIRED:'Prepare the network observations field in NetBox settings before synchronization.',
  ESXI_HOST_NETWORK_UNSUPPORTED:'ESXi topology is stored in a device snapshot. The verified connection IPv4 and its VMkernel interface are synchronized separately; other host networking remains report-only.',
  MANAGED_FIELD_UPDATE:'Update managed fields',
  EXECUTOR_CREATE_UNSUPPORTED:'No supported create operation was produced for this object.'
 };
 if(item.reason_code==='HOST_NETWORK_FIELD_REQUIRED' && item.reason.startsWith('NetBox field '))return item.reason;
 if(Object.hasOwn(reasons,item.reason_code))return tr(reasons[item.reason_code]);
 if(item.reason==='Existing guarded executor would perform this managed-field mutation.')return tr(item.action==='CREATE'?'Create managed object':'Update managed fields');
 return item.reason;
}


/** Presentation only; the canonical plan submitted for confirmation is unchanged. */
export function readablePlanItem(item: SyncPlanItem, items: SyncPlanItem[]): SyncPlanItem {
  const temporary = (value: unknown) => typeof value === 'number' && value < 0;
  const relations: Record<string,string> = {device:'dcim.devices', virtual_machine:'virtualization.virtual_machines',
    parent:item.object_kind, bridge:item.object_kind, primary_ip4:'ipam.ip_addresses', primary_ip6:'ipam.ip_addresses',
    primary_mac_address:'dcim.mac_addresses'};
  const created = (kind:string, id:unknown) => items.find(row=>row.action==='CREATE' && row.object_kind===kind && new Map(row.after).get('id')===id);
  const label = (row?:SyncPlanItem) => {
    const values = new Map(row?.after ?? []);
    return String(values.get('name') ?? values.get('address') ?? values.get('mac_address') ?? 'Planned object');
  };
  const own = created(item.object_kind, item.matched_object_id ?? Number(item.external_id));
  const values = new Map([...item.before, ...item.after]);
  const present = (pairs:[string,unknown][]):[string,unknown][] => pairs.map(([key,value])=> {
    if (!temporary(value)) return [key,value];
    const assigned:Record<string,string> = {'dcim.interface':'dcim.interfaces','virtualization.vminterface':'virtualization.interfaces'};
    const kind = key==='id' ? item.object_kind : key==='assigned_object_id' ? assigned[String(values.get('assigned_object_type'))] : relations[key];
    return [key, kind ? label(created(kind,value)) : value];
  });
  return {...item, name:/^-\d+$/.test(item.name)?label(own):item.name,
    external_id:/^-\d+$/.test(item.external_id)?label(own):item.external_id,
    matched_object_id:temporary(item.matched_object_id)?label(own):item.matched_object_id,
    before:present(item.before),after:present(item.after)};
}

/** Resolve presentation context without changing submitted operations or identity. */
export function planParent(item:SyncPlanItem,items:SyncPlanItem[],seen=new Set<SyncPlanItem>()):string {
 if(seen.has(item))return '';seen.add(item);
 const fields=new Map([...item.before,...item.after]);
 const links:[string,string][]=[['device','dcim.devices'],['virtual_machine','virtualization.virtual_machines']];
 const assigned=String(fields.get('assigned_object_type')??'');
 if(assigned==='dcim.interface')links.push(['assigned_object_id','dcim.interfaces']);
 if(assigned==='virtualization.vminterface')links.push(['assigned_object_id','virtualization.interfaces']);
 for(const [key,kind] of links){
  const ref=fields.get(key);if(ref===undefined)continue;
  const id=typeof ref==='object'&&ref!==null?(ref as {id?:unknown}).id:ref;
  const parent=items.find(row=>row!==item&&row.object_kind===kind&&(row.matched_object_id===id||new Map(row.after).get('id')===id||row.external_id===String(id)));
  if(parent)return planParent(parent,items,seen)||readablePlanItem(parent,items).name;
  if(typeof ref==='object'&&ref!==null&&'name' in ref)return String(ref.name);
 }
 return '';
}

/** Count mutation targets, not operations. Endpoint + canonical target ID keeps
 * create/update pairs together without conflating same-named objects. */
export function changedObjectCount(items:SyncPlanItem[]):number {
 const keys=items.filter(i=>(i.action==='CREATE'||i.action==='UPDATE')&&!observationRefreshOnly(i)).map(i=>{
  const id=i.matched_object_id??new Map(i.after).get('id')??i.external_id;
  return JSON.stringify([i.object_kind,id]);
 });
 return new Set(keys).size;
}
