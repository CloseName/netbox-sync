import {retirementReason,retirementProgress} from '../ui/retirementFeedback';
import {QueuedSourceRemoval} from '../components/QueuedSourceRemoval';
import {useNavigate} from 'react-router-dom';
import {SourceInventoryAudit,permissionErrors} from '../components/SourceInventoryAudit';
import {useCallback, useEffect, useRef, useState} from 'react';
import type {Source} from '../api/sources';
import {sourceLifecycle, type SourceLifecycle} from '../api/lifecycle';
import {retirement, retainedContext, RetirementError, type Retirement} from '../api/retirement';
import {useLanguage} from '../ui/language';
import {useResource} from '../ui/useResource';
import {Alert} from '../ui/primitives';

export function SourceRetirementPanel({source,onRemoved,retained=false,archive=false}:{source:Pick<Source,'source_instance'|'name'>;retained?:boolean;archive?:boolean;onRemoved:(value:SourceLifecycle)=>void}) {
  const navigate=useNavigate();
  const [language]=useLanguage(),t=(en:string,ru:string)=>language==='ru'?ru:en;
  const state=useResource(useCallback(signal=>retained?retainedContext(source.source_instance,signal):sourceLifecycle(source.source_instance,signal),[source.source_instance,retained]));
  const [review,setReview]=useState<Retirement|null>(null),[open,setOpen]=useState(false),[busy,setBusy]=useState(false);
  const [error,setError]=useState(''),[pending,setPending]=useState<string|null>(null),[attempted,setAttempted]=useState(false);
  const dialog=useRef<HTMLDialogElement>(null),trigger=useRef<HTMLButtonElement>(null);
  useEffect(()=>{if(open)dialog.current?.showModal();else dialog.current?.close();},[open]);
  useEffect(()=>{if(!retained&&state.data?.removed_at&&!state.data.retirement)onRemoved(state.data);},[state.data,onRemoved,retained]);
  useEffect(()=>{if(!state.data?.retirement?.queued&&state.data?.retirement&&state.data.retirement.state!=='FINALIZED'&&!(archive&&state.data.retirement.archive_required))setPending(state.data.retirement.operation_id);},[state.data?.retirement,archive]);
  const errorText=(code:string)=>{
    if(permissionErrors[code])return t(...permissionErrors[code]);
    if(code==='SOURCE_RETIREMENT_PENDING')return t('Removal is already in progress. Its result is checked automatically.','Удаление уже выполняется. Результат проверяется автоматически.');
    if(code==='AUTH_DENIED')return t('Only an administrator can remove a source.','Удалять источники может только администратор.');
    if(code==='SOURCE_OPERATION_ACTIVE'||code==='SOURCE_APPLY_ACTIVE')return t('Wait for the active operation to finish.','Дождитесь завершения выполняющейся операции.');
    if(code==='SOURCE_APPLY_UNCONFIRMED')return t('Reconcile the previous synchronization before removal. Do not repeat apply.','Сначала сверьте результат прежней синхронизации. Не повторяйте применение.');
    const reason:Record<string,[string,string]>={
      RETIREMENT_SOURCE_OBJECTS_REMAIN:['The cluster is missing or its placement changed, but source-related objects remain in NetBox, possibly detached. Removal is blocked to protect those objects. Review ownership and dependencies in Ownership details; do not register the host again.','Кластер отсутствует или размещение изменилось, но в NetBox остались связанные с источником объекты, возможно отвязанные. Удаление заблокировано для их защиты. Проверьте принадлежность и зависимости в сведениях об источнике; не добавляйте хост заново.'],
      SOURCE_RECOVERY_OUTCOME_UNCERTAIN:['An earlier recovery may have stored credentials. Resume that recovery from the source page before closing this generation; do not start another registration.','Предыдущее восстановление могло сохранить данные доступа. Продолжите его на странице источника перед закрытием поколения; не начинайте другую регистрацию.'],
      SOURCE_CREDENTIAL_CLEANUP_PENDING:['NetBox removal is confirmed. Local credential cleanup is pending and will be retried automatically. Shared credentials are preserved.','Удаление в NetBox подтверждено. Очистка локальных данных доступа ещё не завершена и будет повторена автоматически. Общие данные доступа сохраняются.'],
      SOURCE_ARCHIVED:['This generation is closed. Add the server as a new source.','Это поколение закрыто. Добавьте сервер как новый источник.'],
      RETIREMENT_PERMISSION_DENIED:['NetBox refused the service account. Check its guard permissions and object scope, then review again.','NetBox отказал служебной учётной записи. Проверьте её права guard и доступ к объектам, затем повторите просмотр.'],
      RETIREMENT_OWNERSHIP_UNPROVEN:['Creation ownership is unproved. Preserve these objects; source tags or matching names do not authorize deletion. Review creation receipts with the NetBox administrator.','Не доказано, что объекты созданы источником. Сохраните их: метки и имена не разрешают удаление. Проверьте квитанции создания с администратором NetBox.'],
      RETIREMENT_OWNERSHIP_CONFLICT:['Objects have conflicting ownership. Review their recorded source in NetBox; do not transfer them by name.','У объектов конфликтует принадлежность. Проверьте записанный источник в NetBox; не перепривязывайте их по имени.'],
      RETIREMENT_DEPENDENCIES_CHANGED:['Objects, placement or dependencies changed. Review the new list before confirming again.','Объекты, размещение или зависимости изменились. Проверьте новый список перед повторным подтверждением.'],
      RETIREMENT_MANUAL_CHANGE:['Manually changed fields are protected. Review these changes in NetBox before another removal review.','Ручные изменения защищены. Проверьте их в NetBox перед новым просмотром удаления.'],
      RETIREMENT_PROTECTED_DEPENDENCY:['A protected dependency prevents removal. Resolve it explicitly in NetBox, preserving shared and foreign objects, then review again.','Защищённая зависимость мешает удалению. Разрешите её явно в NetBox, сохранив общие и чужие объекты, затем повторите просмотр.'],
      RETIREMENT_GUARD_CHANGED:['The NetBox guard installation or protocol changed. Verify the pinned installation and compatible plugin before retrying.','Изменились установка или протокол NetBox guard. Проверьте привязку установки и совместимость плагина перед повтором.'],
    };
    const timing=retirementReason(code);if(timing)return t(...timing);
    if(reason[code])return t(...reason[code]);
    if(code==='RETIREMENT_BLOCKED')return t('Removal is blocked: ownership, dependencies or permission could not be verified. No completion is confirmed.','Удаление заблокировано: не подтверждены владение, зависимости или права. Завершение не подтверждено.');
    if(code==='SOURCE_LIFECYCLE_CONFLICT'||code==='RETIREMENT_CONFLICT')return t('The reviewed state changed. Reload and review it again.','Проверенное состояние изменилось. Обновите данные и проверьте список заново.');
    return t('The result could not be confirmed. Check the original operation; do not start another removal.','Результат не подтверждён. Проверьте исходную операцию; не начинайте новое удаление.');
  };
  const accept=async(result:Retirement)=>{
    setReview(result);setPending(result.operation_id);
    if(result.state==='READY'||result.state==='BLOCKED'||result.state==='FINALIZED')setAttempted(false);
    if(result.state==='FINALIZED'){
      if(result.purged){navigate('/sources',{replace:true,state:{removedSource:source.name}});return;}
      const current=await sourceLifecycle(source.source_instance,AbortSignal.timeout(15000));
      if(!current.removed_at)throw new RetirementError('RETIREMENT_CONFLICT');
      onRemoved(current);
    }
  };
  const read=async()=>{
    if(busy||!state.data?.revision)return;
    setOpen(true);setBusy(true);setError('');
    const operation=pending??crypto.randomUUID();setPending(operation);
    try{await accept(await retirement(source.source_instance,pending?'retirement-status':archive?'archive-review':'retirement-review',
      {operation_id:operation,...(!pending?{revision:state.data.revision}:{})},AbortSignal.timeout(175000)));}
    catch(e){setError(errorText(e instanceof RetirementError?e.code:''));}
    finally{setBusy(false);}
  };
  const confirm=async(resume=false)=>{
    if(busy||!review||!state.data)return;
    setBusy(true);setError('');setAttempted(true);
    try{await accept(await retirement(source.source_instance,resume?'retirement-resume':'retire',{
      operation_id:review.operation_id,digest:review.digest,confirmed:true,confirmed_source:state.data.display_name,
      remove_credentials:true},AbortSignal.timeout(175000)));}
    catch(e){setReview({...review,state:'UNCERTAIN',safe_code:'RETIREMENT_UNCERTAIN'});setError(errorText(e instanceof RetirementError?e.code:''));state.refresh();}
    finally{setBusy(false);}
  };
  const check=async()=>{
    if(busy||!pending)return;
    setBusy(true);setError('');
    try{
      const result=await retirement(source.source_instance,'retirement-status',{operation_id:pending},AbortSignal.timeout(175000));
      await accept(result);
    }catch(e){setError(errorText(e instanceof RetirementError?e.code:''));}
    finally{setBusy(false);}
  };
  const checkRef=useRef(check);checkRef.current=check;
  useEffect(()=>{
    if(!pending||review?.state==='FINALIZED'||review?.state==='BLOCKED'||review?.state==='READY')return;
    const timer=window.setInterval(()=>void checkRef.current(),5000);
    void checkRef.current();
    return()=>window.clearInterval(timer);
  },[pending,review?.state]);
  const pendingResult=attempted || review&&['SENDING','UNCERTAIN','SUCCEEDED'].includes(review.state);
  const kinds:Record<string,string>={cluster:t('Cluster','Кластер'),device:t('Host','Хост'),vm:t('VM','ВМ'),
    interface:t('Host interface','Интерфейс хоста'),vminterface:t('VM interface','Интерфейс ВМ'),
    disk:t('Disk','Диск'),ip:t('IP address','IP-адрес'),mac:t('MAC address','MAC-адрес')};
  if(!retained&&!archive&&state.data&&(state.data.retirement?.queued||state.data.removal_blocker==='SOURCE_OPERATION_ACTIVE'))return <QueuedSourceRemoval source={source.source_instance} name={source.name} lifecycle={state.data}/>;
  return <section className="source-panel"><h3>{archive?t('Close historical registration','Завершить старую регистрацию'):retained?t('Retire retained NetBox objects','Удалить сохранённые объекты NetBox'):t('Source removal','Удаление источника')}</h3>
    <p>{t('Review the exact NetBox objects owned by this source before confirming. Shared catalogs are retained. On completion, source settings, credentials and run history in Sync are removed.',
      'Перед подтверждением проверьте точный список принадлежащих источнику объектов NetBox. Общие справочники сохраняются. После завершения настройки, данные доступа и история этого источника в Sync удаляются.')}</p>
    {state.error&&<Alert retry={state.refresh}>{t('Removal state is unavailable.','Состояние удаления недоступно.')}</Alert>}
    {state.data?.removal_blocker&&<p role="alert">{errorText(state.data.removal_blocker)}</p>}
    <button ref={trigger} className="danger" disabled={busy||state.loading||state.error|| (!!state.data?.removal_blocker&&state.data.removal_blocker!=='SOURCE_RETIREMENT_PENDING')}
      onClick={read}>{pending?t('Removal progress','Ход удаления'):archive?t('Review archive','Проверить архивирование'):retained?t('Review retained objects','Проверить сохранённые объекты'):t('Remove Source','Удалить источник')}</button>
    {pendingResult&&<p role="status">{t(...retirementProgress(attempted&&review?.state==='READY'?'SUBMITTING':review?.state,review?.safe_code))}</p>}
    <details><summary>{t('Ownership details','Сведения о принадлежности')}</summary><SourceInventoryAudit source={source.source_instance}/></details>
    <dialog ref={dialog} className="sync-dialog" onCancel={()=>setOpen(false)} aria-labelledby="retirement-title">
      <h2 id="retirement-title">{archive?t('Archive registration','Архивировать регистрацию'):t('Remove source','Удалить источник')} {source.name}?</h2>
      {busy&&<p role="status">{t('Checking the operation…','Проверяем операцию…')}</p>}
      {error&&error!==(review?.safe_code?errorText(review.safe_code):null)&&<p role="alert">{error}</p>}
      {review?.manifest.retained&&<><p>{t('Objects preserved (not a deletion list)','Сохраняемые объекты (не список удаления)')}</p><ul>{review.manifest.retained.map(o=><li key={o.kind+o.id}>{kinds[o.kind]??o.kind} · NetBox ID {o.id} · {o.present?t('present','существует'):t('already absent','уже отсутствует')} · {o.claimed?t('creation claim recorded','квитанция создания записана'):t('creation not proved','создание не доказано')}</li>)}</ul></>}
      {review&&<><p>{t('Objects in the reviewed removal list:','Объектов в проверенном списке удаления:')} {review.manifest.objects.length}</p>
        <details><summary>{t('View every object','Просмотреть все объекты')}</summary><ul>{review.manifest.objects.map(([key])=>{
          const [kind,id]=key.split(':');return <li key={key}>{kinds[kind]} · NetBox ID {id}</li>;
        })}</ul></details>
        {review.manifest.cluster_missing&&<p>{t('The cluster is already absent. No source-related objects were found. Confirmation will check again and finish removing the source from Sync.','Кластер уже отсутствует. Связанных с источником объектов не найдено. После подтверждения сервер повторит проверку и завершит удаление источника из Sync.')}</p>}
        {!archive&&review.manifest.retained_cluster&&<p>{t('The selected cluster is not owned by this source and will be retained.','Выбранный кластер не принадлежит источнику и будет сохранён.')}</p>}
        {review.state==='READY'&&<p>{archive?t('Close this registration permanently and release its active UUID claim. All NetBox objects below are retained and protected; a new source gets a new Source ID and cannot adopt them. The old execution result remains unchanged.','Завершить регистрацию и освободить активный резерв UUID. Все перечисленные объекты NetBox сохраняются и защищены; новый источник получит новый Source ID без права присвоить их. Исторический результат запусков не меняется.'):retained?t('Only the verified NetBox list will be removed. Source history and exclusively owned local credentials will be removed.','Будет удалён только проверенный список NetBox. История источника и исключительно принадлежащие ему локальные данные доступа будут удалены.'):t('Confirmation stops synchronization and deletes only this verified list. Exclusive local credentials will then be removed. Provider access is not revoked.',
          'Подтверждение остановит синхронизацию и удалит только этот проверенный список. Затем будут удалены исключительно принадлежащие источнику локальные данные доступа. Доступ у провайдера не отзывается.')}</p>}
        {pendingResult&&<p role="alert">{t('Removal is in progress. The server checks its result and continues the confirmed operation automatically. You can close this page.',
          'Удаление выполняется. Сервер проверяет результат и автоматически продолжает подтверждённую операцию. Страницу можно закрыть.')}</p>}
        {review.safe_code&&review.state!=='BLOCKED'&&<p role="alert">{errorText(review.safe_code)}</p>}{review.state==='BLOCKED'&&<p role="alert">{errorText(review.safe_code??'RETIREMENT_BLOCKED')}</p>}</>}
      <div className="page-actions"><button onClick={()=>{setOpen(false);trigger.current?.focus();}}>{t('Close','Закрыть')}</button>
        {review?.state==='READY'&&!attempted&&<button className="danger" disabled={busy} onClick={()=>confirm()}>{archive?t('Confirm archive','Подтвердить архивирование'):t('Confirm removal','Подтвердить удаление')}</button>}
        {review?.state==='SUCCEEDED'&&review.remove_credentials===false&&<><p>{t('NetBox removal is confirmed, but the earlier request retained credentials. Confirm exclusive local credential cleanup to finish closing this registration. Shared credentials remain.','Удаление в NetBox подтверждено, но прежний запрос сохранял данные доступа. Подтвердите очистку исключительно принадлежащих источнику локальных данных для завершения регистрации. Общие данные доступа сохраняются.')}</p><button className="danger" disabled={busy} onClick={()=>confirm()}>{t('Confirm credential cleanup','Подтвердить очистку данных доступа')}</button></>}
        {(review?.state==='BLOCKED'||(!review&&error&&!attempted))&&<button disabled={busy} onClick={()=>{
          setReview(null);setPending(null);setAttempted(false);setOpen(false);state.refresh();
        }}>{t('Review again','Проверить заново')}</button>}
      </div>
    </dialog>
  </section>;
}
