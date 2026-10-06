import {useRef,useState} from 'react';
import type {Source} from '../api/sources';
import {fetchSources} from '../api/sources';
import {fetchSchedule,updateSchedule,type CalendarSchedule} from '../api/schedule';
import {fetchPfSense} from '../api/pfsense';
import {sourceLifecycle} from '../api/lifecycle';
import {retirement,type Retirement} from '../api/retirement';
import {usePermission} from '../AuthGate';
import {useLanguage} from '../ui/language';

type Review={source:Source;plan?:Retirement;error?:string};
export function SourcesBulkActions({selected,refresh}:{selected:Source[];refresh:()=>void}){
 const [language]=useLanguage(),t=(en:string,ru:string)=>language==='ru'?ru:en;
 const canSchedule=usePermission('source.schedule'),canRemove=usePermission('source.remove');
 const [busy,setBusy]=useState(false),[results,setResults]=useState<string[]>([]),[reviews,setReviews]=useState<Review[]>([]);
 const [mode,setMode]=useState('interval'),[seconds,setSeconds]=useState(600),[time,setTime]=useState('00:00'),[day,setDay]=useState(1);
 const [targets,setTargets]=useState<Source[]>([]),[attempted,setAttempted]=useState(false);
 const scheduleDialog=useRef<HTMLDialogElement>(null),deleteDialog=useRef<HTMLDialogElement>(null);
 const lock=useRef(false);
 const signal=()=>AbortSignal.timeout(175000);
 const report=(name:string,value:string)=>setResults(r=>[...r,`${name}: ${value}`]);
 async function schedules(rows:Source[],enable:boolean){
  let successful=0;
  const calendar:CalendarSchedule|null=mode==='interval'?null:{mode:mode as CalendarSchedule['mode'],time,timezone:'Europe/Moscow',...(mode==='daily'?{}:{day})};
  for(const row of rows){try{
   const before=await fetchSchedule(row.source_instance,signal());
   const after=await updateSchedule(row.source_instance,{sync_enabled:enable,sync_interval_seconds:enable?seconds:before.sync_interval_seconds,
    sync_calendar:enable?calendar:before.sync_calendar??null,expected_sync_enabled:before.sync_enabled,
    expected_sync_interval_seconds:before.sync_interval_seconds,expected_sync_calendar:before.sync_calendar??null},signal());
   successful++;
   report(row.name,enable?t('Schedule saved','Расписание сохранено')+(after.next_expected_at?' · '+new Date(after.next_expected_at).toLocaleString(language==='ru'?'ru-RU':'en-GB',{timeZone:'Europe/Moscow'})+' MSK':''):t('Schedule disabled','Расписание отключено'));
  }catch(e){report(row.name,e instanceof Error?e.message:t('Failed','Ошибка'));}}
  report(t('Sources total','Итого источников'),`${successful}/${rows.length} ${enable?t('saved','сохранено'):t('disabled','отключено')}; ${rows.length-successful} ${t('failed','ошибок')}`);
 }
 async function run(operation:()=>Promise<void>){if(lock.current)return;lock.current=true;setBusy(true);setResults([]);try{await operation();}catch(e){report(t('Operation','Операция'),e instanceof Error?e.message:t('Failed','Ошибка'));}finally{lock.current=false;setBusy(false);refresh();}}
 async function disableAll(){await run(async()=>{
  await schedules(await fetchSources(signal()),false);
  try{
   const vms=await fetchPfSense(signal());
   for(const vm of vms.items){try{
    const response=await fetch(`/api/v1/pfsense/${vm.id}/status`,{cache:'no-store',signal:signal()});if(!response.ok)throw Error(t('Status unavailable','Состояние недоступно'));
    const current=await response.json();if(!current.ssh_port||!current.sync_enabled)continue;
    const policy=await fetch('/api/v1/policy',{cache:'no-store',signal:signal()});if(!policy.ok)throw Error(t('Policy unavailable','Права недоступны'));
    const {revision}=await policy.json();
    const result=await fetch(`/api/v1/pfsense/${vm.id}/schedule`,{method:'POST',signal:signal(),headers:{'Content-Type':'application/json','X-Netbox-Sync-CSRF':'same-origin'},body:JSON.stringify({sync_enabled:false,interval_minutes:current.interval_minutes,policy_revision:revision})});
    const value=await result.json();if(!result.ok||value.error)throw Error(value.error||t('Failed','Ошибка'));
    report(vm.name,t('pfSense collection disabled','Автосбор pfSense отключён'));
   }catch(e){report(vm.name,String(e));}}
  }catch{report('pfSense',t('Automatic collection could not be checked or disabled.','Не удалось проверить или отключить автоматический сбор.'));}
 });}
 async function reviewDelete(){
  const chosen=[...selected];setTargets(chosen);setReviews([]);setAttempted(false);deleteDialog.current?.showModal();
  await run(async()=>{for(const source of chosen){try{
   const state=await sourceLifecycle(source.source_instance,signal());if(!state.revision||state.removal_blocker)throw Error(state.removal_blocker||'SOURCE_CHANGED');
   const plan=await retirement(source.source_instance,'retirement-review',{operation_id:crypto.randomUUID(),revision:state.revision},signal());
   setReviews(r=>[...r,{source,plan}]);
  }catch(e){setReviews(r=>[...r,{source,error:String(e)}]);}}});
 }
 async function confirmDelete(){if(attempted||busy)return;setAttempted(true);await run(async()=>{
  for(const row of reviews){if(row.plan?.state!=='READY'){report(row.source.name,row.error||row.plan?.safe_code||t('Blocked','Заблокировано'));continue;}
   try{const value=await retirement(row.source.source_instance,'retire',{operation_id:row.plan.operation_id,digest:row.plan.digest,confirmed:true,confirmed_source:row.source.name,remove_credentials:true},signal());
    setReviews(r=>r.map(item=>item.source.source_instance===row.source.source_instance?{...item,plan:value}:item));
    report(row.source.name,value.state==='FINALIZED'?t('Removed','Удалён'):t('Operation accepted; check its progress on the source page.','Операция принята; проверьте ход удаления в карточке источника.'));
   }catch(e){report(row.source.name,t('Result requires checking: ','Результат требует проверки: ')+String(e));}
  }
 });}
 return <section className="source-panel" aria-label={t('Bulk actions','Массовые действия')}>
 <p>{t('Selected on this page: ','Выбрано на этой странице: ')}{selected.length}. {t('Running synchronizations will finish.','Уже выполняющиеся синхронизации завершатся.')}</p>
 <div className="page-actions">
 {canSchedule&&<><button disabled={busy||!selected.length} onClick={()=>void run(()=>schedules([...selected],false))}>{t('Disable selected schedules','Отключить выбранные расписания')}</button><button disabled={busy||!selected.length} onClick={()=>{setTargets([...selected]);scheduleDialog.current?.showModal();}}>{t('Set schedule','Настроить расписание')}</button><button disabled={busy} onClick={()=>void disableAll()}>{t('Disable all scheduled sync, including pfSense','Отключить всю синхронизацию по расписанию, включая pfSense')}</button></>}
 {canRemove&&<button className="danger" disabled={busy||!selected.length} onClick={()=>void reviewDelete()}>{t('Delete resources','Удалить ресурсы')}</button>}
 </div>
 <div role="status" aria-live="polite">{busy&&<p>{t('Working…','Выполняется…')}</p>}<ul>{results.map((r,i)=><li key={i}>{r}</li>)}</ul></div>
 <dialog ref={scheduleDialog} className="sync-dialog"><h2>{t('Schedule for selected sources','Расписание выбранных источников')} ({targets.length})</h2><ul>{targets.map(s=><li key={s.source_instance}>{s.name} · {s.address} · {s.cluster_name}</li>)}</ul>
 <form className="bulk-schedule-form" onSubmit={e=>{e.preventDefault();scheduleDialog.current?.close();void run(()=>schedules(targets,true));}}>
 <label>{t('Mode','Режим')}<select value={mode} onChange={e=>{setMode(e.target.value);setDay(1);}}>{['interval','daily','weekly','monthly'].map(m=><option key={m} value={m}>{t(m,({interval:'Интервал',daily:'Ежедневно',weekly:'Еженедельно',monthly:'Ежемесячно'} as Record<string,string>)[m])}</option>)}</select></label>
 {mode==='interval'?<label>{t('Seconds','Секунды')}<input type="number" min={60} max={86400} step={1} required value={seconds} onChange={e=>setSeconds(Number(e.target.value))}/></label>:<><label>MSK<input type="time" required value={time} onChange={e=>setTime(e.target.value)}/></label>{mode!=='daily'&&<label>{mode==='weekly'?t('Weekday (1 = Monday)','День недели (1 = понедельник)'):t('Day of month','Число месяца')}<input type="number" min={1} max={mode==='weekly'?7:31} step={1} required value={day} onChange={e=>setDay(Number(e.target.value))}/></label>}</>}
 <button type="submit" disabled={busy}>{t('Apply to selected','Применить к выбранным')}</button><button type="button" onClick={()=>scheduleDialog.current?.close()}>{t('Cancel','Отмена')}</button></form></dialog>
 <dialog ref={deleteDialog} className="sync-dialog"><h2>{t('The following resources will be removed. Are you sure?','Следующие ресурсы будут удалены. Вы уверены?')}</h2><p>{t('Only verified owned NetBox objects and Sync registrations are removed. Real hosts and VMs, pfSense configuration and shared catalogs are preserved.','Удаляются только проверенные управляемые объекты NetBox и регистрации Sync. Реальные хосты и VM, конфигурация pfSense и общие справочники сохраняются.')}</p>
 {targets.map(source=>{const row=reviews.find(r=>r.source.source_instance===source.source_instance);return <section key={source.source_instance}><h3>{source.name} · {source.address} · {source.site_slug} / {source.cluster_name}</h3>{!row&&<p>{t('Checking…','Проверяем…')}</p>}{row?.error&&<p role="alert">{row.error}</p>}{row?.plan&&<><p>{row.plan.state} {row.plan.safe_code}</p><p>{t('NetBox objects to delete','Объекты NetBox к удалению')}: {row.plan.manifest.objects.length}</p><ul>{row.plan.manifest.objects.map(([key])=><li key={key}>{key}</li>)}</ul><p>{t('Preserved objects','Сохраняемые объекты')}: {row.plan.manifest.retained_cluster?'Cluster; ':''}{row.plan.manifest.retained?.map(o=>`${o.kind}:${o.id}`).join(', ')||'—'}</p></>}</section>})}
 <button type="button" onClick={()=>deleteDialog.current?.close()}>{t('Cancel / Close','Отмена / Закрыть')}</button><button className="danger" disabled={busy||attempted||!reviews.some(r=>r.plan?.state==='READY')||reviews.length!==targets.length} onClick={()=>void confirmDelete()}>{t('Yes, delete','Да, удалить')}</button></dialog>
 </section>;
}
