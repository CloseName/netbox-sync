import {tr} from "../ui/i18n";
import { Link } from "react-router-dom";
import { fetchDiagnostics } from "../api/diagnostics";
import { useResource } from "../ui/useResource";
import { ResourceFeedback } from "../ui/ResourceFeedback";
import { Badge, PageHeader, Timestamp } from "../ui/primitives";
import { healthStatus, runStatus, scheduleStates } from "../ui/status";
import {
  componentLabels,
  componentReason,
  aggregateReason,
} from "../ui/diagnosticEvidence";
import type { ComponentKey } from "../ui/diagnosticEvidence";
import { diagnosticsUsable } from "../ui/operations";
import { DiagnosticAttention } from "../ui/DiagnosticAttention";
import { staleEvidence } from "../ui/runEvidence";
import { sourcePath, runPath } from "../ui/routes";
export function DiagnosticsPage() {
  const resource = useResource(fetchDiagnostics),
    data = resource.data;
  return (
    <main className="operations-workspace">
      <PageHeader
        title={tr("Diagnostics")}
        description={tr("Checks and recorded activity, with evidence for investigation.")}
        actions={
          <button disabled={resource.loading} onClick={resource.refresh}>
            {tr("Refresh")}{" "}</button>
        }
      />
      <ResourceFeedback
        resource={resource}
        label={tr("diagnostics")}
        evidenceAt={data?.generated_at}
      />
      {data && (
        <>
          <section
            className="diagnostic-summary source-panel"
            aria-label={tr("System assessment")}
          >
            <div>
              <h2>
                <Badge
                  value={healthStatus(data.overall_status)}
                  code={data.overall_status}
                />
              </h2>
              <p>{tr(aggregateReason(data))}</p>
            </div>
            <p>
              {tr("Snapshot")}{" "}<Timestamp value={data.generated_at} />
            </p>
          </section>
          <section className="source-panel">
            <h2>{tr("Component checks")}{" "}</h2>
            <div className="diagnostic-components">
              {(Object.keys(componentLabels) as ComponentKey[]).map((key) => {
                const c = data.components[key];
                return (
                  <article
                    id={"component-" + key}
                    key={key}
                    className="diagnostic-component"
                  >
                    <div>
                      <h3>{tr(componentLabels[key])}</h3>
                      <Badge value={healthStatus(c.status)} code={c.status} />
                    </div>
                    <div>
                      <p>{tr(componentReason(key, c))}</p>
                      {key === "scheduler" && (
                        <small>
                          {tr("Last recorded activity:")}{" "}{" "}
                          <Timestamp value={c.last_seen_at} />
                        </small>
                      )}
                      <details>
                        <summary>{tr("Technical details")}{" "}</summary>
                        <dl className="technical-facts">
                          <div>
                            <dt>{tr("Recorded status")}{" "}</dt>
                            <dd>{c.status}</dd>
                          </div>
                          <div>
                            <dt>{tr("Checked at")}{" "}</dt>
                            <dd>
                              <Timestamp value={c.checked_at} />
                            </dd>
                          </div>
                          <div>
                            <dt>{tr("Last response")}{" "}</dt>
                              <dd><Timestamp value={c.last_seen_at} /></dd>
                            </div>
                            <div>
                              <dt>{tr("Last success")}{" "}</dt>
                            <dd>
                              <Timestamp value={c.last_success_at} />
                            </dd>
                          </div>
                          <div>
                            <dt>{tr("Next expected")}{" "}</dt>
                            <dd>
                              <Timestamp value={c.next_expected_at} />
                            </dd>
                          </div>
                          <div>
                            <dt>{tr("Safe code")}{" "}</dt>
                            <dd>{c.safe_code ?? tr("None reported")}</dd>
                          </div>
                          {c.safe_message && (
                            <div>
                              <dt>{tr("Safe message")}{" "}</dt>
                              <dd>{c.safe_message}</dd>
                            </div>
                          )}
                        </dl>
                      </details>
                    </div>
                    <div className="muted">
                      {tr("Checked")}{" "}<Timestamp value={c.checked_at} />
                    </div>
                  </article>
                );
              })}
            </div>
          </section>
          <section className="source-panel">
            <h2>{tr("Attention")}{" "}</h2>
            <DiagnosticAttention data={data} />
          </section>
          <section className="source-panel">
            <h2>{tr("Source evidence")}{" "}</h2>
            <p className="muted">
              {tr("Derived from configuration and persisted runs. This does not verify source connectivity or a live scheduler heartbeat.")}{" "}</p>
            {!diagnosticsUsable(data) ? (
              <p>
                {tr("Source evidence unavailable. Registry and run history checks must both succeed.")}{" "}</p>
            ) : data.sources.length === 0 ? (
              <p>
                {tr("No sources configured.")}{" "}<Link to="/sources">{tr("Open Sources")}{" "}</Link>
              </p>
            ) : (
              <div
                className="source-table"
                role="region"
                aria-label={tr("Source diagnostic evidence")}
                tabIndex={0}
              >
                <table>
                  <thead>
                    <tr>
                      {[
                        "Source",
                        "Assessment",
                        "Latest run",
                        "Scheduled activity",
                        "Last success",
                      ].map((label) => (
                        <th key={tr(label)} scope="col">
                          {tr(label)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {data.sources.map((s) => (
                      <tr key={s.source_instance}>
                        <td>
                          <Link
                            to={sourcePath(s.source_instance) + "/diagnostics"}
                          >
                            {s.source_instance}
                          </Link>
                          <small>
                            {s.source_type === "proxmox"
                              ? tr("Proxmox VE")
                              : tr("VMware ESXi")}
                          </small>
                        </td>
                        <td>
                          <Badge value={healthStatus(s.status)} />
                        </td>
                        <td>
                          {s.latest_run ? (
                            <>
                              <Link to={runPath(s.latest_run.run_id)}>
                                <Badge
                                  value={runStatus(
                                    s.latest_run.status,
                                    !!staleEvidence(
                                      s.latest_run,
                                      s.source_instance,
                                      data,
                                    ),
                                  )}
                                />
                              </Link>
                              <small>
                                <Timestamp value={s.latest_run.started_at} />
                              </small>
                            </>
                          ) : (
                            tr("No runs recorded")
                          )}
                        </td>
                        <td>
                          <Link
                            to={sourcePath(s.source_instance) + "/schedule"}
                          >
                            <Badge value={scheduleStates[s.scheduler_state]} />
                          </Link>
                          <small>
                            {tr("Last scheduled:")}{" "}{" "}
                            <Timestamp value={s.last_scheduled_run_at} />
                          </small>
                        </td>
                        <td>
                          <Timestamp value={s.latest_success_at} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </main>
  );
}
