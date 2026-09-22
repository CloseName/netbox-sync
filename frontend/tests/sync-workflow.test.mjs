import test from "node:test";
import assert from "node:assert/strict";
import {
  planCounts,
  policyRow,
  managedFields,
  fieldText,
  filterPlan,
} from "../src/ui/plan.ts";
import { applyOutcome, failedOutcome, reconcileTransportOutcome } from "../src/ui/syncOutcome.ts";
import {
  applySync,
  buildSyncPlan,
  ManualSyncRequestError,
} from "../src/api/sync.ts";
const digest = "a".repeat(64);
const row = (action, more = {}) => ({
  action,
  object_kind: "virtualization.virtual_machines",
  external_id: "1",
  name: "VM",
  reason: "Managed mutation",
  reason_code: "GUARDED_EXECUTOR_ACTION",
  matched_object_id: 1,
  before: [],
  after: [],
  ...more,
});
const plan = {
  source_instance: "source-1",
  source_type: "proxmox",
  digest,
  source_fingerprint: "s",
  target_fingerprint: "t",
  provider_fingerprint: "p",
  netbox_fingerprint: "n",
  schema_version: 1,
  planner_version: "v1",
  apply_allowed: true,
  items: [],
};
test("mixed plan counts operations and excludes only source retention policy", () => {
  const rows = [
    row("CREATE"),
    row("UPDATE"),
    row("UPDATE"),
    row("REVIEW_REQUIRED"),
    row("BLOCKED"),
    row("RETAIN_ONLY", { object_kind: "source" }),
    row("RETAIN_ONLY"),
    ...Array.from({ length: 105 }, () => row("NO_CHANGE")),
  ];
  assert.deepEqual(planCounts(rows), {
    CREATE: 1,
    UPDATE: 2,
    NO_CHANGE: 105,
    REVIEW_REQUIRED: 1,
    BLOCKED: 1,
    RETAIN_ONLY: 1,
    IGNORED: 0,
    UNSUPPORTED: 0,
  });
  assert.equal(filterPlan(rows, "Changes", "", "", "").length, 3);
  assert.equal(filterPlan(rows, "Attention", "", "", "").length, 2);
  assert.equal(filterPlan(rows, "All", "NO_CHANGE", "", "vm").length, 105);
  assert.equal(policyRow(rows[5]), true);
});
test("diff retains missing, null, empty and nested values without inferred provenance", () => {
  const fields = managedFields(
    row("UPDATE", {
      before: [
        ["status", null],
        ["old", ""],
      ],
      after: [
        ["status", "active"],
        ["nested", { id: 3, enabled: false }],
      ],
    }),
  );
  assert.equal(fieldText(fields[0].before), "null");
  assert.equal(fieldText(fields[1].before), '"" (empty string)');
  assert.equal(fieldText(fields[1].after), "Not provided");
  assert.equal(fieldText(fields[2].before), "Not provided");
  assert.equal(fieldText(fields[2].after), '{"id":3,"enabled":false}');
  assert.deepEqual(managedFields(row("CREATE")), []);
});
test("plan transport rejects malformed pairs, duplicate fields and foreign identity", async (ctx) => {
  const mock = ctx.mock.method(globalThis, "fetch");
  for (const invalid of [
    { ...plan, source_instance: "source-2" },
    { ...plan, items: [row("UPDATE", { before: [["a"]] })] },
    {
      ...plan,
      items: [
        row("UPDATE", {
          before: [
            ["a", 1],
            ["a", 2],
          ],
        }),
      ],
    },
  ]) {
    mock.mock.mockImplementationOnce(async () => Response.json(invalid));
    await assert.rejects(
      buildSyncPlan("source-1", new AbortController().signal),
      /malformed/,
    );
  }
});
test("all actual result statuses and optional run IDs survive client parsing", async (ctx) => {
  const runId = "11111111-1111-4111-8111-111111111111";
  const mock = ctx.mock.method(globalThis, "fetch");
  for (const status of [
    "SUCCEEDED",
    "FAILED_BEFORE_WRITE",
    "PARTIALLY_APPLIED",
    "OUTCOME_UNCERTAIN",
  ]) {
    mock.mock.mockImplementationOnce(async () =>
      Response.json({ status, plan_digest: digest, run_id: runId }),
    );
    const result = await applySync(
      "source-1",
      "b".repeat(64),
      new AbortController().signal,
    );
    assert.equal(applyOutcome(result, digest).runId, runId);
    assert.equal(applyOutcome(result, digest).state, status);
  }
  assert.equal(
    applyOutcome({ status: "SUCCEEDED", plan_digest: digest }, digest).runId,
    undefined,
  );
  assert.equal(
    applyOutcome(
      { status: "SUCCEEDED", plan_digest: digest, run_id: runId },
      "c".repeat(64),
    ).state,
    "OUTCOME_UNCERTAIN",
  );
});
test("safe failure classification distinguishes stage and never asserts writes absent after response loss", () => {
  for (const [code, state] of [
    ["PLAN_STALE", "STALE"],
    ["PLAN_BLOCKED", "BLOCKED"],
    ["APPLY_LOCKED", "LOCKED"],
    ["PARTIALLY_APPLIED", "PARTIALLY_APPLIED"],
    ["OUTCOME_UNCERTAIN", "OUTCOME_UNCERTAIN"],
    ["FAILED_BEFORE_WRITE", "FAILED_BEFORE_WRITE"],
    ["APPLY_FAILED", "FAILED"],
    ["NETWORK_LOST", "OUTCOME_UNCERTAIN"],
    ["UNKNOWN", "OUTCOME_UNCERTAIN"],
  ]) {
    assert.equal(
      failedOutcome(new ManualSyncRequestError("safe", code), "applying").state,
      state,
    );
  }
  assert.equal(
    failedOutcome(
      new ManualSyncRequestError(
        "Registry unavailable",
        "REGISTRY_UNAVAILABLE",
      ),
      "validating",
    ).state,
    "PREPARATION_FAILED",
  );
});


test('transport loss follows only the exact durable run and digest without retry',()=>{
 const lost=failedOutcome(new ManualSyncRequestError('safe','NETWORK_LOST'),'applying');
 const run={run_id:'accepted',status:'RUNNING',plan_digest:digest};
 assert.equal(reconcileTransportOutcome(lost,run,'another',digest),lost);
 assert.equal(reconcileTransportOutcome(lost,{...run,plan_digest:'b'.repeat(64)},'accepted',digest),lost);
 const running=reconcileTransportOutcome(lost,run,'accepted',digest);
 assert.equal(running.state,'RUNNING');
 const complete=reconcileTransportOutcome(running,{...run,status:'SUCCEEDED'},'accepted',digest,true);
 assert.equal(complete.state,'SUCCEEDED');assert.match(complete.message,/IPAM assignments remain incomplete/);
 const uncertain=failedOutcome(new ManualSyncRequestError('safe','OUTCOME_UNCERTAIN'),'applying');
 assert.equal(reconcileTransportOutcome(uncertain,run,'accepted',digest),uncertain);
});
