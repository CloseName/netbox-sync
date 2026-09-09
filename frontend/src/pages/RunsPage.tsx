import {tr} from "../ui/i18n";
import { useCallback, useState } from "react";
import {
  Link,
  useLocation,
  useParams,
  useSearchParams,
} from "react-router-dom";
import { fetchRun, fetchRunPage } from "../api/runs";
import { fetchDiagnostics } from "../api/diagnostics";
import type { SyncRun } from "../api/runs";
import type { Diagnostics } from "../api/diagnostics";
import { runPath, sourcePath } from "../ui/routes";
import { Badge, EmptyState, PageHeader, Timestamp } from "../ui/primitives";
import { ResourceFeedback } from "../ui/ResourceFeedback";
import { useResource } from "../ui/useResource";
import { runStatus, runStates } from "../ui/status";
import { duration, interval } from "../ui/format";
import {
  actionLabels,
  planActions,
  planExplanation,
  runAttention,
  staleEvidence,
  staleExplanation,
} from "../ui/runEvidence";

export function RunsPage() {
  const { runId } = useParams();
  return runId ? <RunDetail id={runId} /> : <RunHistory />;
}
function RunHistory() {
  const [params, setParams] = useSearchParams();
  const sourceParam = params.get("source_instance") ?? "";
  const [draft, setDraft] = useState({
    origin: sourceParam,
    value: sourceParam,
  });
  const source = draft.origin === sourceParam ? draft.value : sourceParam;
  const query = new URLSearchParams();
  for (const key of [
    "source_instance",
    "source_type",
    "status",
    "trigger",
    "cursor",
  ]) {
    const value = params.get(key);
    if (value) query.set(key, value);
  }
  const update = (key: string, value: string) => {
    const next = new URLSearchParams(query);
    next.delete("cursor");
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next);
  };
  const clear = () => {
    setDraft({ origin: "", value: "" });
    setParams({});
  };
  return (
    <main className="operations-workspace">
      <PageHeader
        title={tr("Run history")}
        description={tr("Recorded manual and scheduled synchronization outcomes.")}
      />
      <form
        className="run-filters"
        onSubmit={(e) => {
          e.preventDefault();
          update("source_instance", source.trim());
        }}
      >
        <label>
          {tr("Source ID")}{" "}<input
            name="source"
            value={source}
            onChange={(e) =>
              setDraft({ origin: sourceParam, value: e.target.value })
            }
          />
        </label>
        <button type="submit">{tr("Filter source")}{" "}</button>
        <label>
          {tr("Provider")}{" "}<select
            value={params.get("source_type") ?? ""}
            onChange={(e) => update("source_type", e.target.value)}
          >
            <option value="">{tr("All providers")}{" "}</option>
            <option value="proxmox">{tr("Proxmox VE")}{" "}</option>
            <option value="esxi">{tr("VMware ESXi")}{" "}</option>
          </select>
        </label>
        <label>
          {tr("Outcome")}{" "}<select
            value={params.get("status") ?? ""}
            onChange={(e) => update("status", e.target.value)}
          >
            <option value="">{tr("All outcomes")}{" "}</option>
            {Object.entries(runStates).map(([k, v]) => (
              <option value={k} key={k}>
                {tr(v.label)}
              </option>
            ))}
          </select>
        </label>
        <label>
          {tr("Trigger")}{" "}<select
            value={params.get("trigger") ?? ""}
            onChange={(e) => update("trigger", e.target.value)}
          >
            <option value="">{tr("All triggers")}{" "}</option>
            <option value="manual">{tr("Manual")}{" "}</option>
            <option value="scheduled">{tr("Scheduled")}{" "}</option>
          </select>
        </label>
        <button type="button" onClick={clear}>
          {tr("Clear filters")}{" "}</button>
      </form>
      <RunResults
        key={query.toString()}
        query={query.toString()}
        clear={clear}
      />
    </main>
  );
}
function RunResults({ query, clear }: { query: string; clear: () => void }) {
  const [, setParams] = useSearchParams();
  const runs = useResource(
    useCallback(
      (signal) => fetchRunPage(new URLSearchParams(query), signal),
      [query],
    ),
  );
  const diagnostics = useResource(fetchDiagnostics);
  const filters = new URLSearchParams(query),
    cursor = filters.get("cursor");
  const filtered = ["source_instance", "source_type", "status", "trigger"].some(
    (k) => filters.has(k),
  );
  return (
    <>
      <div className="evidence-toolbar">
        <p className="muted">
          {tr(planExplanation)} {tr("Newest first; up to 50 runs per request.")}{" "}</p>
        <button
          disabled={runs.loading || diagnostics.loading}
          onClick={() => {
            runs.refresh();
            diagnostics.refresh();
          }}
        >
          {tr("Refresh")}{" "}</button>
      </div>
      <ResourceFeedback resource={runs} label={tr("history")} table />
      <ResourceFeedback
        resource={diagnostics}
        label={tr("diagnostic evidence")}
        evidenceAt={diagnostics.data?.generated_at}
      />
      {diagnostics.data && (
        <p className="muted">
          {tr("Stale evidence:")}{" "}<Timestamp value={diagnostics.data.generated_at} />{tr(". Up to 100 oldest stale runs; absence from this sample does not confirm completion.")}{" "}</p>
      )}
      {diagnostics.data &&
        diagnostics.data.components.run_history.status !== "HEALTHY" && (
          <p className="muted">
            {tr("Stale assessment unavailable: the run history check did not succeed.")}{" "}</p>
        )}
      {diagnostics.error && (
        <p className="muted">
          {tr("Recorded outcomes remain visible; diagnostic attention may be incomplete.")}{" "}</p>
      )}
      {runs.data && (
        <>
          {runs.data.runs.length ? (
            <RunTable
              runs={runs.data.runs}
              diagnostics={diagnostics.data}
              context={query}
            />
          ) : (
            <EmptyState
              title={
                cursor
                  ? tr("No older runs were returned.")
                  : filtered
                    ? tr("No runs match these filters.")
                    : tr("No runs have been recorded yet.")
              }
            >
              {filtered ? (
                <button onClick={clear}>{tr("Clear filters")}{" "}</button>
              ) : (
                !cursor && <Link to="/sources">{tr("Open Sources")}{" "}</Link>
              )}
            </EmptyState>
          )}
          <nav className="pagination" aria-label={tr("Run history pages")}>
            {cursor && (
              <button
                onClick={() => {
                  filters.delete("cursor");
                  setParams(filters);
                }}
              >
                {tr("Newest runs")}{" "}</button>
            )}
            <span>
              {runs.data.runs.length}{" "}
              {runs.data.runs.length === 1 ? tr("run") : tr("runs")} {tr("in this response")}{" "}</span>
            <button
              disabled={!runs.data.next_cursor || runs.loading}
              onClick={() => {
                if (runs.data?.next_cursor) {
                  filters.set("cursor", runs.data.next_cursor);
                  setParams(filters);
                }
              }}
            >
              {tr("Older runs")}{" "}</button>
          </nav>
        </>
      )}
    </>
  );
}
function RunTable({
  runs,
  diagnostics,
  context,
}: {
  runs: SyncRun[];
  diagnostics: Diagnostics | null;
  context: string;
}) {
  return (
    <div
      className="source-table run-table"
      role="region"
      aria-label={tr("Run history table")}
      tabIndex={0}
    >
      <table>
        <thead>
          <tr>
            {[
              "Started",
              "Source",
              "Trigger",
              "Outcome",
              "Duration",
              "Plan actions",
              "Attention",
            ].map((s, i) => (
              <th
                scope="col"
                className={
                  i === 4
                    ? "optional-duration"
                    : i === 5
                      ? "optional-actions"
                      : ""
                }
                key={s}
              >
                {s}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => {
            const stale = !!staleEvidence(
              run,
              run.source_instance,
              diagnostics,
            );
            return (
              <tr key={run.run_id}>
                <td>
                  <Link to={runPath(run.run_id)} state={{ runsQuery: context }}>
                    <Timestamp value={run.started_at} />
                  </Link>
                </td>
                <td>
                  <Link to={sourcePath(run.source_instance)}>
                    {run.source_instance}
                  </Link>
                  <small>
                    {run.source_type === "proxmox"
                      ? tr("Proxmox VE")
                      : tr("VMware ESXi")}
                  </small>
                </td>
                <td>{run.trigger === "manual" ? tr("Manual") : tr("Scheduled")}</td>
                <td>
                  <Link to={runPath(run.run_id)} state={{ runsQuery: context }}>
                    <Badge value={runStatus(run.status, stale)} />
                  </Link>
                </td>
                <td className="optional-duration">
                  {duration(run.duration_ms)}
                </td>
                <td className="optional-actions">{planActions(run)}</td>
                <td>{tr(runAttention(run, stale))}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
function RunDetail({ id }: { id: string }) {
  const run = useResource(useCallback((signal) => fetchRun(id, signal), [id]));
  const diagnostics = useResource(fetchDiagnostics);
  const location = useLocation();
  const query =
    typeof location.state?.runsQuery === "string"
      ? location.state.runsQuery
      : "";
  const data = run.data;
  const stale =
    data && staleEvidence(data, data.source_instance, diagnostics.data);
  return (
    <main className="operations-workspace">
      <PageHeader
        title={tr("Run details")}
        description={tr("Recorded outcome and supporting evidence.")}
        actions={
          <button
            disabled={run.loading || diagnostics.loading}
            onClick={() => {
              run.refresh();
              diagnostics.refresh();
            }}
          >
            {tr("Refresh")}{" "}</button>
        }
      />
      <p>
        <Link to={"/runs" + (query ? "?" + query : "")}>{tr("Back to runs")}{" "}</Link>
      </p>
      <ResourceFeedback resource={run} label={tr("run")} />
      {data && (
        <>
          <section className="source-panel">
            <h2>{tr("Outcome")}{" "}</h2>
            <dl className="source-facts">
              <div>
                <dt>{tr("Outcome")}{" "}</dt>
                <dd>
                  <Badge value={runStatus(data.status, !!stale)} />
                </dd>
              </div>
              <div>
                <dt>{tr("Source")}{" "}</dt>
                <dd>
                  <Link to={sourcePath(data.source_instance)}>
                    {data.source_instance}
                  </Link>
                  <small>
                    {data.source_type === "proxmox"
                      ? tr("Proxmox VE")
                      : tr("VMware ESXi")}
                  </small>
                </dd>
              </div>
              <div>
                <dt>{tr("Trigger")}{" "}</dt>
                <dd>{data.trigger === "manual" ? tr("Manual") : tr("Scheduled")}</dd>
              </div>
              <div>
                <dt>{tr("Started")}{" "}</dt>
                <dd>
                  <Timestamp value={data.started_at} />
                </dd>
              </div>
              <div>
                <dt>{tr("Duration")}{" "}</dt>
                <dd>{duration(data.duration_ms)}</dd>
              </div>
              <div>
                <dt>{tr("Attention")}{" "}</dt>
                <dd>{tr(runAttention(data, !!stale))}</dd>
              </div>
            </dl>
            {stale && (
              <div className="evidence-note">
                <p>{tr(staleExplanation)}</p>
                {stale.age_seconds !== null && (
                  <p>
                    {tr("Age at diagnostic snapshot:")}{" "}{interval(stale.age_seconds)}.
                  </p>
                )}
                <p>{stale.safe_message}</p>
              </div>
            )}
            {["OUTCOME_UNCERTAIN", "PARTIALLY_APPLIED"].includes(
              data.status,
            ) && (
              <p className="evidence-note">
                {tr("Verify the final state before planning another sync. Recorded plan counts do not confirm what was applied.")}{" "}</p>
            )}
          </section>
          <section className="source-panel">
            <h2>{tr("Plan actions")}{" "}</h2>
            <p className="muted">{tr(planExplanation)}</p>
            <dl className="source-facts">
              {Object.entries(actionLabels).map(([key, label]) => (
                <div key={key}>
                  <dt>{tr(label)}</dt>
                  <dd>{data.actions[key as keyof SyncRun["actions"]]}</dd>
                </div>
              ))}
            </dl>
          </section>
          <section className="source-panel">
            <h2>{tr("Result message")}{" "}</h2>
            <p>
              {data.error_message_safe ||
                "No additional result message was recorded."}
            </p>
            <h3>{tr("Recorded lifecycle")}{" "}</h3>
            <ol className="run-lifecycle">
              <li>
                {tr("Started:")}{" "}<Timestamp value={data.started_at} />
              </li>
              <li>
                {data.finished_at ? (
                  <>
                    {tr("Finished:")}{" "}<Timestamp value={data.finished_at} />
                  </>
                ) : stale ? (
                  tr("Completion unconfirmed")
                ) : (
                  tr("Completion timestamp not recorded")
                )}
              </li>
            </ol>
          </section>
          <section className="source-panel">
            <h2>{tr("Diagnostic evidence")}{" "}</h2>
            <ResourceFeedback
              resource={diagnostics}
              evidenceAt={diagnostics.data?.generated_at}
              label={tr("diagnostic evidence")}
            />
            {diagnostics.data && (
              <p>
                {tr("Snapshot:")}{" "}<Timestamp value={diagnostics.data.generated_at} />.{" "}
                {stale
                  ? tr("This run appears in the stale evidence.")
                  : tr("No matching stale evidence in this bounded snapshot; this does not establish completion.")}
              </p>
            )}
            <p>
              <Link to={sourcePath(data.source_instance) + "/diagnostics"}>
                {tr("Open source diagnostics")}{" "}</Link>{" "}
              · <Link to="/diagnostics">{tr("View system diagnostics")}{" "}</Link>
            </p>
          </section>
          <details className="source-panel">
            <summary>{tr("Technical details")}{" "}</summary>
            <dl className="technical-facts">
              {Object.entries({
                "Run ID": data.run_id,
                "Recorded status": data.status,
                "Plan digest": data.plan_digest,
                "Planner version": data.planner_version,
                "Safe code": data.error_code,
                "Started timestamp": data.started_at,
                "Finished timestamp": data.finished_at,
                "Created by": data.created_by,
              }).map(([label, value]) => (
                <div key={tr(label)}>
                  <dt>{tr(label)}</dt>
                  <dd>{value ?? tr("Not recorded")}</dd>
                </div>
              ))}
            </dl>
          </details>
        </>
      )}
    </main>
  );
}
