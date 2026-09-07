export type SyncAction =
  | "CREATE"
  | "UPDATE"
  | "NO_CHANGE"
  | "REVIEW_REQUIRED"
  | "BLOCKED"
  | "IGNORED"
  | "UNSUPPORTED"
  | "RETAIN_ONLY";
export interface SyncPlanItem {
  object_kind: string;
  external_id: string;
  name: string;
  action: SyncAction;
  reason_code: string;
  reason: string;
  matched_object_id: string | number | null;
  before: [string, unknown][];
  after: [string, unknown][];
}
export interface SyncPlan {
  source_instance: string;
  source_type: "proxmox" | "esxi";
  source_fingerprint: string;
  target_fingerprint: string;
  provider_fingerprint: string;
  netbox_fingerprint: string;
  schema_version: number;
  planner_version: string;
  items: SyncPlanItem[];
  apply_allowed: boolean;
  digest: string;
}
export type ApplyStatus =
  | "SUCCEEDED"
  | "FAILED_BEFORE_WRITE"
  | "PARTIALLY_APPLIED"
  | "OUTCOME_UNCERTAIN";
export interface ApplyResult {
  status: ApplyStatus;
  plan_digest: string;
  run_id?: string | null;
}
const record = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const actions = [
  "CREATE",
  "UPDATE",
  "NO_CHANGE",
  "REVIEW_REQUIRED",
  "BLOCKED",
  "IGNORED",
  "UNSUPPORTED",
  "RETAIN_ONLY",
];
const genericFailure =
  "Manual sync request failed. No automatic retry was performed.";
const messages: Record<string, string> = {
  APPLY_LOCKED: "Sync did not start because another sync operation is active.",
  PLAN_STALE:
    "Source or NetBox state changed. Build a new plan before syncing.",
  CONFIRMATION_EXPIRED:
    "Sync confirmation expired. Build a new plan before syncing.",
  CONFIRMATION_INVALID:
    "Sync confirmation is no longer valid. Build a new plan.",
  CONFIRMATION_SOURCE_MISMATCH:
    "Sync confirmation does not match this source. Build a new plan.",
  PLAN_BLOCKED: "Sync did not start because safety checks blocked the plan.",
  FAILED_BEFORE_WRITE: "Sync failed before changes were applied.",
  PARTIALLY_APPLIED:
    "Some changes may have been applied. Review the run before continuing.",
  OUTCOME_UNCERTAIN:
    "Final outcome could not be confirmed. Do not retry automatically.",
  APPLY_FAILED: "Manual sync request failed",
  SOURCE_NOT_FOUND: "Source not found.",
  SOURCE_DISABLED: "Source is disabled.",
  REGISTRY_UNAVAILABLE: "Source registry is unavailable.",
  PROVIDER_UNAVAILABLE: "Source discovery is unavailable.",
  NETBOX_UNAVAILABLE: "NetBox comparison is unavailable.",
  CREDENTIAL_UNAVAILABLE: "Source-scoped credentials are unavailable.",
  DISCOVERY_TIMEOUT: "Planning timed out.",
  DISCOVERY_UNAVAILABLE: "Planning worker is unavailable.",
  DISCOVERY_FAILED: "Planning failed.",
  DISCOVERY_RESPONSE_INVALID: "Plan response could not be validated.",
  APPLY_UNAVAILABLE:
    "Apply worker response is unavailable. The outcome may be unknown.",
  APPLY_RESPONSE_INVALID:
    "Apply response could not be validated. The outcome may be unknown.",
};
export class ManualSyncRequestError extends Error {
  code: string;
  constructor(message = genericFailure, code = "UNKNOWN") {
    super(message);
    this.name = "ManualSyncRequestError";
    this.code = code;
  }
}
async function errorFor(response: Response): Promise<ManualSyncRequestError> {
  try {
    const value: unknown = await response.json();
    const code =
      record(value) &&
      record(value.error) &&
      typeof value.error.code === "string"
        ? value.error.code
        : "UNKNOWN";
    return new ManualSyncRequestError(
      Object.hasOwn(messages, code) ? messages[code] : genericFailure,
      Object.hasOwn(messages, code) ? code : "UNKNOWN",
    );
  } catch {
    return new ManualSyncRequestError();
  }
}
const digest = (value: unknown) =>
  typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const pairs = (value: unknown): value is [string, unknown][] =>
  Array.isArray(value) &&
  value.every(
    (pair) =>
      Array.isArray(pair) && pair.length === 2 && typeof pair[0] === "string",
  ) &&
  new Set(value.map((pair) => pair[0])).size === value.length;
