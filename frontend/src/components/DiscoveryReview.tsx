import {tr} from "../ui/i18n";
import { useState } from "react";
import type { DiscoveryResult } from "../api/discovery";
import { Badge, Timestamp } from "../ui/primitives";
import { kindLabel } from "../ui/plan";
const labels: Record<string, string> = {
  MANAGED: "Managed",
  NO_CHANGE: "Unchanged",
  WOULD_CREATE: "Would create",
  REVIEW_REQUIRED: "Needs review",
  CONFLICT: "Conflict",
  IGNORED: "Ignored",
  UNSUPPORTED: "Unsupported",
};
export function DiscoveryReview({
  result,
  received,
  previous,
}: {
  result: DiscoveryResult;
  received: string;
  previous: boolean;
}) {
  const [classification, setClassification] = useState(""),
    [kind, setKind] = useState("");
  const rows = result.items.filter(
    (item) =>
      (!classification || item.classification === classification) &&
      (!kind || item.object_kind === kind),
  );
  return (
    <div>
      <p role="status">
        {tr("Discovery received")}{" "}<Timestamp value={received} />
        {previous ? tr(" · Previous evidence while discovery runs") : ""}
      </p>
      <dl className="sync-summary">
        {[...new Set(result.items.map((item) => item.classification))].map(
          (value) => (
            <div key={value}>
              <dt>{tr(labels[value])} {tr("rows")}{" "}</dt>
              <dd>
                {
                  result.items.filter((item) => item.classification === value)
                    .length
                }
              </dd>
            </div>
          ),
        )}
      </dl>
      <div className="sync-filters">
        <label>
          {tr("Classification")}{" "}<select
            value={classification}
            onChange={(e) => setClassification(e.target.value)}
          >
            <option value="">{tr("All classifications")}{" "}</option>
            {Object.entries(labels).map(([value, label]) => (
              <option value={value} key={value}>
                {tr(label)}
              </option>
            ))}
          </select>
        </label>
        <label>
          {tr("Discovery object kind")}{" "}<select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">{tr("All kinds")}{" "}</option>
            {[...new Set(result.items.map((item) => item.object_kind))].map(
              (value) => (
                <option key={value} value={value}>
                  {tr(kindLabel(value))}
                </option>
              ),
            )}
          </select>
        </label>
      </div>
      {!rows.length && <p>{tr("No discovered rows in this view.")}{" "}</p>}
      <div className="plan-rows">
        {rows.map((item, i) => (
          <details className="plan-row" key={i}>
            <summary>
              <span className="plan-object">
                <strong>{item.name}</strong>
                <span>{tr(kindLabel(item.object_kind))}</span>
              </span>
              <Badge
                value={{
                  label: labels[item.classification],
                  tone:
                    item.classification === "CONFLICT"
                      ? "danger"
                      : item.classification === "REVIEW_REQUIRED"
                        ? "warning"
                        : "neutral",
                  icon: ["CONFLICT", "REVIEW_REQUIRED"].includes(
                    item.classification,
                  )
                    ? "!"
                    : "−",
                }}
              />
              <span className="plan-reason">{item.reason}</span>
            </summary>
            <div className="plan-row-body">
              <p>{tr("NetBox match:")}{" "}{item.matched_object_name ?? tr("Not provided")}</p>
              {["CONFLICT", "REVIEW_REQUIRED"].includes(
                item.classification,
              ) && (
                <p className="sync-attention">
                  {tr("Attention:")}{" "}{item.reason}{tr(". No automatic adoption.")}{" "}</p>
              )}
              <details>
                <summary>{tr("Discovery technical details")}{" "}</summary>
                <dl className="source-facts">
                  <div>
                    <dt>{tr("External ID")}{" "}</dt>
                    <dd>
                      <code>{item.external_id}</code>
                    </dd>
                  </div>
                  <div>
                    <dt>{tr("Reason code")}{" "}</dt>
                    <dd>
                      <code>{item.reason_code}</code>
                    </dd>
                  </div>
                  <div>
                    <dt>{tr("Match ID")}{" "}</dt>
                    <dd>{item.matched_object_id ?? tr("Not provided")}</dd>
                  </div>
                  <div>
                    <dt>{tr("Future action classification")}{" "}</dt>
                    <dd>{item.future_action}</dd>
                  </div>
                </dl>
              </details>
            </div>
          </details>
        ))}
      </div>
      <p className="muted">
        {tr("Build plan performs a fresh read. It does not reuse this discovery snapshot.")}{" "}</p>
    </div>
  );
}
