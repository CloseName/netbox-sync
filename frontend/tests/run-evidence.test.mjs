import assert from "node:assert/strict";
import test from "node:test";
import {
  staleEvidence,
  runAttention,
  planActions, unknownCounts, countExplanation,
} from "../src/ui/runEvidence.ts";
import {
  aggregateReason,
  componentReason,
  coverage,
} from "../src/ui/diagnosticEvidence.ts";
import { duration } from "../src/ui/format.ts";
import { runStatus } from "../src/ui/status.ts";
import { fetchRunPage } from "../src/api/runs.ts";
import { run, diagnostics, staleWarning, runId } from "./fixtures.mjs";
test("stale joins require recorded RUNNING and exact source/run evidence with usable history", () => {
  const d = diagnostics();
  d.stale_runs = [staleWarning];
  assert.equal(staleEvidence(run("RUNNING"), "source-1", d), staleWarning);
  for (const status of [
    "SUCCEEDED",
    "FAILED",
    "OUTCOME_UNCERTAIN",
    "PARTIALLY_APPLIED",
  ])
    assert.equal(staleEvidence(run(status), "source-1", d), undefined);
  assert.equal(staleEvidence(run("RUNNING"), "source-2", d), undefined);
  assert.equal(
    staleEvidence(
      { ...run("RUNNING"), run_id: "22222222-2222-4222-8222-222222222222" },
      "source-1",
      d,
    ),
    undefined,
  );
  d.components.run_history.status = "UNAVAILABLE";
  assert.equal(staleEvidence(run("RUNNING"), "source-1", d), undefined);
});
test("outcomes never derive running or no changes from a missing duration", () => {
  const labels = {
    SUCCEEDED: "Completed",
    FAILED_BEFORE_WRITE: "Failed before changes",
    BLOCKED: "Blocked by safety checks",
    LOCKED: "Not started — sync busy",
    PARTIALLY_APPLIED: "Partially applied",
    OUTCOME_UNCERTAIN: "Outcome unknown",
    FAILED: "Failed",
    RUNNING: "Recorded as running",
  };
  for (const [status, label] of Object.entries(labels)) {
    assert.equal(runStatus(status).label, label);
    assert.equal(duration(null), "Not recorded");
  }
  assert.equal(runStatus("RUNNING", true).label, "Completion unconfirmed");
  assert.equal(
    runAttention(run("OUTCOME_UNCERTAIN"), false),
    "Verify final state",
  );
  assert.equal(
    runAttention(run("PARTIALLY_APPLIED"), false),
    "Review partial result",
  );
  assert.equal(planActions(run("FAILED")), "Create 1 · Update 2");
  assert.equal(duration(134000), "2 min 14 s");
});
test("cursor client sends backend filters and rejects malformed cursor, never forwards unsupported timeframe", async (ctx) => {
  const requests = [];
  const mock = ctx.mock.method(globalThis, "fetch", async (url) => {
    requests.push(String(url));
    return Response.json({ runs: [run()], next_cursor: runId });
  });
  const query = new URLSearchParams({
    source_instance: "source-1",
    source_type: "proxmox",
    trigger: "manual",
    status: "FAILED",
    cursor: runId,
    timeframe: "24h",
  });
  assert.equal(
    (await fetchRunPage(query, new AbortController().signal)).next_cursor,
    runId,
  );
  const sent = new URL(requests[0], "https://example.test").searchParams;
  assert.equal(sent.get("limit"), "50");
  assert.equal(sent.has("timeframe"), false);
  for (const key of [
    "source_instance",
    "source_type",
    "trigger",
    "status",
    "cursor",
  ])
    assert.equal(sent.get(key), query.get(key));
  mock.mock.mockImplementation(async () =>
    Response.json({ runs: [run()], next_cursor: "bad" }),
  );
  await assert.rejects(fetchRunPage(query, new AbortController().signal));
});
test("diagnostic meanings distinguish checks, activity, unknown and bounded coverage", () => {
  const d = diagnostics();
  assert.match(
    componentReason("apply_worker", d.components.apply_worker),
    /connectivity are not tested/,
  );
  assert.match(
    componentReason("scheduler", d.components.scheduler),
    /not a live heartbeat/,
  );
  d.components.scheduler.status = "UNKNOWN";
  d.components.scheduler.safe_message = null;
  assert.equal(
    componentReason("scheduler", d.components.scheduler),
    "No verification evidence is available.",
  );
  d.overall_status = "DEGRADED";
  d.stale_runs = [staleWarning];
  d.warnings = [staleWarning];
  assert.match(aggregateReason(d), /Checked components are available/);
  d.stale_runs = Array(100).fill(staleWarning);
  assert.match(coverage(d), /more may exist/);
  d.components.registry.status = "UNAVAILABLE";
  assert.match(coverage(d), /incomplete/);
  assert.doesNotMatch(aggregateReason(d), /Checked components are available/);
});

test('missing counters cannot establish zero writes and prewrite refusals stay distinct',()=>{
 const empty=Object.fromEntries(Object.keys(run().actions).map(key=>[key,0]));
 const uncertain={...run('OUTCOME_UNCERTAIN'),actions:empty};assert(unknownCounts(uncertain));assert.match(planActions(uncertain),/may have been written/);
 assert.match(countExplanation({...uncertain,status:'FAILED_BEFORE_WRITE'}),/did not start writes/);
 assert(!unknownCounts({...uncertain,status:'SUCCEEDED'}));
});
