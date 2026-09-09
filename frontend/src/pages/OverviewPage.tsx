import {tr} from "../ui/i18n";
import { Link } from "react-router-dom";
import { fetchSources } from "../api/sources";
import { fetchDiagnostics } from "../api/diagnostics";
import { fetchRuns } from "../api/runs";
import { useResource } from "../ui/useResource";
import { ResourceNotice } from "../ui/ResourceNotice";
import {
  Badge,
  EmptyState,
  LoadingState,
  PageHeader,
  Timestamp,
} from "../ui/primitives";
import { healthStatus, runStatus } from "../ui/status";
import { duration } from "../ui/format";
import {
  composeSources,
  diagnosticsUsable,
  overviewReason,
} from "../ui/operations";
import { sourcePath, runPath } from "../ui/routes";
import { staleEvidence } from "../ui/runEvidence";
export function OverviewPage() {
  const sources = useResource(fetchSources),
    diagnostics = useResource(fetchDiagnostics),
    runs = useResource(fetchRuns);
  const data = diagnostics.data;
  const usable = diagnosticsUsable(data);
  const rows = composeSources(sources.data ?? [], data);
  const attention = rows
    .filter((row) => row.attention)
    .sort(
      (a, b) =>
        a.attention!.priority - b.attention!.priority ||
        a.source.source_instance.localeCompare(b.source.source_instance),
    )
    .slice(0, 5);
  const expected = usable
    ? data!.sources
        .filter((s) => s.enabled && s.sync_enabled && s.next_expected_at)
        .sort((a, b) => a.next_expected_at!.localeCompare(b.next_expected_at!))
        .slice(0, 5)
    : [];
  const refresh = () => {
    sources.refresh();
    diagnostics.refresh();
    runs.refresh();
  };
  const running = runs.data?.filter(
    (run) =>
      run.status === "RUNNING" &&
      !staleEvidence(run, run.source_instance, data),
  );
  return (
    <main>
      <PageHeader
        title={tr("Overview")}
        description={tr("Synchronization activity and the evidence behind it.")}
        actions={
          <button
            disabled={sources.loading || diagnostics.loading || runs.loading}
            onClick={refresh}
          >
            {tr("Refresh")}{" "}</button>
        }
      />
      <ResourceNotice
        resource={diagnostics}
        name="Diagnostics"
        retry={diagnostics.refresh}
      />
      <section
        className="panel overview-summary"
        aria-label={tr("Overall diagnostics")}
      >
        {data ? (
          <>
            <Badge
              value={healthStatus(data.overall_status)}
              code={data.overall_status}
            />
            <p>{tr(overviewReason(data))}</p>
            <small>
              {tr("Checked")}{" "}<Timestamp value={data.generated_at} />
            </small>
            <Link to="/diagnostics">{tr("Open diagnostics →")}{" "}</Link>
          </>
        ) : diagnostics.loading ? (
          <LoadingState label={tr("Loading diagnostic summary…")} />
        ) : (
          <p>{tr("Overall diagnostics unavailable.")}{" "}</p>
        )}
      </section>
      <div className="summary-panels">
        <section className="panel">
          <h2>{tr("Sources")}{" "}</h2>
          <ResourceNotice
            resource={sources}
            name="Sources"
            retry={sources.refresh}
          />
          {sources.data ? (
            <>
              <Link className="metric" to="/sources">
                {sources.data.length} {tr("registered")}{" "}</Link>
              {diagnostics.loading && !data ? (
                <LoadingState label={tr("Loading source diagnostic states…")} />
              ) : (
                <div className="status-counts">
                  {[
                    "HEALTHY",
                    "DEGRADED",
                    "UNHEALTHY",
                    "UNKNOWN",
                    "UNAVAILABLE",
                  ].map((status) => {
                    const count = rows.filter(
                      (row) =>
                        (row.diagnostic?.status ?? "UNAVAILABLE") === status,
                    ).length;
                    return (
                      <Link key={status} to={`/sources?health=${status}`}>
                        {tr(healthStatus(status).label)}: {count}
                      </Link>
                    );
                  })}
                </div>
              )}
            </>
          ) : sources.loading ? (
            <LoadingState />
          ) : (
            <p>{tr("Source count unavailable.")}{" "}</p>
          )}
        </section>
        <section className="panel">
          <h2>{tr("Activity")}{" "}</h2>
          {runs.data ? (
            <>
              <p>
                <Link to="/runs">
                  {running?.length} {tr("records marked as running in the latest")}{" "}{" "}
                  {runs.data.length} {tr("runs")}{" "}</Link>
              </p>
              <p className="muted">{tr("Recorded status; not a live worker check.")}{" "}</p>
            </>
          ) : runs.loading ? (
            <LoadingState />
          ) : (
            <p>{tr("Recent activity unavailable.")}{" "}</p>
          )}
          {data && data.components.run_history.status === "HEALTHY" ? (
            <p>
              <Link to="/diagnostics">
                {tr("Completion unconfirmed:")}{" "}{data.stale_runs.length} {tr("returned run records")}{" "}</Link>
              <small>
                {tr("Diagnostic selection is limited to 100; not a global total.")}{" "}</small>
            </p>
          ) : (
            <p>{tr("Stale record evidence unavailable.")}{" "}</p>
          )}
        </section>
      </div>
      <div className="overview-grid">
        <section className="panel">
          <h2>{tr("Needs attention")}{" "}</h2>
          {data &&
            Object.entries(data.components)
              .filter(([, c]) => ["UNAVAILABLE", "DEGRADED"].includes(c.status))
              .map(([key, c]) => (
                <p key={key}>
                  <Link to="/diagnostics">
                    {key.replaceAll("_", " ")}: {tr(healthStatus(c.status).label)}
                  </Link>
                </p>
              ))}
          {!sources.data || !usable ? (
            <p>{tr("Source attention cannot be fully evaluated.")}{" "}</p>
          ) : attention.length ? (
            <ul className="activity-list">
              {attention.map((row) => (
                <li key={row.source.source_instance}>
                  <Link to={sourcePath(row.source.source_instance)}>
                    {row.source.name}
                  </Link>
                  <span>{tr(row.attention!.label)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p>{tr("No source attention items reported.")}{" "}</p>
          )}
          {data?.stale_runs.slice(0, 3).map((w) => (
            <p key={w.run_id ?? w.source_instance}>
              {w.run_id ? (
                <Link to={runPath(w.run_id)}>
                  {tr("Completion unconfirmed:")}{" "}{w.source_instance}
                </Link>
              ) : (
                tr("Completion unconfirmed")
              )}
            </p>
          ))}
          <Link to="/sources?attention=yes">
            {tr("View sources needing attention →")}{" "}</Link>
        </section>
        <section className="panel">
          <h2>{tr("Next expected")}{" "}</h2>
          {!usable ? (
            <p>{tr("Schedule evidence unavailable.")}{" "}</p>
          ) : expected.length ? (
            <ul className="activity-list">
              {expected.map((s) => (
                <li key={s.source_instance}>
                  <Link to={sourcePath(s.source_instance)}>
                    {sources.data?.find(
                      (source) => source.source_instance === s.source_instance,
                    )?.name ?? s.source_instance}
                  </Link>
                  <Timestamp value={s.next_expected_at} />
                </li>
              ))}
            </ul>
          ) : (
            <p>{tr("No next expected runs reported.")}{" "}</p>
          )}
          <p className="muted">
            {tr("Expected times are derived from configuration and history; start times are not guaranteed.")}{" "}</p>
        </section>
      </div>
      <section className="panel">
        <h2>{tr("Recent runs")}{" "}</h2>
        <ResourceNotice
          resource={runs}
          name="Run history"
          retry={runs.refresh}
        />
        {runs.data ? (
          runs.data.length ? (
            <div
              className="scroll-region"
              tabIndex={0}
              role="region"
              aria-label={tr("Recent runs")}
            >
              <table>
                <caption className="sr-only">
                  {tr("Latest eight recorded runs")}{" "}</caption>
                <thead>
                  <tr>
                    <th scope="col">{tr("Source")}{" "}</th>
                    <th scope="col">{tr("Started")}{" "}</th>
                    <th scope="col">{tr("Trigger")}{" "}</th>
                    <th scope="col">{tr("Outcome")}{" "}</th>
                    <th scope="col">{tr("Duration")}{" "}</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.data.slice(0, 8).map((run) => (
                    <tr key={run.run_id}>
                      <th scope="row">
                        <Link to={sourcePath(run.source_instance)}>
                          {sources.data?.find(
                            (s) => s.source_instance === run.source_instance,
                          )?.name ?? run.source_instance}
                        </Link>
                      </th>
                      <td>
                        <Link to={runPath(run.run_id)}>
                          <Timestamp value={run.started_at} />
                        </Link>
                      </td>
                      <td>{tr(run.trigger)}</td>
                      <td>
                        <Badge
                          value={runStatus(
                            run.status,
                            !!staleEvidence(run, run.source_instance, data),
                          )}
                          code={run.status}
                        />
                      </td>
                      <td>{duration(run.duration_ms)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState title={tr("No runs have been recorded yet.")}>
              <Link to="/sources">{tr("Open Sources")}{" "}</Link>
            </EmptyState>
          )
        ) : runs.loading ? (
          <LoadingState table label={tr("Loading recent runs…")} />
        ) : (
          <p>{tr("No run data available.")}{" "}</p>
        )}
        <Link to="/runs">{tr("Open run history →")}{" "}</Link>
      </section>
    </main>
  );
}
