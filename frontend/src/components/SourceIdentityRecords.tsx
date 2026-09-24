import {useState} from 'react';
import {Link} from 'react-router-dom';
import {useLanguage} from '../ui/language';
interface Row {source_instance:string;name:string;address:string;host_uuid:string|null;site_id:number|null;cluster_id:number|null;state:string;enabled:boolean;unresolved_runs:number;operations:unknown[];runs:{run_id:string;status:string;started_at:string}[]}
export function SourceIdentityRecords({source}:{source:string}) {
 const [language]=useLanguage(),t=(en:string,ru:string)=>language==='ru'?ru:en;
 const [rows,setRows]=useState<Row[]|null>(null),[busy,setBusy]=useState(false),[failed,setFailed]=useState(false);
 async function load(){
  if(busy)return;setBusy(true);setFailed(false);setRows(null);
  try{
   const response=await fetch(`/api/v1/sources/${encodeURIComponent(source)}/identity-records`,{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json','X-NetBox-Sync-CSRF':'same-origin'},body:'{}',signal:AbortSignal.timeout(15000)});
   if(!response.ok)throw new Error();const value=await response.json();
   if(value.comparison!=='RECORDED_IDENTITY_ONLY'||!Array.isArray(value.sources)||value.sources.length>100)throw new Error();
   setRows(value.sources);
  }catch{setFailed(true);}finally{setBusy(false);}
 }
 return <section className="source-panel"><button type="button" disabled={busy} onClick={()=>void load()}>{busy?t('Loading records…','Получаем записи…'):t('Compare saved identity and history','Сравнить сохранённую идентичность и историю')}</button>
 {failed&&<p role="alert">{t('Could not read the records. No reservation was changed. Retry after checking your administrator session.','Не удалось прочитать записи. Резервы не изменены. Проверьте сеанс администратора и повторите запрос.')}</p>}
 {rows&&<><p>{t('These are recorded values, not proof that the machines are physically identical. Open each source to review its history. Select the original removed source only after checking fresh connection evidence and NetBox ownership. Other records and reservations remain in history.','Это сохранённые значения, а не доказательство тождества физических серверов. Откройте каждый источник и проверьте историю. Выбирайте прежний удалённый источник только после проверки свежих данных подключения и принадлежности NetBox. Другие записи и резервы сохраняются в истории.')}</p>
 {rows.map(row=><article key={row.source_instance}><h3><Link to={`/sources/${encodeURIComponent(row.source_instance)}`}>{row.name}</Link></h3><p><code>{row.source_instance}</code> · {row.address}</p>
 <p>UUID: <code>{row.host_uuid??t('Not recorded','Не записан')}</code> · {t('Site','Площадка')} #{row.site_id??'—'} · {t('Cluster','Кластер')} #{row.cluster_id??'—'}</p>
 <p>{row.state==='REMOVED'?t('Removed','Удалён'):row.enabled?t('Registered','Зарегистрирован'):t('Registered, disabled','Зарегистрирован, выключен')} · {t('Active operations','Выполняется операций')}: {row.operations.length} · {t('Unresolved runs','Неразрешённых запусков')}: {row.unresolved_runs}</p>
 <ul>{row.runs.map(run=><li key={run.run_id}><Link to={`/runs/${encodeURIComponent(run.run_id)}`}>{run.started_at} · {run.status}</Link></li>)}</ul></article>)}</>}
 </section>;
}
