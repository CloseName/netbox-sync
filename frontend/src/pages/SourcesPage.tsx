import {useLanguage} from "../ui/language";
import {tr} from "../ui/i18n";
import { useCallback, useEffect, useState } from "react";
import { Link, NavLink, useLocation, useParams } from "react-router-dom";
import { fetchSource, SourceNotFoundError } from "../api/sources";
import type { Source } from "../api/sources";
import { fetchSchedule } from "../api/schedule";
import { fetchDiagnostics } from "../api/diagnostics";
import type { DiagnosticRun, Diagnostics } from "../api/diagnostics";
import { fetchSourceRuns } from "../api/runs";
import { useResource } from "../ui/useResource";
import { diagnosticIndex, attention } from "../ui/operations";
import {
  Badge,
  Timestamp,
  Alert,
  LoadingState,
  PageHeader,
} from "../ui/primitives";
import { healthStatus, runStatus, scheduleStates } from "../ui/status";
import { duration } from "../ui/format";
import { sourcePath, runPath } from "../ui/routes";
import { SourceLifecyclePanel, RemovedSource, RemovedSourceLookup } from "./SourceLifecycle";
import type { SourceLifecycle } from "../api/lifecycle";
import { SourceSync } from "./SourceSync";
import { SourceSchedule, ScheduleSummary } from "./SourceSchedule";
import { DiagnosticAttention } from "../ui/DiagnosticAttention";
import { staleEvidence } from "../ui/runEvidence";
export const sourceTabs = [
  "Overview",
  "Sync",
  "Runs",
  "Schedule",
  "Diagnostics",
  "Configuration",
];
function RunEvidence({
  run,
  stale = false,
}: {
  run: DiagnosticRun | null;
  stale?: boolean;
}) {
  return run ? (
    <>
      <Link to={runPath(run.run_id)}>
        <Badge value={runStatus(run.status, stale)} />
      </Link>{" "}
      <Timestamp value={run.started_at} />
    </>
  ) : (
    <>{tr("No run recorded")}{" "}</>
  );
}
export function SourcesPage() {
  const [language]=useLanguage();
  const { sourceInstance = "", "*": suffix = "" } = useParams();
  const tab = suffix
    ? sourceTabs.find((item) => item.toLowerCase() === suffix)
    : "Overview";
  const location = useLocation();
  const [from] = useState(() =>
    typeof location.state?.from === "string" &&
    /^\/sources(?:\?|$)/.test(location.state.from)
      ? location.state.from
      : "/sources",
  );
  const source = useResource(
    useCallback(
      (signal) => fetchSource(sourceInstance, signal),
      [sourceInstance],
    ),
  );
  const schedule = useResource(
    useCallback(
      (signal) => fetchSchedule(sourceInstance, signal),
      [sourceInstance],
    ),
  );
  const diagnostics = useResource(fetchDiagnostics);
  const detail = source.data;
  const [removed, setRemoved] = useState<SourceLifecycle | null>(null);
  const evidence = diagnosticIndex(diagnostics.data).get(sourceInstance);
  const concern = attention(evidence);
  const base = sourcePath(sourceInstance);
  useEffect(() => {
    document.title = `${detail?.name ?? sourceInstance}${tab && tab !== "Overview" ? " / " + tr(tab) : ""} | NetBox Sync`;
  }, [detail?.name, sourceInstance, tab, language]);
  if (removed?.source_instance === sourceInstance) return <RemovedSource value={removed} />;
  if (source.failure instanceof SourceNotFoundError) return <RemovedSourceLookup source={sourceInstance} />;
  if (!tab)
    return (
      <main>
        <h1>{tr("Page not found")}{" "}</h1>
        <Link to={base}>{tr("Open source overview")}{" "}</Link>
      </main>
    );
  return (
    <main className="source-workspace">
      <nav aria-label={tr("Breadcrumb")}>
        <ol className="breadcrumbs">
          <li>
            <Link to="/sources">{tr("Sources")}{" "}</Link>
          </li>
          <li>
            {tab === "Overview" ? (
              <span aria-current="page">{detail?.name ?? sourceInstance}</span>
            ) : (
              <Link to={base} state={{ from }}>
                {detail?.name ?? sourceInstance}
              </Link>
            )}
          </li>
          {tab !== "Overview" && (
            <li>
              <span aria-current="page">{tr(tab)}</span>
            </li>
          )}
        </ol>
      </nav>
      <Link to={from}>{tr("Back to sources")}{" "}</Link>
      {source.loading && !detail && (
        <LoadingState label={tr("Loading source configuration…")} />
      )}
      {source.error && (
        <>
          <h1>
            {source.failure instanceof SourceNotFoundError
              ? tr("Source not found")
              : tr("Source unavailable")}
          </h1>
          <Alert retry={source.refresh}>
            {source.failure instanceof SourceNotFoundError
              ? tr("This source does not exist in the registry.")
              : tr("Source configuration could not be loaded. Retry without leaving this route.")}
          </Alert>
        </>
      )}
      {detail && !source.error && (
        <>
          <header className="source-header">
            <PageHeader
              title={detail.name}
              description={
                detail.type === "proxmox" ? tr("Proxmox VE") : tr("VMware ESXi")
              }
              actions={
                tab === "Overview" ? (
                  <Link
                    className="button primary"
                    to={base + "/sync"}
                    state={{ from }}
                  >
                    {tr("Open Sync")}{" "}</Link>
                ) : undefined
              }
            />
            <p className="muted source-identity">
              <code>{detail.source_instance}</code> {tr("· Site")}{" "}{detail.site_slug} /{" "}
              {detail.cluster_name}
            </p>
            <dl className="source-header-signals">
              <div>
                <dt>{tr("Source")}{" "}</dt>
                <dd>
                  <Badge
                    value={{
                      label: detail.enabled ? "Enabled" : "Disabled",
                      tone: detail.enabled ? "info" : "neutral",
                      icon: detail.enabled ? "✓" : "−",
                    }}
                  />
                </dd>
              </div>
              <div>
                <dt>{tr("Automatic sync")}{" "}</dt>
                <dd>
                  {schedule.data
                    ? schedule.data.sync_enabled
                      ? tr("On")
                      : tr("Off")
                    : tr("Unavailable")}
                  {schedule.error && schedule.data && tr(" (last loaded)")}
                </dd>
              </div>
              <div>
                <dt>{tr("Last run")}{" "}</dt>
                <dd>
                  {evidence ? (
                    <RunEvidence
                      run={evidence.latest_run}
                      stale={
                        !!(
                          evidence.latest_run &&
                          staleEvidence(
                            evidence.latest_run,
                            sourceInstance,
                            diagnostics.data,
                          )
                        )
                      }
                    />
                  ) : (
                    tr("Unavailable")
                  )}
                </dd>
              </div>
              <div>
                <dt>{tr("Last successful sync")}{" "}</dt>
                <dd>
                  {evidence ? (
                    <Timestamp value={evidence.latest_success_at} />
                  ) : (
                    tr("Unavailable")
                  )}
                </dd>
              </div>
              <div>
                <dt>{tr("Attention")}{" "}</dt>
                <dd>
                  {concern ? (
                    <Link to={base + "/diagnostics"} state={{ from }}>
                      {tr(concern.label)}
                    </Link>
                  ) : evidence ? (
                    evidence.status === "UNKNOWN" ? (
                      tr("Not verified")
                    ) : (
                      tr("None reported")
                    )
                  ) : (
                    tr("Unavailable")
                  )}
                </dd>
              </div>
            </dl>
          </header>
          <nav className="source-tabs" aria-label={tr("Source sections")}>
            {sourceTabs.map((item) => (
              <NavLink
                key={item}
                end
                to={
                  base + (item === "Overview" ? "" : "/" + item.toLowerCase())
                }
                state={{ from }}
              >
                {item}
              </NavLink>
            ))}
          </nav>
          {schedule.error && tab !== "Schedule" && (
            <Alert>
              {tr("Schedule unavailable.")}{" "}{" "}
              <Link to={base + "/schedule"} state={{ from }}>
                {tr("Open schedule to retry")}{" "}</Link>
            </Alert>
          )}
          {diagnostics.error && (
            <Alert retry={diagnostics.refresh}>
              {tr("Diagnostics unavailable.")}{" "}{diagnostics.data && (
                <>
                  {" "}
                  {tr("Could not refresh. Showing data from")}{" "}{" "}
                  <Timestamp value={diagnostics.data.generated_at} />.
                </>
              )}
            </Alert>
          )}
          {tab === "Overview" && (
            <>
              <h2>{tr("Source overview")}{" "}</h2>
              <div className="source-panels">
                <section className="source-panel">
                  <h3>{tr("Recent activity")}{" "}</h3>
                  <dl className="source-facts">
                    <div>
                      <dt>{tr("Last run")}{" "}</dt>
                      <dd>
                        {evidence ? (
                          <RunEvidence
                            run={evidence.latest_run}
                            stale={
                              !!(
                                evidence.latest_run &&
                                staleEvidence(
                                  evidence.latest_run,
                                  sourceInstance,
                                  diagnostics.data,
                                )
                              )
                            }
                          />
                        ) : (
                          tr("Unavailable")
                        )}
                      </dd>
                    </div>
                    <div>
                      <dt>{tr("Last success")}{" "}</dt>
                      <dd>
                        {evidence ? (
                          <Timestamp value={evidence.latest_success_at} />
                        ) : (
                          tr("Unavailable")
                        )}
                      </dd>
                    </div>
                    <div>
                      <dt>{tr("Diagnostics")}{" "}</dt>
                      <dd>
                        <Badge value={healthStatus(evidence?.status)} />
                      </dd>
                    </div>
                  </dl>
                  <Link to={base + "/runs"} state={{ from }}>
                    {tr("View source runs")}{" "}</Link>
                </section>
                <section className="source-panel">
                  <h3>{tr("Schedule summary")}{" "}</h3>
                  {schedule.data ? (
                    <ScheduleSummary
                      schedule={schedule.data}
                      evidence={evidence}
                    />
                  ) : (
                    <p>{tr("Schedule unavailable.")}{" "}</p>
                  )}
                  <Link to={base + "/schedule"} state={{ from }}>
                    {tr("Manage schedule")}{" "}</Link>
                </section>
                <section className="source-panel">
                  <h3>{tr("NetBox target")}{" "}</h3>
                  <dl className="source-facts">
                    <div>
                      <dt>{tr("Site")}{" "}</dt>
                      <dd>{detail.site_slug}</dd>
                    </div>
                    <div>
                      <dt>{tr("Cluster")}{" "}</dt>
                      <dd>{detail.cluster_name}</dd>
                    </div>
                  </dl>
                  <Link to={base + "/configuration"} state={{ from }}>
                    {tr("View configuration")}{" "}</Link>
                </section>
                <section className="source-panel">
                  <h3>{tr("Attention")}{" "}</h3>
                  <p>
                    {tr(concern?.label ??
                      (evidence
                        ? evidence.status === "UNKNOWN"
                          ? "Not verified"
                          : "No attention reported in this evidence."
                        : "Source evidence unavailable."))}
                  </p>
                  <p className="muted">
                    {tr("Registry configuration and recorded activity do not verify provider connectivity or authentication.")}{" "}</p>
                  <Link to={base + "/diagnostics"} state={{ from }}>
                    {tr("View source diagnostics")}{" "}</Link>
                </section>
              </div>
            </>
          )}
          {/* Keep local operations and edits mounted across tabs; the route wrapper remounts by source identity. */}
          <div hidden={tab !== "Sync"}>
            <SourceSync detail={detail} active={tab === "Sync"} />
          </div>
          <div hidden={tab !== "Schedule"}>
            <SourceSchedule
              instance={sourceInstance}
              sourceEnabled={detail.enabled}
              resource={schedule}
              evidence={evidence}
              afterSave={diagnostics.refresh}
            />
          </div>
          {tab === "Runs" && (
            <SourceRuns
              instance={sourceInstance}
              diagnostics={diagnostics.data}
            />
          )}
          {tab === "Diagnostics" && (
            <section className="source-panel">
              <div className="page-heading">
                <h2>{tr("Source diagnostics")}{" "}</h2>
                <button
                  disabled={diagnostics.loading}
                  onClick={diagnostics.refresh}
                >
                  {tr("Refresh evidence")}{" "}</button>
              </div>
              {diagnostics.loading && (
                <LoadingState label={tr("Loading evidence…")} />
              )}
              <dl className="source-facts">
                <div>
                  <dt>{tr("Diagnostic status")}{" "}</dt>
                  <dd>
                    <Badge value={healthStatus(evidence?.status)} />
                  </dd>
                </div>
                <div>
                  <dt>{tr("Scheduled activity (at evidence time)")}{" "}</dt>
                  <dd>
                    {evidence ? (
                      <Badge value={scheduleStates[evidence.scheduler_state]} />
                    ) : (
                      tr("Unavailable")
                    )}
                  </dd>
                </div>
                <div>
                  <dt>{tr("Last run")}{" "}</dt>
                  <dd>
                    {evidence ? (
                      <RunEvidence
                        run={evidence.latest_run}
                        stale={
                          !!(
                            evidence.latest_run &&
                            staleEvidence(
                              evidence.latest_run,
                              sourceInstance,
                              diagnostics.data,
                            )
                          )
                        }
                      />
                    ) : (
                      tr("Unavailable")
                    )}
                  </dd>
                </div>
                <div>
                  <dt>{tr("Last success")}{" "}</dt>
                  <dd>
                    {evidence ? (
                      <Timestamp value={evidence.latest_success_at} />
                    ) : (
                      tr("Unavailable")
                    )}
                  </dd>
                </div>
                <div>
                  <dt>{tr("Evidence timestamp")}{" "}</dt>
                  <dd>
                    <Timestamp value={diagnostics.data?.generated_at} />
                  </dd>
                </div>
              </dl>
              <h3>{tr("Attention")}{" "}</h3>
              {diagnostics.data && (
                <DiagnosticAttention
                  data={diagnostics.data}
                  source={sourceInstance}
                />
              )}
              <p className="muted">
                {tr("Evidence is derived from persisted activity. It does not prove source connectivity or a live scheduler heartbeat.")}{" "}</p>
              <Link to="/diagnostics">{tr("Open system diagnostics")}{" "}</Link>
              <details>
                <summary>{tr("Technical details")}{" "}</summary>
                <p>
                  {tr("Source:")}{" "}<code>{sourceInstance}</code>
                </p>
                <p>{tr("Diagnostic status:")}{" "}{evidence?.status ?? "UNAVAILABLE"}</p>
                <p>
                  {tr("Warning codes:")}{" "}{" "}
                  {evidence?.warnings.join(", ") || tr("None available")}
                </p>
              </details>
            </section>
          )}
          {tab === "Configuration" && (<>
            <SourceConfiguration
              source={detail}
              scheduleLink={base + "/schedule"}
            />
            <SourceLifecyclePanel source={detail} onRemoved={setRemoved} />
          </>)}
        </>
      )}
    </main>
  );
}
function SourceRuns({
  instance,
  diagnostics,
}: {
  instance: string;
  diagnostics: Diagnostics | null;
}) {
  const resource = useResource(
    useCallback((signal) => fetchSourceRuns(instance, signal), [instance]),
  );
  return (
    <section className="source-panel">
      <div className="page-heading">
        <h2>{tr("Source runs")}{" "}</h2>
        <button disabled={resource.loading} onClick={resource.refresh}>
          {tr("Refresh runs")}{" "}</button>
      </div>
      <p className="muted">
        {tr("Latest 50 runs for this source. Action counts describe the recorded plan, not confirmed applied changes.")}{" "}</p>
      {resource.loading && <LoadingState />}
      {resource.error && (
        <Alert retry={resource.refresh}>
          {tr("Source history unavailable.")}{" "}{resource.data && tr(" Showing previously loaded runs.")}
        </Alert>
      )}
      {resource.data &&
        (resource.data.length ? (
          <div className="source-table">
            <table>
              <thead>
                <tr>
                  <th>{tr("Outcome")}{" "}</th>
                  <th>{tr("Trigger")}{" "}</th>
                  <th>{tr("Started")}{" "}</th>
                  <th>{tr("Duration")}{" "}</th>
                  <th>{tr("Plan action counts")}{" "}</th>
                </tr>
              </thead>
              <tbody>
                {resource.data.map((run) => (
                  <tr key={run.run_id}>
                    <td>
                      <Link to={runPath(run.run_id)}>
                        <Badge
                          value={runStatus(
                            run.status,
                            !!staleEvidence(run, instance, diagnostics),
                          )}
                        />
                      </Link>
                    </td>
                    <td>{tr(run.trigger)}</td>
                    <td>
                      <Timestamp value={run.started_at} />
                    </td>
                    <td>{duration(run.duration_ms)}</td>
                    <td>
                      {Object.entries(run.actions)
                        .filter(([, count]) => count > 0)
                        .map(
                          ([action, count]) =>
                            `${action.replaceAll("_", " ")}: ${count}`,
                        )
                        .join(" · ") || tr("No actions recorded")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p>{tr("No runs recorded for this source.")}{" "}</p>
        ))}
    </section>
  );
}
function SourceConfiguration({
  source: s,
  scheduleLink,
}: {
  source: Source;
  scheduleLink: string;
}) {
  const groups = [
    [
      "Identity",
      [
        ["Display name", s.name],
        ["Provider", s.type === "proxmox" ? "Proxmox VE" : "VMware ESXi"],
      ],
    ],
    [
      "Connection",
      [
        ["Address", s.address],
        ["Credentials", "Source-scoped; values are not exposed"],
        ["Verification", "Connectivity and authentication not checked here"],
      ],
    ],
    [
      "NetBox target",
      [
        ["Site", s.site_slug],
        ["Cluster", s.cluster_name],
      ],
    ],
    [
      "Provider mapping",
      [
        ["Platform", s.platform_slug],
        ["Device role", s.device_role_slug],
        ["Device type", s.device_type_slug],
        ["Cluster type", s.cluster_type_slug],
      ],
    ],
    [
      "TLS",
      [["Certificate verification", s.verify_ssl ? "Enabled" : "Disabled"]],
    ],
  ] as const;
  return (
    <>
      <h2>{tr("Configuration")}{" "}</h2>
      <p className="muted">
        {tr("Read-only source configuration. Credentials and stable identity are protected.")}{" "}</p>
      <div className="source-panels">
        {groups.map(([title, fields]) => (
          <section className="source-panel" key={tr(title)}>
            <h3>{tr(title)}</h3>
            <dl className="source-facts">
              {fields.map(([label, value]) => (
                <div key={tr(label)}>
                  <dt>{tr(label)}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
            </dl>
          </section>
        ))}
      </div>
      <p>
        <Link to={scheduleLink}>{tr("Manage automatic sync schedule")}{" "}</Link>
      </p>
      <details className="source-panel">
        <summary>{tr("Advanced identity")}{" "}</summary>
        <dl className="source-facts">
          <div>
            <dt>{tr("Stable source ID")}{" "}</dt>
            <dd>
              <code>{s.source_instance}</code>
            </dd>
          </div>
          <div>
            <dt>{tr("Legacy identity owner")}{" "}</dt>
            <dd>{s.legacy_identity_owner ? tr("Yes") : tr("No")}</dd>
          </div>
        </dl>
      </details>
    </>
  );
}
