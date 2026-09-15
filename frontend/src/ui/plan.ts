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
export type PlanView = "Changes" | "Attention" | "All";
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
        (view === "Changes"
          ? ["CREATE", "UPDATE"]
          : ["REVIEW_REQUIRED", "BLOCKED"]
        ).includes(item.action)) &&
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
  return [...new Set([...before.keys(), ...after.keys()])].map((field) => ({
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
    qemu: "Virtual machine",
    vm: "Virtual machine",
    lxc: "Container",
    "virtualization.virtual_machines": "Virtual machine",
    "dcim.devices": "Device",
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
  if(objects.some(i=>i.action==='UNSUPPORTED'))return 'No executable changes: unsupported objects';
  if(objects.length&&objects.every(i=>i.action==='IGNORED'))return 'All discovered objects are excluded';
  if(objects.some(i=>i.action==='REVIEW_REQUIRED'))return 'Objects require separate review';
  return 'No changes to apply';
}

export function planReason(item:{reason_code:string;reason:string}) {
 const reasons:Record<string,string>={
  ESXI_HOST_NETWORK_UNSUPPORTED:'ESXi host VMkernel/vSwitch networking is report-only; no host networking writes are supported.',
  EXECUTOR_CREATE_UNSUPPORTED:'No supported create operation was produced for this object.'
 };
 return Object.hasOwn(reasons,item.reason_code)?tr(reasons[item.reason_code]):item.reason;
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
