import test from "node:test";
import assert from "node:assert/strict";
import { source, diagnostics, staleWarning } from "./fixtures.mjs";
import {
  attention,
  composeSources,
  querySources,
  overviewReason,
} from "../src/ui/operations.ts";
import { healthStatus, runStatus } from "../src/ui/status.ts";
import { interval, duration } from "../src/ui/format.ts";
const sources = Array.from({ length: 105 }, (_, i) => source(i + 1));
const rows = composeSources(sources, diagnostics(sources));
test("sources search covers name identity address site and cluster; query combinations are applied before pagination", () => {
  for (const query of ["Source 001", "source-1", "host-1", "dc1", "Cluster 1"])
    assert.ok(querySources(rows, new URLSearchParams({ q: query })).total > 0);
  assert.equal(
    querySources(rows, new URLSearchParams({ provider: "esxi", site: "dc1" }))
      .total,
    0,
  );
  assert.equal(
    querySources(rows, new URLSearchParams({ provider: "proxmox" })).total,
    53,
  );
  assert.equal(
    querySources(rows, new URLSearchParams({ schedule: "off" })).total,
    2,
  );
  assert.equal(
    querySources(rows, new URLSearchParams({ q: "missing" })).total,
    0,
  );
});
test("sorting stable name and latest/next with missing evidence; pagination covers full dataset", () => {
  const result = querySources(
    rows,
    new URLSearchParams({ size: "50", page: "3" }),
  );
  assert.equal(result.rows.length, 5);
  assert.equal(result.total, 105);
  assert.equal(
    querySources(rows, new URLSearchParams({ page: "999" })).page,
    5,
  );
  assert.equal(
    querySources(rows, new URLSearchParams({ sort: "name", direction: "desc" }))
      .rows[0].source.source_instance,
    "source-105",
  );
  const changed = structuredClone(rows.slice(0, 3));
  changed[0].diagnostic.latest_run.started_at = "2025-01-01T00:00:00Z";
  changed[1].diagnostic.latest_run = null;
  assert.equal(
    querySources(
      changed,
      new URLSearchParams({ sort: "last", direction: "desc" }),
    ).rows[0].source.source_instance,
    "source-3",
  );
  assert.equal(
    querySources(
      changed,
      new URLSearchParams({ sort: "last", direction: "desc" }),
    ).rows.at(-1).source.source_instance,
    "source-2",
  );
  assert.equal(
    querySources(rows, new URLSearchParams({ sort: "next" })).rows[0].source
      .source_instance,
    "source-1",
  );
});
test("unavailable diagnostics never erase configuration or become healthy/no attention", () => {
  const result = composeSources(sources, null);
  assert.equal(result.length, 105);
  assert.equal(
    querySources(result, new URLSearchParams({ health: "UNAVAILABLE" })).total,
    105,
  );
  assert.equal(
    querySources(result, new URLSearchParams({ attention: "no" })).total,
    0,
  );
  const data = diagnostics(sources);
  data.components.run_history.status = "UNAVAILABLE";
  assert.ok(composeSources(sources, data).every((row) => !row.diagnostic));
});
test("attention priority is deterministic and unknown is not success", () => {
  const d = diagnostics().sources[0];
  d.status = "UNKNOWN";
  assert.equal(attention(d), null);
  assert.equal(healthStatus("UNKNOWN").tone, "neutral");
  d.warnings = ["STALE_RUNNING", "SCHEDULED_ACTIVITY_DELAYED"];
  assert.equal(attention(d).priority, 3);
  d.status = "UNHEALTHY";
  assert.equal(attention(d).priority, 2);
  d.latest_run.status = "OUTCOME_UNCERTAIN";
  assert.equal(attention(d).priority, 1);
  d.latest_run.status = "PARTIALLY_APPLIED";
  assert.equal(attention(d).priority, 1);
  assert.equal(runStatus("RUNNING", true).label, "Completion unconfirmed");
});
test("overview states explain evidence without declaring operational health", () => {
  const d = diagnostics();
  assert.match(overviewReason(d), /No problems reported/);
  d.overall_status = "DEGRADED";
  d.warnings = [staleWarning];
  d.stale_runs = [staleWarning];
  d.sources[0].warnings = ["STALE_RUNNING"];
  d.sources[0].status = "DEGRADED";
  assert.match(overviewReason(d), /unconfirmed completion/);
  d.components.registry.status = "UNAVAILABLE";
  assert.match(overviewReason(d), /unavailable/);
});
test("formatting preserves non-minute intervals and unknown duration", () => {
  assert.equal(interval(600), "10 min");
  assert.equal(interval(7200), "2 h");
  assert.equal(interval(61), "1 min 1 s");
  assert.equal(duration(134000), "2 min 14 s");
  assert.equal(duration(null), "Not recorded");
});
