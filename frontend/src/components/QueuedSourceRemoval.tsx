import {retirementReason,retirementProgress} from '../ui/retirementFeedback';
import {useEffect,useRef,useState} from 'react';
import {useNavigate} from 'react-router-dom';
import {sourceLifecycle,type SourceLifecycle} from '../api/lifecycle';
import {useLanguage} from '../ui/language';

class DefiniteRemovalRefusal extends Error {}
type Progress={source_instance:string;operation_id:string;state:string;safe_code?:string|null;purged?:boolean};
/** Confirmation is durable; only status reads originate from the poll loop. */
export function QueuedSourceRemoval({source,name,lifecycle}:{source:string;name:string;lifecycle:SourceLifecycle}){
 const [language]=useLanguage(),t=(en:string,ru:string)=>language==='ru'?ru:en,navigate=useNavigate();
 const [operation,setOperation]=useState(lifecycle.retirement?.queued?lifecycle.retirement.operation_id:null);
 const [progress,setProgress]=useState<Progress|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false),[open,setOpen]=useState(false);
 const [retryRevision,setRetryRevision]=useState<string|null>(null),[displayName,setDisplayName]=useState(name);
 const dialog=useRef<HTMLDialogElement>(null),polling=useRef(false);
 useEffect(()=>{if(open)dialog.current?.showModal();else dialog.current?.close();},[open]);
 const message=(code?:string|null)=>retirementReason(code)?t(...retirementReason(code)!):code==='RETIREMENT_SOURCE_OBJECTS_REMAIN'?t('Source-related objects remain in NetBox outside the expected cluster. Check ownership and dependencies before reviewing removal again.','В NetBox остались связанные с источником объекты вне ожидаемого кластера. Проверьте принадлежность и зависимости перед повторной проверкой удаления.'):code==='SOURCE_APPLY_UNCONFIRMED'?t('The previous synchronization outcome is unknown. Removal is blocked until that outcome is reconciled. Do not repeat synchronization.','Результат прежней синхронизации неизвестен. Удаление заблокировано до его сверки. Не повторяйте синхронизацию.'):code==='SOURCE_LIFECYCLE_CONFLICT'?t('Source settings changed. Review the source before confirming removal again.','Настройки источника изменились. Проверьте источник перед новым подтверждением удаления.'):t('Removal could not be completed safely. Review the source diagnostics and NetBox integration permissions.','Безопасно завершить удаление не удалось. Проверьте диагностику источника и права интеграции NetBox.');
 async function call(action:string,body:object){
  const response=await fetch(`/api/v1/sources/${encodeURIComponent(source)}/${action}`,{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json','X-NetBox-Sync-CSRF':'same-origin'},body:JSON.stringify(body),signal:AbortSignal.timeout(20000)});
  const value=await response.json();if(!response.ok){if(response.status>=400&&response.status<500)throw new DefiniteRemovalRefusal(message(value?.error?.code));throw new Error(message(value?.error?.code));}
  if(value.source_instance!==source||!['WAITING','READY','SENDING','UNCERTAIN','SUCCEEDED','FINALIZED','BLOCKED'].includes(value.state))throw new Error(t('Removal state is unavailable.','Состояние удаления недоступно.'));
  return value as Progress;
 }
 useEffect(()=>{if(!operation||progress?.state==='FINALIZED'||progress?.state==='BLOCKED')return;let stopped=false;
  async function check(){if(polling.current)return;polling.current=true;try{const value=await call('removal-status',{operation_id:operation});if(value.operation_id!==operation)throw new Error(t('Removal state is unavailable.','Состояние удаления недоступно.'));if(stopped)return;setProgress(value);setError('');if(value.state==='FINALIZED'&&value.purged===true)navigate('/sources',{replace:true,state:{removedSource:name}});}catch(e){if(!stopped)setError(e instanceof Error?e.message:t('Removal state is unavailable.','Состояние удаления недоступно.'));}finally{polling.current=false;}}
  void check();const timer=window.setInterval(()=>void check(),5000);return()=>{stopped=true;window.clearInterval(timer);};
 },[operation,progress?.state]);
 async function confirm(){if(busy||operation||!lifecycle.revision)return;setBusy(true);setError('');const id=crypto.randomUUID();
  // Retain the nonce even if the response is lost; status resolves this request.
  setOperation(id);try{const value=await call('removal-request',{operation_id:id,revision:retryRevision??lifecycle.revision,confirmed:true});setProgress(value);setOpen(false);}catch(e){if(e instanceof DefiniteRemovalRefusal)setOperation(null);setError(e instanceof Error?e.message:message());}finally{setBusy(false);}}
 return <section className="source-panel"><h3>{t('Source removal','Удаление источника')}</h3>
  <p>{operation?t('New runs are paused. The server waits for the active operation, then removes only verified source-owned resources. You can close this page.','Новые запуски приостановлены. Сервер дождётся текущей операции, затем удалит только ресурсы с подтверждённой принадлежностью источнику. Страницу можно закрыть.'):t('An operation is running. You can request removal now; it will begin when the operation has finished safely.','Операция выполняется. Можно запросить удаление сейчас: оно начнётся после её безопасного завершения.')}</p>
  {error&&<p role="alert">{error}</p>}
  {progress?.state==='BLOCKED'?<p role="alert">{message(progress.safe_code)}</p>:operation&&<p role="status">{t(...retirementProgress(progress?.state??'WAITING',progress?.safe_code))}</p>}
  {progress?.state==='BLOCKED'&&<button disabled={busy} onClick={async()=>{setBusy(true);try{const current=await sourceLifecycle(source,AbortSignal.timeout(15000));setRetryRevision(current.revision);setDisplayName(current.display_name);setOperation(null);setProgress(null);setOpen(true);}catch{setError(t('Current source state is unavailable.','Текущее состояние источника недоступно.'));}finally{setBusy(false);}}}>{t('Review removal again','Проверить удаление заново')}</button>}
  {!operation&&<button className="danger" onClick={()=>setOpen(true)}>{t('Remove source','Удалить источник')}</button>}
  <dialog ref={dialog} className="sync-dialog" onCancel={()=>setOpen(false)} aria-labelledby="queued-removal-title"><h2 id="queued-removal-title">{t('Remove source','Удалить источник')} {displayName}?</h2>
   <p>{t('New synchronization runs will stop. The active operation may finish creating objects; these will also be checked for removal. Only resources whose creation and ownership are verified will be deleted. Shared and foreign objects remain. Source settings, exclusive credentials and run history will then be cleared.','Новые синхронизации будут остановлены. Текущая операция может завершить создание объектов — они также войдут в проверку удаления. Будут удалены только ресурсы с доказанным созданием и принадлежностью. Общие и чужие объекты сохранятся. Затем будут очищены настройки источника, его отдельные данные доступа и история запусков.')}</p>
   <div className="page-actions"><button onClick={()=>setOpen(false)}>{t('Cancel','Отмена')}</button><button className="danger" disabled={busy} onClick={()=>void confirm()}>{t('Confirm removal','Подтвердить удаление')}</button></div>
  </dialog>
 </section>;
}
