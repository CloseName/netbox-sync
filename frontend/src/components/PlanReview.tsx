import {tr} from "../ui/i18n";
import { useState } from "react";
import type { SyncPlan, SyncPlanItem } from "../api/sync";
import {
  actionLabels,
  actionStatus,
  countLabels,
  filterPlan,
  planCounts,
  policyRow,
  managedFields,
  fieldText,
  kindLabel,
} from "../ui/plan";
import type { PlanView } from "../ui/plan";
import { Badge, Timestamp } from "../ui/primitives";
export function PlanSummary({ plan }: { plan: SyncPlan }) {
  const counts = planCounts(plan.items);
  return (
    <dl className="sync-summary">
      {Object.entries(counts)
        .filter(
          ([action, n]) =>
            n ||
            ["CREATE", "UPDATE", "REVIEW_REQUIRED", "BLOCKED"].includes(action),
        )
        .map(([action, count]) => (
          <div key={action}>
            <dt>{tr(countLabels[action as keyof typeof countLabels])}</dt>
            <dd>{count}</dd>
          </div>
        ))}
    </dl>
  );
}
export function PlanReview({
  plan,
  received,
  previous,
}: {
  plan: SyncPlan;
  received: string;
  previous: boolean;
}) {
  const [view, setView] = useState<PlanView>(
    plan.items.some((item) => item.action === "BLOCKED")
      ? "Attention"
      : "Changes",
  );
  const [action, setAction] = useState(""),
    [kind, setKind] = useState(""),
    [search, setSearch] = useState("");
  const [limit, setLimit] = useState(50);
  const rows = filterPlan(plan.items, view, action, kind, search);
  return (
    <section
      className="source-panel plan-review"
      aria-labelledby="plan-review-title"
    >
      <div className="page-heading">
        <h3 id="plan-review-title">{tr("Review plan")}{" "}</h3>
        <Badge
          value={{
            label: previous
              ? "Previous plan — build a new plan"
              : plan.apply_allowed
                ? "Plan permits sync"
                : "Blocked by safety checks",
            tone: previous ? "neutral" : plan.apply_allowed ? "info" : "danger",
            icon: previous ? "◷" : plan.apply_allowed ? "✓" : "!",
          }}
        />
      </div>
      <p className="muted">
        {tr("Plan received")}{" "}<Timestamp value={received} />{tr(". The plan is checked again before sync.")}{" "}</p>
      <PlanSummary plan={plan} />
      <p className="muted">
        {tr("Create and Update count operations, not unique objects. Other counts describe plan rows. Filters change this view only; sync submits the entire reviewed plan.")}{" "}</p>
      {plan.items.filter(policyRow).map((item, i) => (
        <p className="sync-safety" key={i}>
          {tr("Retention policy:")}{" "}{item.reason}
        </p>
      ))}
      {!!planCounts(plan.items).REVIEW_REQUIRED && (
        <p className="sync-attention">
          {tr("Review rows remain isolated and are not automatically adopted as normal updates. Other operations may proceed only when the plan permits sync.")}{" "}</p>
      )}
      {!plan.apply_allowed && (
        <p className="source-error" role="alert">
          {tr("This plan cannot be applied. Resolve the reported conditions and rebuild the plan.")}{" "}</p>
      )}
      <div className="sync-filters">
        <div className="view-options" role="group" aria-label={tr("Plan view")}>
          {(["Changes", "Attention", "All"] as PlanView[]).map((value) => (
            <button
              key={value}
              aria-pressed={view === value}
              onClick={() => {
                setView(value);
                setLimit(50);
              }}
            >
              {value}
            </button>
          ))}
        </div>
        <label>
          {tr("Action")}{" "}<select
            value={action}
            onChange={(e) => {
              setAction(e.target.value);
              setLimit(50);
            }}
          >
            <option value="">{tr("All actions")}{" "}</option>
            {Object.entries(actionLabels).map(([value, label]) => (
              <option key={value} value={value}>
                {tr(label)}
              </option>
            ))}
          </select>
        </label>
        <label>
          {tr("Object kind")}{" "}<select
            value={kind}
            onChange={(e) => {
              setKind(e.target.value);
              setLimit(50);
            }}
          >
            <option value="">{tr("All kinds")}{" "}</option>
            {[
              ...new Set(
                plan.items
                  .filter((item) => !policyRow(item))
                  .map((item) => item.object_kind),
              ),
            ].map((value) => (
              <option key={value} value={value}>
                {tr(kindLabel(value))}
              </option>
            ))}
          </select>
        </label>
        <label>
          {tr("Search plan")}{" "}<input
            type="search"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setLimit(50);
            }}
          />
        </label>
      </div>
      <p>
        {rows.length} {tr("rows in this view")}{" "}{rows.length > limit ? ` · showing first ${limit}` : ""}
      </p>
      {!rows.length && (
        <p>{tr("No rows in this view. Review the summary or choose All.")}{" "}</p>
      )}
      <div className="plan-rows">
        {rows.slice(0, limit).map((item) => (
          <PlanRow key={plan.items.indexOf(item)} item={item} />
        ))}
      </div>
      {rows.length > limit && (
        <button onClick={() => setLimit(limit + 50)}>{tr("Show 50 more rows")}{" "}</button>
      )}
      <details className="sync-technical">
        <summary>{tr("Plan technical details")}{" "}</summary>
        <dl className="source-facts">
          {Object.entries({
            Digest: plan.digest,
            "Schema version": plan.schema_version,
            "Planner version": plan.planner_version,
            "Source identity": plan.source_instance,
            "Source fingerprint": plan.source_fingerprint,
            "Target fingerprint": plan.target_fingerprint,
            "Provider fingerprint": plan.provider_fingerprint,
            "NetBox fingerprint": plan.netbox_fingerprint,
          }).map(([key, value]) => (
            <div key={key}>
              <dt>{key}</dt>
              <dd>
                <code>{String(value)}</code>
              </dd>
            </div>
          ))}
        </dl>
      </details>
    </section>
  );
}
function PlanRow({ item }: { item: SyncPlanItem }) {
  const fields = managedFields(item);
  return (
    <details className={"plan-row plan-" + item.action.toLowerCase()}>
      <summary>
        <span className="plan-object">
          <strong>{item.name}</strong>
          <span className="muted">{tr(kindLabel(item.object_kind))}</span>
        </span>
        <Badge value={actionStatus(item.action)} />
        <span className="plan-reason">{item.reason}</span>
        <span className="muted">{tr("Details")}{" "}</span>
      </summary>
      <div className="plan-row-body">
        {item.action === "CREATE" && (
          <p>
            {tr("Will create managed object. Proposed managed values are shown only when provided.")}{" "}</p>
        )}
        {item.action === "UPDATE" && (
          <p>{tr("Changes to managed fields are shown below.")}{" "}</p>
        )}
        {item.action === "REVIEW_REQUIRED" && (
          <p className="sync-attention">
            {tr("Needs operator review. No automatic adoption.")}{" "}{item.reason}
          </p>
        )}
        {item.action === "BLOCKED" && (
          <p className="source-error">{tr("Blocked:")}{" "}{item.reason}</p>
        )}
        {fields.length ? (
          <div
            className="managed-diff"
            role="table"
            aria-label={tr("Managed fields for") + " " + item.name}
          >
            <div className="diff-head" role="row">
              <span role="columnheader">{tr("Field")}{" "}</span>
              <span role="columnheader">{tr("NetBox before")}{" "}</span>
              <span role="columnheader">{tr("Proposed")}{" "}</span>
            </div>
            {fields.map((field) => (
              <div role="row" className="diff-row" key={field.field}>
                <strong role="rowheader">{field.field}</strong>
                <div role="cell">
                  <span className="diff-mobile-label">{tr("NetBox before")}{" "}</span>
                  <pre>{field.before.provided?fieldText(field.before):tr("Not provided")}</pre>
                </div>
                <div role="cell">
                  <span className="diff-mobile-label">{tr("Proposed")}{" "}</span>
                  <pre>{field.after.provided?fieldText(field.after):tr("Not provided")}</pre>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p>{tr("No managed before/proposed values were provided for this row.")}{" "}</p>
        )}
        <p className="muted">
          {tr("Two-way evidence only. Proposed values are not a separate discovered snapshot.")}{" "}</p>
        <details>
          <summary>{tr("Row technical details")}{" "}</summary>
          <dl className="source-facts">
            <div>
              <dt>{tr("External ID")}{" "}</dt>
              <dd>
                <code>{item.external_id}</code>
              </dd>
            </div>
            <div>
              <dt>{tr("Kind / endpoint")}{" "}</dt>
              <dd>
                <code>{item.object_kind}</code>
              </dd>
            </div>
            <div>
              <dt>{tr("Reason code")}{" "}</dt>
              <dd>
                <code>{item.reason_code}</code>
              </dd>
            </div>
            <div>
              <dt>{tr("NetBox match ID")}{" "}</dt>
              <dd>{item.matched_object_id ?? tr("Not provided")}</dd>
            </div>
          </dl>
        </details>
      </div>
    </details>
  );
}
