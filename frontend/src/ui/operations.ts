import type { Source } from "../api/sources.ts";
import type { Diagnostics, SourceDiagnostic } from "../api/diagnostics.ts";
export interface Attention {
  priority: number;
  label: string;
}
export function attention(source?: SourceDiagnostic): Attention | null {
  if (!source) return null;
  const outcome = source.latest_run?.status;
  if (outcome === "OUTCOME_UNCERTAIN" || outcome === "PARTIALLY_APPLIED")
    return {
      priority: 1,
      label:
        outcome === "OUTCOME_UNCERTAIN"
          ? "Outcome unknown"
          : "Partially applied",
    };
  if (source.status === "UNHEALTHY" || source.status === "UNAVAILABLE")
    return {
      priority: 2,
      label: source.status === "UNHEALTHY" ? "Unhealthy" : "Status unavailable",
    };
  if (source.warnings.includes("STALE_RUNNING"))
    return { priority: 3, label: "Completion unconfirmed" };
  if (source.warnings.includes("SCHEDULED_ACTIVITY_DELAYED"))
    return { priority: 4, label: "Later than expected" };
  if (
    outcome &&
    ["FAILED", "FAILED_BEFORE_WRITE", "BLOCKED", "LOCKED"].includes(outcome)
  )
    return { priority: 5, label: "Last run needs attention" };
  if (source.status === "DEGRADED" || source.warning_count)
    return { priority: 6, label: "Needs attention" };
  return null;
}
export function diagnosticsUsable(data: Diagnostics | null): boolean {
  return (
    !!data &&
    data.components.registry.status === "HEALTHY" &&
    data.components.run_history.status === "HEALTHY"
  );
}
export function diagnosticIndex(
  data: Diagnostics | null,
): Map<string, SourceDiagnostic> {
  return new Map(
    diagnosticsUsable(data)
      ? data!.sources.map((source) => [source.source_instance, source])
      : [],
  );
}
export interface SourceRow {
  source: Source;
  diagnostic?: SourceDiagnostic;
  attention: Attention | null;
}
export function composeSources(
  sources: Source[],
  diagnostics: Diagnostics | null,
): SourceRow[] {
  const index = diagnosticIndex(diagnostics);
  return sources.map((source) => {
    const diagnostic = index.get(source.source_instance);
    return { source, diagnostic, attention: attention(diagnostic) };
  });
}
export function sourceQuery(params: URLSearchParams) {
  const oneOf = (name: string, values: string[], fallback = "") =>
    values.includes(params.get(name) ?? "") ? params.get(name)! : fallback;
  return {
    q: params.get("q") ?? "",
    provider: oneOf("provider", ["proxmox", "esxi"]),
    health: oneOf("health", [
      "HEALTHY",
      "DEGRADED",
      "UNHEALTHY",
      "UNKNOWN",
      "UNAVAILABLE",
    ]),
    schedule: oneOf("schedule", ["on", "off"]),
    attention: oneOf("attention", ["yes", "no", "unknown"]),
    site: params.get("site") ?? "",
    sort: oneOf("sort", ["name", "last", "next", "attention"], "name"),
    direction: oneOf("direction", ["asc", "desc"], "asc"),
    size: Number(oneOf("size", ["25", "50", "100"], "25")),
    page: Math.max(
      1,
      Math.min(1000000, Math.floor(Number(params.get("page")) || 1)),
    ),
  };
}
export function querySources(rows: SourceRow[], params: URLSearchParams) {
  const query = sourceQuery(params);
  const text = query.q.toLocaleLowerCase().trim();
  const filtered = rows.filter(
    ({ source: s, diagnostic: d, attention: a }) =>
      (!text ||
        [
          s.name,
          s.source_instance,
          s.address,
          s.site_slug,
          s.cluster_name,
        ].some((value) => value.toLocaleLowerCase().includes(text))) &&
      (!query.provider || s.type === query.provider) &&
      (!query.site || s.site_slug === query.site) &&
      (!query.health || (d?.status ?? "UNAVAILABLE") === query.health) &&
      (!query.schedule ||
        (s.enabled && s.sync_enabled ? "on" : "off") === query.schedule) &&
      (!query.attention ||
        (d ? (a ? "yes" : "no") : "unknown") === query.attention),
  );
  filtered.sort((a, b) => {
    let result = 0;
    if (query.sort === "name")
      result = a.source.name.localeCompare(b.source.name);
    else {
      const value = (row: SourceRow) =>
        query.sort === "attention"
          ? (row.attention?.priority ?? null)
          : query.sort === "last"
            ? row.diagnostic?.latest_run?.started_at
            : row.diagnostic?.next_expected_at;
      const av = value(a),
        bv = value(b);
      if (av == null || bv == null)
        return av == null && bv == null
          ? a.source.source_instance.localeCompare(b.source.source_instance)
          : av == null
            ? 1
            : -1;
      result = av < bv ? -1 : av > bv ? 1 : 0;
    }
    return (
      result * (query.direction === "desc" ? -1 : 1) ||
      a.source.source_instance.localeCompare(b.source.source_instance)
    );
  });
  const page = Math.min(
    query.page,
    Math.max(1, Math.ceil(filtered.length / query.size)),
  );
  return {
    rows: filtered.slice((page - 1) * query.size, page * query.size),
    total: filtered.length,
    page,
    query,
  };
}
export function overviewReason(data: Diagnostics): string {
  if (Object.values(data.components).some((c) => c.status === "UNAVAILABLE"))
    return "Some diagnostics are unavailable.";
  if (data.sources.some((s) => s.status === "UNHEALTHY"))
    return "A source reports a synchronization problem.";
  if (
    data.warnings.length &&
    data.warnings.every((w) => w.warning_code === "STALE_RUNNING") &&
    !data.sources.some((s) =>
      [
        "FAILED",
        "FAILED_BEFORE_WRITE",
        "PARTIALLY_APPLIED",
        "OUTCOME_UNCERTAIN",
        "BLOCKED",
        "LOCKED",
      ].includes(s.latest_run?.status ?? ""),
    ) &&
    !Object.values(data.components).some((c) => c.status === "DEGRADED")
  )
    return "Some runs have unconfirmed completion.";
  if (data.overall_status !== "HEALTHY")
    return "Synchronization needs attention.";
  return "No problems reported.";
}
