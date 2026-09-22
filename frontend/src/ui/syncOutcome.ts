import { ManualSyncRequestError } from "../api/sync.ts";
import type { ApplyResult } from "../api/sync.ts";
import type { Status } from "./status.ts";
export interface SyncOutcome {
  state: string;
  message: string;
  status: Status;
  runId?: string;
  code?: string;
  eventId?: string;
  reason?: string;
  categories?: string[];
}
const statuses: Record<string, [string, string, Status["tone"]]> = {
  SUCCEEDED: [
    "Sync completed",
    "The reviewed plan completed. Plan counts describe operations, not individual applied objects.",
    "success",
  ],
  FAILED_BEFORE_WRITE: [
    "Failed before write",
    "Sync failed before changes were applied.",
    "danger",
  ],
  BLOCKED: [
    "Blocked",
    "Sync did not start because safety checks blocked the plan.",
    "danger",
  ],
  LOCKED: [
    "Sync did not start",
    "Sync did not start because another sync operation is active.",
    "warning",
  ],
  PARTIALLY_APPLIED: [
    "Partially applied",
    "Some changes may have been applied. Review the run before continuing.",
    "warning",
  ],
  OUTCOME_UNCERTAIN: [
    "Outcome unknown",
    "Final outcome could not be confirmed. Do not retry automatically.",
    "danger",
  ],
  STALE: [
    "Stale plan",
    "Source or NetBox state changed. Build a new plan before syncing.",
    "warning",
  ],
  FAILED: ["Request failed", "Manual sync request failed", "danger"],
  PREPARATION_FAILED: [
    "Validation failed",
    "Confirmation could not be prepared. No apply request was submitted.",
    "danger",
  ],
};
export function outcome(
  state: string,
  message?: string,
  code?: string,
  runId?: string,
): SyncOutcome {
  const [label, defaultMessage, tone] = statuses[state];
  return {
    state,
    message: message ?? defaultMessage,
    status: { label, tone, icon: tone === "success" ? "✓" : "!" },
    code,
    runId,
  };
}
export function applyOutcome(
  result: ApplyResult,
  expectedDigest: string,
): SyncOutcome {
  if (result.plan_digest !== expectedDigest)
    return outcome(
      "OUTCOME_UNCERTAIN",
      "The response did not match the reviewed plan. Final outcome could not be confirmed. Do not retry automatically.",
      "DIGEST_MISMATCH",
    );
  return outcome(
    result.status,
    result.status==='SUCCEEDED' && result.ipam_complete===false ? 'Inventory synchronized with address observations. Disputed IPAM assignments remain incomplete; review the NetBox interfaces.' : undefined,
    undefined,
    result.run_id ?? undefined,
  );
}
function baseFailedOutcome(
  error: unknown,
  stage: "validating" | "applying",
): SyncOutcome {
  const code = error instanceof ManualSyncRequestError ? error.code : "UNKNOWN";
  if (
    [
      "PLAN_STALE",
      "CONFIRMATION_EXPIRED",
      "CONFIRMATION_INVALID",
      "CONFIRMATION_SOURCE_MISMATCH",
    ].includes(code)
  )
    return outcome("STALE", undefined, code);
  if (code === "PLAN_BLOCKED") return outcome("BLOCKED", undefined, code);
  if (code === "APPLY_LOCKED") return outcome("LOCKED", undefined, code);
  if (
    ["FAILED_BEFORE_WRITE", "PARTIALLY_APPLIED", "OUTCOME_UNCERTAIN"].includes(
      code,
    )
  )
    return outcome(code, undefined, code);
  if (stage === "validating")
    return outcome(
      "PREPARATION_FAILED",
      error instanceof ManualSyncRequestError
        ? error.message + " No apply request was submitted."
        : undefined,
      code,
    );
  if (code === "APPLY_FAILED") return outcome("FAILED", undefined, code);
  return outcome(
    "OUTCOME_UNCERTAIN",
    code === "NETWORK_LOST"
      ? "Client/network response was lost. Final outcome could not be confirmed. Do not retry automatically."
      : undefined,
    code,
  );
}

export function failedOutcome(error: unknown, stage: 'validating' | 'applying'): SyncOutcome {
  const result = baseFailedOutcome(error, stage);
  if (error instanceof ManualSyncRequestError) {
    result.eventId = error.eventId; result.reason = error.reason; result.categories = error.categories;
  }
  return result;
}
