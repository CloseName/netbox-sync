import {useLanguage} from '../ui/language';
import {readablePlanItem,planReason,planParent,changedObjectCount} from '../ui/plan';
import {hasChanges,emptyPlanLabel} from '../ui/plan';
import {tr} from "../ui/i18n";
import { useState, Fragment, type ReactNode } from "react";
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
  const [language]=useLanguage();
  if(plan.conflicts?.length)return <p role="status">{language==='ru'?'Подсчёт изменений не завершён: план заблокирован.':'Change calculation is incomplete: the plan is blocked.'}</p>;
  const counts = planCounts(plan.items);
  return (
    <dl className="sync-summary"><div><dt>{tr("Unique changed objects")}</dt><dd>{changedObjectCount(plan.items)}</dd></div>
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
  toolbar,
  executionBlocked = false,
}: {
  plan: SyncPlan;
  received: string;
  previous: boolean;
  toolbar?: ReactNode;
  executionBlocked?: boolean;
}) {
  const [language]=useLanguage(),t=(en:string,ru:string)=>language==='ru'?ru:en;
  const [view, setView] = useState<PlanView>(
    plan.items.some((item) => item.action === "BLOCKED")
      ? "Attention"
      : "Changes",
  );
  const [action, setAction] = useState(""),
    [kind, setKind] = useState(""),
    [search, setSearch] = useState("");
  const [limit, setLimit] = useState(50);
  const rows = filterPlan(plan.conflicts?.length?plan.items.filter(item=>item.action!=='BLOCKED'):plan.items, view, action, kind, search);
  const groups=rows.slice(0,limit).reduce((map,item)=>{const name=planParent(item,plan.items)||readablePlanItem(item,plan.items).name;map.set(name,[...(map.get(name)??[]),item]);return map;},new Map<string,SyncPlanItem[]>());
  return (
    <section
      className="source-panel plan-review"
      aria-labelledby="plan-review-title"
    >
      <div className="page-heading">
        <h3 id="plan-review-title">{tr("Review plan")}{" "}</h3>
        <Badge
          value={{
            label: executionBlocked ? "Blocked by safety checks" : previous
              ? "Previous plan — build a new plan"
              : plan.apply_allowed
                ? hasChanges(plan.items) ? "Plan permits sync" : emptyPlanLabel(plan.items)
                : "Blocked by safety checks",
            tone: executionBlocked ? "danger" : previous ? "neutral" : plan.apply_allowed ? "info" : "danger",
            icon: executionBlocked ? "!" : previous ? "◷" : plan.apply_allowed ? "✓" : "!",
          }}
        />
        {toolbar}
      </div>
      <p className="muted">
        {tr("Plan received")}{" "}<Timestamp value={received} />{tr(". The plan is checked again before sync.")}{" "}</p>
      <PlanSummary plan={plan} />
      {!!planCounts(plan.items).UNSUPPORTED&&<button onClick={()=>{setView('Attention');setAction('UNSUPPORTED');setKind('');setSearch('');setLimit(50);}}>{tr('Show unsupported categories')}</button>}
      {!plan.conflicts?.length&&<p className="muted">
        {tr("Create and Update count operations, not unique objects. Other counts describe plan rows. Filters change this view only; sync submits the entire reviewed plan.")}{" "}</p>}
      {plan.items.filter(item=>policyRow(item)&&!plan.conflicts?.length).map((item, i) => (
        <p className="sync-safety" key={i}>
          {tr("Retention policy:")}{" "}{planReason(item)}
        </p>
      ))}
      {!!planCounts(plan.items).REVIEW_REQUIRED && (
        <p className="sync-attention">
          {tr("Review rows remain isolated and are not automatically adopted as normal updates. Other operations may proceed only when the plan permits sync.")}{" "}</p>
      )}
      {!plan.apply_allowed && !plan.conflicts?.length && (
        <p className="source-error" role="alert">
          {tr("This plan cannot be applied. Resolve the reported conditions and rebuild the plan.")}{" "}</p>
      )}
      {!!plan.conflicts?.length && <section aria-label={tr('Inventory conflicts')}>
        <h4>{tr('Plan blocked: conflicts detected')}</h4>
        <p>{tr('Compare the listed objects in the source. Correct ambiguous identities or network assignments, then build a new plan. No objects are excluded automatically.')}</p>
        {plan.conflicts.map((conflict,index)=>{
          const identities=new Set(conflict.participants.map(p=>[p.host_id,p.provider_object_id||p.external_id,p.interface_id||p.interface].join(':')));
          const masks=conflict.kind==='IP_ASSIGNMENT'&&identities.size===1&&new Set(conflict.participants.map(p=>p.address)).size>1;
          return <article key={index} className="conflict-summary"><h4>{conflict.kind==='VM_IDENTITY'?`${conflict.participants.length} VM`:conflict.value}: {masks?t('Different masks for one IP','Разные маски одного IP'):conflict.kind==='VM_IDENTITY'?tr('Shared VM identifier'):t('Ambiguous IP mapping','Неоднозначное сопоставление IP')}</h4>
          <ul>{Array.from(new Set(conflict.participants.map(p=>[p.name,p.interface,p.address].filter(Boolean).join(' · ')))).map(value=><li key={value}>{value}</li>)}</ul>
          <details><summary>{tr('Technical details')}</summary><p>{tr('Source')}: {plan.source_instance}</p><p>{conflict.value}</p><ul>{conflict.participants.map((p,i)=><li key={i}>{p.host_id} · {p.external_id} · {p.provider_object_id} · {p.interface_id}</li>)}</ul></details></article>;
        })}
      </section>}
      {(!plan.conflicts?.length||plan.items.some(item=>item.action!=='BLOCKED'&&!policyRow(item)))&&<>
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
              {tr(value)}
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
        {rows.length} {tr("rows in this view")}{" "}{rows.length > limit ? ` · ${tr("Showing first")} ${limit}` : ""}
      </p>
      {!rows.length && (
        <p>{tr("No rows in this view. Review the summary or choose All.")}{" "}</p>
      )}
      <div className="plan-rows">
        {[...groups].map(([parent,items])=><Fragment key={parent}>{(items.length>1||planParent(items[0],plan.items))&&<h4>{parent}</h4>}{items.map((item) => (
          <PlanRow key={plan.items.indexOf(item)} item={readablePlanItem(item, plan.items)} raw={item} />
        ))}</Fragment>)}
      </div>
      {rows.length > limit && (
        <button onClick={() => setLimit(limit + 50)}>{tr("Show 50 more rows")}{" "}</button>
      )}
      </>}
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
function PlanRow({ item,raw }: { item: SyncPlanItem;raw:SyncPlanItem }) {
  const fields = managedFields(item);
  return (
    <details className={"plan-row plan-" + item.action.toLowerCase()}>
      <summary>
        <span className="plan-object">
          <strong>{item.name}</strong>
          <span className="muted">{tr(kindLabel(item.object_kind))}</span>
        </span>
        <Badge value={actionStatus(item.action)} />
        <span className="plan-reason">{planReason(item)}</span>
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
            {tr("Needs operator review. No automatic adoption.")}{" "}{planReason(item)}
          </p>
        )}
        {item.action === "BLOCKED" && (
          <p className="source-error">{tr("Blocked:")}{" "}{planReason(item)}</p>
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
          <summary>{tr("Row technical details")}{" "}</summary><details><summary>{tr("Raw operation")}</summary><pre>{JSON.stringify(raw,null,2)}</pre></details>
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