export const validPlan = (value: unknown, instance: string): value is SyncPlan =>
  record(value) &&
  value.source_instance === instance &&
  (value.source_type === "proxmox" || value.source_type === "esxi") &&
  digest(value.digest) &&
  [
    "source_fingerprint",
    "target_fingerprint",
    "provider_fingerprint",
    "netbox_fingerprint",
    "planner_version",
  ].every((key) => typeof value[key] === "string") &&
  Number.isSafeInteger(value.schema_version) &&
  typeof value.apply_allowed === "boolean" &&
  Array.isArray(value.items) &&
  value.items.every(
    (item) =>
      record(item) &&
      typeof item.action === "string" &&
      actions.includes(item.action) &&
      ["name", "object_kind", "external_id", "reason", "reason_code"].every(
        (key) => typeof item[key] === "string",
      ) &&
      (item.matched_object_id === null ||
        typeof item.matched_object_id === "string" ||
        typeof item.matched_object_id === "number") &&
      pairs(item.before) &&
      pairs(item.after),
  );
const protectedPost = async (
  path: string,
  body: object,
  signal: AbortSignal,
) => {
  try {
    return await fetch(path, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-NetBox-Sync-CSRF": "same-origin",
      },
      credentials: "same-origin",
      cache: "no-store",
      signal,
      body: JSON.stringify(body),
    });
  } catch {
    throw new ManualSyncRequestError(
      "Client/network response was lost. No automatic retry was performed.",
      "NETWORK_LOST",
    );
  }
};
export async function buildSyncPlan(
  instance: string,
  signal: AbortSignal,
): Promise<SyncPlan> {
  const response = await protectedPost(
    `/api/v1/sources/${encodeURIComponent(instance)}/sync-plan`,
    {},
    signal,
  );
  if (!response.ok) throw await errorFor(response);
  let value: unknown;
  try {
    value = await response.json();
  } catch {
    throw new ManualSyncRequestError();
  }
  if (!validPlan(value, instance))
    throw new ManualSyncRequestError(
      "Sync plan returned malformed data.",
      "INVALID_RESPONSE",
    );
  return value;
}
export async function prepareSync(
  instance: string,
  expectedDigest: string,
  signal: AbortSignal,
  operationId?: string,
): Promise<string> {
  const response = await protectedPost(
    `/api/v1/sources/${encodeURIComponent(instance)}/sync-confirmations`,
    { plan_digest: expectedDigest, confirmed: true, ...(operationId ? { operation_id: operationId } : {}) },
    signal,
  );
  if (!response.ok) throw await errorFor(response);
  let value: unknown;
  try {
    value = await response.json();
  } catch {
    throw new ManualSyncRequestError();
  }
  if (!record(value) || !digest(value.confirmation_token))
    throw new ManualSyncRequestError();
  return value.confirmation_token as string;
}
export async function applySync(
  instance: string,
  token: string,
  signal: AbortSignal,
  operationId?: string,
): Promise<ApplyResult> {
  const response = await protectedPost(
    `/api/v1/sources/${encodeURIComponent(instance)}/sync`,
    { confirmation_token: token, ...(operationId ? {operation_id: operationId} : {}) },
    signal,
  );
  if (!response.ok) throw await errorFor(response);
  let value: unknown;
  try {
    value = await response.json();
  } catch {
    throw new ManualSyncRequestError();
  }
  if (
    !record(value) ||
    ![
      "SUCCEEDED",
      "FAILED_BEFORE_WRITE",
      "PARTIALLY_APPLIED",
      "OUTCOME_UNCERTAIN",
    ].includes(String(value.status)) ||
    typeof value.status !== "string" ||
    !digest(value.plan_digest) ||
    (value.run_id !== undefined &&
      value.run_id !== null &&
      (typeof value.run_id !== "string" ||
        !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
          value.run_id,
        )))
  )
    throw new ManualSyncRequestError();
  return value as unknown as ApplyResult;
}
