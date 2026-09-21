import {planReason} from '../ui/plan';
import {tr} from "../ui/i18n";
import { useState } from "react";
import type { DiscoveryResult } from "../api/discovery";
import { Badge, Timestamp } from "../ui/primitives";
import { kindLabel } from "../ui/plan";
const labels: Record<string, string> = {
  MANAGED: "Managed",
  NO_CHANGE: "Unchanged",
  WOULD_CREATE: "No existing match",
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
    [kind, setKind] = useState(""), [search,setSearch]=useState(""), [limit,setLimit]=useState(50);
  const rows = result.items.filter(
    (item) =>
      (!classification || item.classification === classification) &&
      (!kind || item.object_kind === kind) && (!search.trim() || [item.name,...(item.properties?.addresses??[])].some(value=>value.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()))),
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
      <div className="sync-filters"><label>{tr("Search by name or IP")}<input type="search" value={search} onChange={e=>{setSearch(e.target.value);setLimit(50);}}/></label>
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
        {rows.slice(0,limit).map((item, i) => (
          <details className="plan-row" key={i}>
            <summary>
              <span className="plan-object">
                <strong>{item.name}</strong><span>{item.properties?.addresses?.join(" · ")}</span>
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
              <span className="plan-reason">{planReason(item)}</span>
            </summary>
            <div className="plan-row-body">
              <dl className="source-facts">{Object.entries(item.properties??{}).filter(([key,value])=>!['addresses','interfaces','disks'].includes(key)&&value!==null&&value!==undefined&&value!=='').map(([key,value])=><div key={key}><dt>{tr(({vcpus:'vCPU',memory_bytes:'Memory',cpu:'CPU',status:'Status',architecture:'Architecture',os_type:'Operating system',manufacturer:'Manufacturer',model:'Model',hypervisor_version:'Hypervisor version'} as Record<string,string>)[key]??key)}</dt><dd>{key==='memory_bytes'?`${(Number(value)/1024**3).toFixed(2)} GiB`:String(value)}</dd></div>)}</dl>
              {!!item.properties?.disks?.length&&<section><h4>{tr('Disks')}</h4><ul>{item.properties.disks.map((disk,i)=><li key={i}>{disk.name} · {(disk.size_bytes/1024**3).toFixed(2)} GiB</li>)}</ul></section>}
              {!!item.properties?.interfaces?.length&&<section><h4>{tr('Interfaces')}</h4><ul>{item.properties.interfaces.map((nic,i)=><li key={i}>{[nic.name,nic.mac_address,nic.bridge,nic.vlan_id!=null?`VLAN ${nic.vlan_id}`:null,...nic.addresses].filter(Boolean).join(' · ')}</li>)}</ul></section>}
              <p>{tr("NetBox match:")}{" "}{item.matched_object_name ?? tr("Not provided")}</p>
              {["CONFLICT", "REVIEW_REQUIRED"].includes(
                item.classification,
              ) && (
                <p className="sync-attention">
                  {tr("Attention:")}{" "}{planReason(item)}{tr(". No automatic adoption.")}{" "}</p>
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
      {rows.length>limit&&<button onClick={()=>setLimit(n=>n+50)}>{tr("Show more")}</button>}
      <p className="muted">
        {tr("Build plan performs a fresh read. It does not reuse this discovery snapshot.")}{" "}</p>
    </div>
  );
}
