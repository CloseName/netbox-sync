import {useState} from 'react';
type Row={model:string;id:number;name:string;url:string;provider_key?:string;reason?:string};
type Pending={operation:string;key?:string|null;fingerprint:string};
type Plan=Pending&{delete:Row[];retain:Row[];bindings?:Row[];blockers:{reason:string;name?:string;model?:string;id?:number;url?:string}[];remove_registry?:boolean};
const reasons:Record<string,string>={
 legacy_ipam_provenance_required:'В аккаунте есть прежние IPAM-объекты без подтверждённого происхождения. Удаление аккаунта остановлено, чтобы не потерять существующие IP и сетевые связи.',
 foreign_dependencies_or_sync_source:'Удаляемый объект используется другим источником или имеет зависимые объекты. Требуется проверка связей администратором.',
 provider_network_links_present:'Есть управляемые сетевые связи Selectel. Их нужно отдельно проверить перед отсоединением.',
 creation_identity_changed:'Карточка заменена после создания. Требуется проверка администратора.',
 binding_target_changed:'Связанная карточка изменилась или удалена. Требуется проверка администратора.',
 unsupported_owned_model:'Для этого типа объекта удаление пока не поддерживается.'};
export function SelectelLifecycle({account,disabled,uncertainRun,pending,busy,request,refresh}:{account:string;disabled:boolean;uncertainRun?:string;pending?:Pending;busy:boolean;
 request:(path:string,body:unknown)=>Promise<unknown>;refresh:()=>void}){
 const [plan,setPlan]=useState<Plan|null>(null),[waiting,setWaiting]=useState(false),[error,setError]=useState(''),[confirm,setConfirm]=useState(false);
 async function review(operation:string,key?:string){setWaiting(true);setError('');setConfirm(false);try{
  if(operation==='delete'&&!disabled)await request('/'+account+'/enabled',{enabled:false});
  setPlan(await request('/'+account+'/lifecycle-review',{operation,key:key??null}) as Plan);
 }catch(e){setError((e as Error).message);}finally{setWaiting(false);refresh();}}
 async function execute(value:Pending){setWaiting(true);setError('');try{
  await request('/'+account+'/lifecycle-execute',{operation:value.operation,key:value.key??null,fingerprint:value.fingerprint,confirmed:true});
  setPlan(null);setConfirm(false);
 }catch(e){setError((e as Error).message);}finally{setWaiting(false);refresh();}}
 return <details><summary>Отсоединение и удаление</summary>
 {error&&<p role="alert">{error}</p>}
 {!disabled&&<p>При подготовке удаления новые запуски аккаунта будут отключены.</p>}
 {pending?<><p role="alert">Результат предыдущего решения не подтверждён. Аккаунт остаётся отключённым. Проверьте результат той же операции.</p>
 <button disabled={busy||waiting} onClick={()=>void execute(pending)}>Проверить результат операции</button></>:<button disabled={busy||waiting}
 onClick={()=>void review('delete',uncertainRun)}>Удалить аккаунт</button>}
 {plan&&!pending&&<section aria-label="План изменения аккаунта">
 <p>{plan.operation==='activate'?'После подтверждения можно заново указать доступ к аккаунту.':plan.operation==='detach'?'Карточка, её IP и связи других источников сохранятся. Автоматическое сопоставление этого ресурса будет отключено.':'Удаляются созданные этим аккаунтом объекты и весь реестр аккаунта: серверы, DNS и объектное хранилище. Ранее существовавшие карточки сохраняются, сведения Selectel отсоединяются. Пароль и расписание аккаунта удаляются.'}</p>
 {plan.operation==='delete'&&<p>Будут удалены объекты импорта: {plan.delete.length}. Сведения и привязки Selectel будут сняты с ранее существовавших объектов: {plan.retain.length}. Их карточки и собственные IP сохранятся. Действие нельзя отменить.</p>}
 {plan.operation==='delete'&&plan.key&&<p>Результат старого импорта останется неизвестным. При удалении этот запуск будет закрыт для повторной записи. Удаление выполняется по текущим ресурсам и подтверждённому происхождению объектов.</p>}
 {plan.blockers.length>0&&<div role="alert"><strong>Удаление пока невозможно</strong>
 <p>Нужно устранить препятствия. Ничего не удалено.</p>
 {[...new Set(plan.blockers.map(b=>b.reason))].map(reason=><p key={reason}>{reasons[reason]||'Требуется проверка зависимостей.'} Объектов: {plan.blockers.filter(b=>b.reason===reason).length}.</p>)}
 <details><summary>Показать препятствия</summary><ul>{plan.blockers.map((b,i)=><li key={i}>{b.url?<a href={b.url}>{b.name||`${b.model} #${b.id}`}</a>:b.name||`${b.model||'Объект'} ${b.id||''}`}</li>)}</ul></details></div>}
 {plan.operation==='delete'&&plan.bindings?.some(r=>r.provider_key)? <details><summary>Отсоединить отдельный ресурс без удаления</summary><p>Это отдельное действие: карточка останется в NetBox. Для удаления всего аккаунта оно не требуется.</p><ul>{plan.bindings.filter(r=>r.provider_key).map(r=><li key={r.provider_key}>{r.name} <button disabled={waiting||busy} onClick={()=>void review('detach',r.provider_key)}>Проверить отсоединение</button></li>)}</ul></details>:null}
 <label><input type="checkbox" checked={confirm} onChange={e=>setConfirm(e.target.checked)}/>Я понимаю последствия и подтверждаю {plan.operation==='delete'?'удаление аккаунта и его импортированных ресурсов':plan.operation==='detach'?'отсоединение':'повторное подключение'}.</label>
 <button disabled={!disabled||!confirm||plan.blockers.length>0||waiting||busy} onClick={()=>void execute(plan)}>{plan.operation==='delete'?'Подтвердить удаление аккаунта':'Применить проверенный план'}</button>
 </section>}
 </details>;
}
