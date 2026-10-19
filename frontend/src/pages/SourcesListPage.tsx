import {SourcesBulkActions} from '../components/SourcesBulkActions';
import {RefreshControl} from '../ui/RefreshControl';
import {useEffect,useState} from 'react';
import {useLanguage} from '../ui/language';
import {usePermission} from '../AuthGate';
import {tr} from "../ui/i18n";
import { SourceFilters } from "../ui/SourceFilters";
import { Link, useLocation, useSearchParams, useNavigate } from "react-router-dom";
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
  const [selected,setSelected]=useState<Set<string>>(new Set());
  const [language]=useLanguage(),t=(en:string,ru:string)=>language==='ru'?ru:en;
  const canRegister = usePermission('source.register');
  const sources = useResource(fetchSources),
    diagnostics = useResource(fetchDiagnostics);
  const [params, setParams] = useSearchParams();
  const location = useLocation(), navigate = useNavigate();
  const [teamWarning,setTeamWarning]=useState(!!location.state?.addedSource?.teamUnconfirmed);
  const [added,setAdded]=useState<{name:string;id:string;teamUnconfirmed?:boolean}|null>(location.state?.addedSource??null);
  useEffect(()=>{if(!added)return;const timer=setTimeout(()=>setAdded(null),10000);return()=>clearTimeout(timer);},[added]);
  useEffect(()=>{if(location.state?.addedSource)navigate(location.pathname+location.search,{replace:true,state:null});},[location,navigate]);
  const result = querySources(
    composeSources(sources.data ?? [], diagnostics.data),
    new URLSearchParams([...params].filter(([key])=>!["team","schedule","attention","site"].includes(key))),
  );
  useEffect(()=>{if(!sources.data||diagnostics.loading)return;try{const offset=Number(sessionStorage.getItem("sources-scroll:"+location.search)||0);if(offset>0)requestAnimationFrame(()=>window.scrollTo(0,offset));}catch{/* Optional browser storage. */}},[!!sources.data,diagnostics.loading]);
  // Browser history changes before React commits a navigation transition.
  // Read that URL so rapid filter edits cannot resurrect a just-cleared query.
  const change = (key: string, value: string) => {
    setSelected(new Set());
    const next = new URLSearchParams(window.location.search);
    value ? next.set(key, value) : next.delete(key);
    if (key !== "page") next.delete("page");
    setParams(next, { replace: key === "q" });
  };
  useEffect(()=>setSelected(new Set()),[location.search]);
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
      {typeof location.state?.removedSource==='string'&&<p role="status">{language==='ru'?'Источник удалён. Его данные в Sync очищены; общие и чужие объекты сохранены.':'Source removed. Its Sync data is cleared; shared and foreign objects are preserved.'} <strong>{location.state.removedSource}</strong></p>}
      <PageHeader
        title={tr("Sources")}
        description={tr("Source configuration and synchronization evidence.")}
      />
      <div className="sources-actions">{canRegister&&<Link className="button primary" to="/sources/add">{tr("Add Source")}</Link>}<RefreshControl loading={sources.loading||diagnostics.loading} error={sources.error||diagnostics.error} received={sources.received} refresh={refresh}/></div>
      {teamWarning&&<p role="alert" className="source-error">{t('Source added, but team assignment is unconfirmed. Check the source team before retrying assignment.','Источник добавлен, но назначение команды не подтверждено. Проверьте команду источника перед повторным назначением.')} <button type="button" onClick={()=>setTeamWarning(false)}>{t('Dismiss','Закрыть')}</button></p>}
      {added&&<div className="source-added-notice" role="status" aria-live="polite"><span>{t('Source ','Источник ')}<strong>{added.name}</strong>{t(' added',' добавлен')}</span><button type="button" aria-label={t('Dismiss notification','Закрыть уведомление')} onClick={()=>setAdded(null)}>×</button></div>}
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
      <SourcesBulkActions selected={result.rows.map(r=>r.source).filter(s=>selected.has(s.source_instance))} refresh={refresh}/>
      <SourceFilters
        query={result.query}
        change={change}
      />
      {sources.loading && !sources.data ? (
        <LoadingState table label={tr("Loading sources…")} />
      ) : (
        sources.data &&
        (sources.data.length === 0 ? (
          <EmptyState title={tr("No sources have been registered.")}>
            {canRegister && <Link to="/sources/add">{tr("Add Source")}{" "}</Link>}
          </EmptyState>
        ) : result.total === 0 ? (
          <EmptyState title={tr("No sources match these filters.")}>
            <p>{t("Change the search or sync status.","Измените поиск или статус синхронизации.")}</p>
          </EmptyState>
        ) : (
          <>
            <div
              className="source-table source-list-table scroll-region"
              tabIndex={0}
              role="region"
              aria-label={tr("Sources table")}
            >
              <table>
                <caption className="sr-only">
                  {tr("Registered sources with configuration and diagnostic evidence")}{" "}</caption>
                <thead>
                  <tr>
                    <th scope="col"><input type="checkbox" aria-label={t("Select this page","Выбрать эту страницу")} checked={result.rows.length>0&&result.rows.every(r=>selected.has(r.source.source_instance))} onChange={e=>setSelected(new Set(e.target.checked?result.rows.map(r=>r.source.source_instance):[]))}/></th>
                    {heading("Source", "name")}

                    <th scope="col">{tr("Target")}{" "}</th>
                    <th scope="col">{tr("Sync status")}{" "}</th>
                    <th scope="col">{tr("Schedule")}{" "}</th>
                    {heading("Last run", "last")}
                    {heading("Attention", "attention")}
                  </tr>
                </thead>
                <tbody>
                  {result.rows.map(
                    ({ source: s, diagnostic: d, attention: a }) => (
                      <tr key={s.source_instance}><td><input type="checkbox" aria-label={t("Select ","Выбрать ")+s.name} checked={selected.has(s.source_instance)} onChange={e=>setSelected(before=>{const next=new Set(before);e.target.checked?next.add(s.source_instance):next.delete(s.source_instance);return next;})}/></td>
                        <th scope="row">
                          <Link
                            to={sourcePath(s.source_instance)}
                            onClick={()=>{try{sessionStorage.setItem("sources-scroll:"+location.search,String(window.scrollY));}catch{/* Optional browser storage. */}}}
                            state={{
                              from: location.pathname + location.search,
                            }}
                          >
                            {s.name}
                          </Link>
<small>{s.type === "proxmox" ? tr("Proxmox VE") : tr("VMware ESXi")}</small>
                          {!s.enabled && <small>{tr("Source disabled")}{" "}</small>}
                        </th>

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
                            <span className="muted">{tr(diagnostics.loading?"Loading diagnostics…":"Status unavailable")}{" "}</span>
                          )}
                          {d?.plan_checked_at&&<small>{t('Last plan: ','Последний план: ')}<Timestamp value={d.plan_checked_at}/></small>}
                          {d?.latest_success_at&&<small>{t('Last successful sync: ','Последняя успешная синхронизация: ')}<Timestamp value={d.latest_success_at}/></small>}
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
                            tr(diagnostics.loading?"Loading diagnostics…":"Unavailable")
                          )}
                        </td>
                        <td>
                          {a ? (
                            <Link to={sourcePath(s.source_instance)+(d?.plan_blocked?"/sync":"")}>
                              {tr(a.label)}
                            </Link>
                          ) : d ? (
                            tr(d?.operation_evidence_available===false?"Status unavailable":"None reported")
                          ) : (
                            tr(diagnostics.loading?"Loading diagnostics…":"Unavailable")
                          )}
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
