import {tr} from "./i18n.ts";
import type { Diagnostics, DiagnosticRun } from "../api/diagnostics";
import type { SyncRun } from "../api/runs";
export const staleExplanation =
  "Recorded as RUNNING. No completion was recorded within the expected window.";
export const planExplanation =
  "Counts describe recorded plan actions, not confirmed applied objects.";
export const actionLabels: Record<keyof SyncRun["actions"], string> = {
  create: "Create",
  update: "Update",
  no_change: "No change",
  review_required: "Review required",
  blocked: "Blocked",
  ignored: "Ignored",
  unsupported: "Unsupported",
  retain_only: "Retain only",
};
export function staleEvidence(
  run: DiagnosticRun,
  source: string,
  data: Diagnostics | null,
) {
  return run.status === "RUNNING" &&
    data?.components.run_history.status === "HEALTHY"
    ? data.stale_runs.find(
        (w) =>
          w.warning_code === "STALE_RUNNING" &&
          w.run_id === run.run_id &&
          w.source_instance === source,
      )
    : undefined;
}
export function runAttention(run: DiagnosticRun, stale: boolean): string {
  if (stale) return "Completion unconfirmed";
  if (run.status === "OUTCOME_UNCERTAIN") return "Verify final state";
  if (run.status === "PARTIALLY_APPLIED") return "Review partial result";
  if (
    ["FAILED", "FAILED_BEFORE_WRITE", "BLOCKED", "LOCKED"].includes(run.status)
  )
    return "Review result";
  if (run.status === "RUNNING") return "Completion not recorded";
  return "None reported";
}
export function planActions(run: SyncRun) {
  return (
    Object.entries(run.actions)
      .filter(([, n]) => n > 0)
      .map(
        ([key, n]) => `${tr(actionLabels[key as keyof SyncRun["actions"]])} ${n}`,
      )
      .join(" · ") || tr("No plan actions recorded")
  );
}
