import {SourceInventoryAudit} from '../components/SourceInventoryAudit';
import {useCallback, useEffect, useRef, useState} from 'react';
import type {Source} from '../api/sources';
import {sourceLifecycle, type SourceLifecycle} from '../api/lifecycle';
import {retirement, retainedContext, RetirementError, type Retirement} from '../api/retirement';
import {useLanguage} from '../ui/language';
import {useResource} from '../ui/useResource';
import {Alert} from '../ui/primitives';

export function SourceRetirementPanel({source,onRemoved,retained=false}:{source:Pick<Source,'source_instance'|'name'>;retained?:boolean;onRemoved:(value:SourceLifecycle)=>void}) {
  const [language]=useLanguage(),t=(en:string,ru:string)=>language==='ru'?ru:en;
  const state=useResource(useCallback(signal=>retained?retainedContext(source.source_instance,signal):sourceLifecycle(source.source_instance,signal),[source.source_instance,retained]));
  const [review,setReview]=useState<Retirement|null>(null),[open,setOpen]=useState(false),[busy,setBusy]=useState(false);
  const [error,setError]=useState(''),[pending,setPending]=useState<string|null>(null),[attempted,setAttempted]=useState(false);
  const dialog=useRef<HTMLDialogElement>(null),trigger=useRef<HTMLButtonElement>(null);
  useEffect(()=>{if(open)dialog.current?.showModal();else dialog.current?.close();},[open]);
  useEffect(()=>{if(!retained&&state.data?.removed_at)onRemoved(state.data);},[state.data,onRemoved,retained]);
  useEffect(()=>{if(state.data?.retirement)setPending(state.data.retirement.operation_id);},[state.data?.retirement]);
  const errorText=(code:string)=>{
    if(code==='SOURCE_RETIREMENT_PENDING')return t('A previous removal needs its result checked.','Нужно проверить результат прежнего удаления.');
    if(code==='AUTH_DENIED')return t('Only an administrator can remove a source.','Удалять источники может только администратор.');
    if(code==='SOURCE_OPERATION_ACTIVE'||code==='SOURCE_APPLY_ACTIVE')return t('Wait for the active operation to finish.','Дождитесь завершения выполняющейся операции.');
    if(code==='SOURCE_APPLY_UNCONFIRMED')return t('Reconcile the previous synchronization before removal. Do not repeat apply.','Сначала сверьте результат прежней синхронизации. Не повторяйте применение.');
    const reason:Record<string,[string,string]>={
      RETIREMENT_PERMISSION_DENIED:['NetBox refused the service account. Check its guard permissions and object scope, then review again.','NetBox отказал служебной учётной записи. Проверьте её права guard и доступ к объектам, затем повторите просмотр.'],
      RETIREMENT_OWNERSHIP_UNPROVEN:['Creation ownership is unproved. Preserve these objects; source tags or matching names do not authorize deletion. Review creation receipts with the NetBox administrator.','Не доказано, что объекты созданы источником. Сохраните их: метки и имена не разрешают удаление. Проверьте квитанции создания с администратором NetBox.'],
      RETIREMENT_OWNERSHIP_CONFLICT:['Objects have conflicting ownership. Review their recorded source in NetBox; do not transfer them by name.','У объектов конфликтует принадлежность. Проверьте записанный источник в NetBox; не перепривязывайте их по имени.'],
      RETIREMENT_DEPENDENCIES_CHANGED:['Objects, placement or dependencies changed. Review the new list before confirming again.','Объекты, размещение или зависимости изменились. Проверьте новый список перед повторным подтверждением.'],
      RETIREMENT_MANUAL_CHANGE:['Manually changed fields are protected. Review these changes in NetBox before another removal review.','Ручные изменения защищены. Проверьте их в NetBox перед новым просмотром удаления.'],
      RETIREMENT_PROTECTED_DEPENDENCY:['A protected dependency prevents removal. Resolve it explicitly in NetBox, preserving shared and foreign objects, then review again.','Защищённая зависимость мешает удалению. Разрешите её явно в NetBox, сохранив общие и чужие объекты, затем повторите просмотр.'],
      RETIREMENT_GUARD_CHANGED:['The NetBox guard installation or protocol changed. Verify the pinned installation and compatible plugin before retrying.','Изменились установка или протокол NetBox guard. Проверьте привязку установки и совместимость плагина перед повтором.'],
    };
    if(reason[code])return t(...reason[code]);
    if(code==='RETIREMENT_BLOCKED')return t('Removal is blocked: ownership, dependencies or permission could not be verified. No completion is confirmed.','Удаление заблокировано: не подтверждены владение, зависимости или права. Завершение не подтверждено.');
    if(code==='SOURCE_LIFECYCLE_CONFLICT'||code==='RETIREMENT_CONFLICT')return t('The reviewed state changed. Reload and review it again.','Проверенное состояние изменилось. Обновите данные и проверьте список заново.');
    return t('The result could not be confirmed. Check the original operation; do not start another removal.','Результат не подтверждён. Проверьте исходную операцию; не начинайте новое удаление.');
  };
  const accept=async(result:Retirement)=>{
    setReview(result);setPending(result.operation_id);
    if(result.state==='BLOCKED'||result.state==='FINALIZED')setAttempted(false);
    if(result.state==='FINALIZED'){
      const current=await sourceLifecycle(source.source_instance,AbortSignal.timeout(15000));
      if(!current.removed_at)throw new RetirementError('RETIREMENT_CONFLICT');
      onRemoved(current);
    }
  };
  const read=async()=>{
    if(busy||!state.data?.revision)return;
    setOpen(true);setBusy(true);setError('');
    const operation=pending??crypto.randomUUID();setPending(operation);
    try{await accept(await retirement(source.source_instance,pending?'retirement-status':'retirement-review',
      {operation_id:operation,...(!pending?{revision:state.data.revision}:{})},AbortSignal.timeout(65000)));}
    catch(e){setError(errorText(e instanceof RetirementError?e.code:''));}
    finally{setBusy(false);}
  };
  const confirm=async(resume=false)=>{
    if(busy||!review||!state.data)return;
    setBusy(true);setError('');setAttempted(true);
    try{await accept(await retirement(source.source_instance,resume?'retirement-resume':'retire',{
      operation_id:review.operation_id,digest:review.digest,confirmed:true,confirmed_source:state.data.display_name,
      remove_credentials:review.remove_credentials??!retained},AbortSignal.timeout(65000)));}
    catch(e){setError(errorText(e instanceof RetirementError?e.code:''));state.refresh();}
    finally{setBusy(false);}
  };
  const check=async()=>{
    if(busy||!pending)return;
    setBusy(true);setError('');
    try{
      const result=await retirement(source.source_instance,'retirement-status',{operation_id:pending},AbortSignal.timeout(65000));
      if(['SENDING','UNCERTAIN','SUCCEEDED'].includes(result.state)&&state.data){
        await accept(await retirement(source.source_instance,'retire',{operation_id:result.operation_id,
          digest:result.digest,confirmed:true,confirmed_source:state.data.display_name,
          remove_credentials:result.remove_credentials??!retained},AbortSignal.timeout(65000)));
      }else{await accept(result);setAttempted(false);}
    }catch(e){setError(errorText(e instanceof RetirementError?e.code:''));}
    finally{setBusy(false);}
  };
  const pendingResult=attempted || review&&['SENDING','UNCERTAIN','SUCCEEDED'].includes(review.state);
  const kinds:Record<string,string>={cluster:t('Cluster','Кластер'),device:t('Host','Хост'),vm:t('VM','ВМ'),
    interface:t('Host interface','Интерфейс хоста'),vminterface:t('VM interface','Интерфейс ВМ'),
    disk:t('Disk','Диск'),ip:t('IP address','IP-адрес'),mac:t('MAC address','MAC-адрес')};
  return <section className="source-panel"><h3>{retained?t('Retire retained NetBox objects','Удалить сохранённые объекты NetBox'):t('Source removal','Удаление источника')}</h3>
    <p>{t('Review the exact NetBox objects owned by this source before confirming. Shared catalogs and run history are retained.',
      'Перед подтверждением проверьте точный список принадлежащих источнику объектов NetBox. Общие справочники и история запусков сохраняются.')}</p>
    {state.error&&<Alert retry={state.refresh}>{t('Removal state is unavailable.','Состояние удаления недоступно.')}</Alert>}
    {state.data?.removal_blocker&&<p role="alert">{errorText(state.data.removal_blocker)}</p>}
    <button ref={trigger} className="danger" disabled={busy||state.loading||state.error|| (!!state.data?.removal_blocker&&state.data.removal_blocker!=='SOURCE_RETIREMENT_PENDING')}
      onClick={read}>{pending?t('Check removal','Проверить удаление'):retained?t('Review retained objects','Проверить сохранённые объекты'):t('Remove Source','Удалить источник')}</button>
    <SourceInventoryAudit source={source.source_instance}/>
    <dialog ref={dialog} className="sync-dialog" onCancel={event=>{if(busy)event.preventDefault();else setOpen(false);}} aria-labelledby="retirement-title">
      <h2 id="retirement-title">{t('Remove source','Удалить источник')} {source.name}?</h2>
      {busy&&<p role="status">{t('Checking the operation…','Проверяем операцию…')}</p>}
      {error&&<p role="alert">{error}</p>}
      {review&&<><p>{t('Objects in the reviewed removal list:','Объектов в проверенном списке удаления:')} {review.manifest.objects.length}</p>
        <details><summary>{t('View every object','Просмотреть все объекты')}</summary><ul>{review.manifest.objects.map(([key])=>{
          const [kind,id]=key.split(':');return <li key={key}>{kinds[kind]} · NetBox ID {id}</li>;
        })}</ul></details>
        {review.manifest.retained_cluster&&<p>{t('The selected cluster is not owned by this source and will be retained.','Выбранный кластер не принадлежит источнику и будет сохранён.')}</p>}
        {review.state==='READY'&&<p>{retained?t('Only the verified NetBox list will be removed. Source history and the existing credential-retention decision stay unchanged.','Будет удалён только проверенный список NetBox. История источника и прежнее решение о сохранении данных доступа не меняются.'):t('Confirmation stops synchronization and deletes only this verified list. Exclusive local credentials will then be removed. Provider access is not revoked.',
          'Подтверждение остановит синхронизацию и удалит только этот проверенный список. Затем будут удалены исключительно принадлежащие источнику локальные данные доступа. Доступ у провайдера не отзывается.')}</p>}
        {pendingResult&&<p role="alert">{t('Removal is not yet confirmed. Checking the result reads the original receipt without repeating NetBox deletion.',
          'Удаление пока не подтверждено. Проверка результата читает исходную квитанцию и не повторяет удаление в NetBox.')}</p>}
        {review.state==='BLOCKED'&&<p role="alert">{errorText(review.safe_code??'RETIREMENT_BLOCKED')}</p>}</>}
      <div className="page-actions"><button disabled={busy} onClick={()=>{setOpen(false);trigger.current?.focus();}}>{t('Close','Закрыть')}</button>
        {review?.state==='READY'&&!attempted&&<button className="danger" disabled={busy} onClick={()=>confirm()}>{t('Confirm removal','Подтвердить удаление')}</button>}
        {review?.state==='UNCERTAIN'&&<><p>{t(
          'If the original request did not reach NetBox, you can explicitly continue the same removal. The server checks the original receipt and object list again; it does not create a new operation.',
          'Если исходный запрос не дошёл до NetBox, можно явно продолжить то же удаление. Сервер заново проверит исходную квитанцию и список объектов; новая операция не создаётся.')}</p>
          <button className="danger" disabled={busy} onClick={()=>confirm(true)}>{t('Confirm continuation','Подтвердить продолжение')}</button></>}
        {pendingResult&&review?.state!=='BLOCKED'&&<button disabled={busy} onClick={check}>{t('Check result','Проверить результат')}</button>}
        {!review&&pending&&<button disabled={busy} onClick={check}>{t('Check result','Проверить результат')}</button>}
        {(review?.state==='BLOCKED'||(!review&&error&&!attempted))&&<button disabled={busy} onClick={()=>{
          setReview(null);setPending(null);setAttempted(false);setOpen(false);state.refresh();
        }}>{t('Review again','Проверить заново')}</button>}
      </div>
    </dialog>
  </section>;
}
