import {tr} from "../ui/i18n";
import { SourceFilters } from "../ui/SourceFilters";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import { fetchSources } from "../api/sources";
import { fetchDiagnostics } from "../api/diagnostics";
import { useResource } from "../ui/useResource";
import { ResourceNotice } from "../ui/ResourceNotice";
import {
  Badge,
  EmptyState,
  LoadingState,
  PageHeader,
  Pagination,
  Timestamp,
} from "../ui/primitives";
import { healthStatus, runStatus } from "../ui/status";
import { interval } from "../ui/format";
import { composeSources, querySources } from "../ui/operations";
import { sourcePath, runPath } from "../ui/routes";
import { staleEvidence } from "../ui/runEvidence";
export function SourcesListPage() {
  const sources = useResource(fetchSources),
    diagnostics = useResource(fetchDiagnostics);
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  const result = querySources(
    composeSources(sources.data ?? [], diagnostics.data),
    params,
  );
  // Browser history changes before React commits a navigation transition.
  // Read that URL so rapid filter edits cannot resurrect a just-cleared query.
  const change = (key: string, value: string) => {
    const next = new URLSearchParams(window.location.search);
    value ? next.set(key, value) : next.delete(key);
    if (key !== "page") next.delete("page");
    setParams(next, { replace: key === "q" });
  };
  const refresh = () => {
    sources.refresh();
    diagnostics.refresh();
  };
  const sort = (key: string) => {
    const next = new URLSearchParams(window.location.search);
    next.set("sort", key);
    next.set(
      "direction",
      result.query.sort === key && result.query.direction === "asc"
        ? "desc"
        : "asc",
    );
    next.delete("page");
    setParams(next);
  };
  const heading = (label: string, key: string) => (
    <th
      scope="col"
      aria-sort={
        result.query.sort === key
          ? result.query.direction === "asc"
            ? "ascending"
            : "descending"
          : "none"
      }
    >
      <button className="sort-button" onClick={() => sort(key)}>
        {tr(label)}{" "}
        {result.query.sort === key
          ? result.query.direction === "asc"
            ? "↑"
            : "↓"
          : "↕"}
      </button>
    </th>
  );
  return (
    <main>
      <PageHeader
        title={tr("Sources")}
        description={tr("Source configuration and synchronization evidence.")}
        actions={
          <>
            <button
              disabled={sources.loading || diagnostics.loading}
              onClick={refresh}
            >
              {tr("Refresh")}{" "}</button>
            <Link className="button primary" to="/sources/add">
              {tr("Add Source")}{" "}</Link>
          </>
        }
      />
      <ResourceNotice
        resource={sources}
        name="Sources"
        retry={sources.refresh}
      />
      <ResourceNotice
        resource={diagnostics}
        name="Diagnostics"
        retry={diagnostics.refresh}
      />
      <SourceFilters
        query={result.query}
        sites={(sources.data ?? []).map((source) => source.site_slug)}
        change={change}
        clear={() => setParams({})}
      />
      {sources.loading && !sources.data ? (
        <LoadingState table label={tr("Loading sources…")} />
      ) : (
        sources.data &&
        (sources.data.length === 0 ? (
          <EmptyState title={tr("No sources have been registered.")}>
            <Link to="/sources/add">{tr("Add Source")}{" "}</Link>
          </EmptyState>
        ) : result.total === 0 ? (
          <EmptyState title={tr("No sources match these filters.")}>
            <button onClick={() => setParams({})}>{tr("Clear filters")}{" "}</button>
          </EmptyState>
        ) : (
          <>
            <div
              className="source-table scroll-region"
              tabIndex={0}
              role="region"
              aria-label={tr("Sources table")}
            >
              <table>
                <caption className="sr-only">
                  {tr("Registered sources with configuration and diagnostic evidence")}{" "}</caption>
                <thead>
                  <tr>
                    {heading("Source", "name")}
                    <th scope="col">{tr("Provider")}{" "}</th>
                    <th scope="col">{tr("Target")}{" "}</th>
                    <th scope="col">{tr("Sync status")}{" "}</th>
                    <th scope="col">{tr("Schedule")}{" "}</th>
                    {heading("Last run", "last")}
                    {heading("Attention", "attention")}
                    <th scope="col">{tr("Actions")}{" "}</th>
                  </tr>
                </thead>
                <tbody>
                  {result.rows.map(
                    ({ source: s, diagnostic: d, attention: a }) => (
                      <tr key={s.source_instance}>
                        <th scope="row">
                          <Link
                            to={sourcePath(s.source_instance)}
                            state={{
                              from: location.pathname + location.search,
                            }}
                          >
                            {s.name}
                          </Link>
                          {s.name !== s.source_instance && (
                            <small>{s.source_instance}</small>
                          )}
                          {!s.enabled && <small>{tr("Source disabled")}{" "}</small>}
                        </th>
                        <td>
                          {s.type === "proxmox" ? tr("Proxmox VE") : tr("VMware ESXi")}
                        </td>
                        <td>
                          {s.site_slug}
                          <small>{s.cluster_name}</small>
                        </td>
                        <td>
                          {d ? (
                            <Badge
                              value={healthStatus(d.status)}
                              code={d.status}
                            />
                          ) : (
                            <span className="muted">{tr("Status unavailable")}{" "}</span>
                          )}
                          {!d && diagnostics.loading && (
                            <small>{tr("Loading diagnostics…")}{" "}</small>
                          )}
                        </td>
                        <td>
                          {s.enabled && s.sync_enabled ? (
                            <>{tr("Every")}{" "}{interval(s.sync_interval_seconds)}</>
                          ) : (
                            tr("Automatic sync off")
                          )}
                          {!s.enabled && s.sync_enabled && (
                            <small>{tr("Configured on; source disabled")}{" "}</small>
                          )}
                          {d?.next_expected_at &&
                            s.enabled &&
                            s.sync_enabled && (
                              <small className="secondary-cell">
                                {tr("Expected")}{" "}{" "}
                                <Timestamp value={d.next_expected_at} />
                              </small>
                            )}
                        </td>
                        <td>
                          {d?.latest_run ? (
                            <>
                              <Link to={runPath(d.latest_run.run_id)}>
                                <Badge
                                  value={runStatus(
                                    d.latest_run.status,
                                    !!staleEvidence(
                                      d.latest_run,
                                      s.source_instance,
                                      diagnostics.data,
                                    ),
                                  )}
                                />
                              </Link>
                              <small>
                                <Timestamp value={d.latest_run.started_at} />
                              </small>
                            </>
                          ) : d ? (
                            tr("No recorded run")
                          ) : (
                            tr("Unavailable")
                          )}
                        </td>
                        <td>
                          {a ? (
                            <Link to={sourcePath(s.source_instance)}>
                              {tr(a.label)}
                            </Link>
                          ) : d ? (
                            tr("None reported")
                          ) : (
                            tr("Unavailable")
                          )}
                        </td>
                        <td>
                          <Link
                            aria-label={`Open ${s.name}`}
                            to={sourcePath(s.source_instance)}
                            state={{
                              from: location.pathname + location.search,
                            }}
                          >
                            {tr("Open")}{" "}</Link>
                        </td>
                      </tr>
                    ),
                  )}
                </tbody>
              </table>
            </div>
            <Pagination
              page={result.page}
              size={result.query.size}
              total={result.total}
              change={change}
            />
          </>
        ))
      )}
      <p className="muted evidence">
        {tr("Sources received")}{" "}<Timestamp value={sources.received} /> {tr("· Diagnostics checked")}{" "}<Timestamp value={diagnostics.data?.generated_at} />{tr(". Configuration is not a connectivity check.")}{" "}</p>
    </main>
  );
}
