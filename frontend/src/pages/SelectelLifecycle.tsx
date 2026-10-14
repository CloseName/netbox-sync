import {useState} from 'react';
type Row={model:string;id:number;name:string;url:string;provider_key?:string;reason?:string};
type Pending={operation:string;key?:string|null;fingerprint:string};
type Plan=Pending&{delete:Row[];retain:Row[];bindings?:Row[];blockers:{reason:string;name?:string}[];remove_registry?:boolean};
const reasons:Record<string,string>={
 legacy_ipam_provenance_required:'В аккаунте есть прежние IPAM-объекты без подтверждённого происхождения. Удаление аккаунта остановлено, чтобы не потерять существующие IP и сетевые связи.',
 foreign_dependencies_or_sync_source:'Есть связи другого источника Sync или зависимые объекты. Отсоедините ресурс от Selectel, чтобы сохранить его.',
 provider_network_links_present:'Есть управляемые сетевые связи Selectel. Их нужно отдельно проверить перед отсоединением.',
 creation_identity_changed:'Карточка заменена после создания. Требуется проверка администратора.',
 binding_target_changed:'Связанная карточка изменилась или удалена. Требуется проверка администратора.',
 unsupported_owned_model:'Для этого типа объекта удаление пока не поддерживается.'};
export function SelectelLifecycle({account,disabled,deleted,pending,busy,request,refresh}:{account:string;disabled:boolean;deleted?:boolean;pending?:Pending;busy:boolean;
 request:(path:string,body:unknown)=>Promise<unknown>;refresh:()=>void}){
 const [plan,setPlan]=useState<Plan|null>(null),[waiting,setWaiting]=useState(false),[error,setError]=useState(''),[confirm,setConfirm]=useState(false);
 async function review(operation:string,key?:string){setWaiting(true);setError('');setConfirm(false);try{
  setPlan(await request('/'+account+'/lifecycle-review',{operation,key:key??null}) as Plan);
 }catch(e){setError((e as Error).message);}finally{setWaiting(false);refresh();}}
 async function execute(value:Pending){setWaiting(true);setError('');try{
  await request('/'+account+'/lifecycle-execute',{operation:value.operation,key:value.key??null,fingerprint:value.fingerprint,confirmed:true});
  setPlan(null);setConfirm(false);
 }catch(e){setError((e as Error).message);}finally{setWaiting(false);refresh();}}
 return <details><summary>Отсоединение и удаление</summary>
 {error&&<p role="alert">{error}</p>}
 {!disabled&&<p>Сначала отключите аккаунт. Проверка не требует ручной остановки планировщика.</p>}
 {pending?<><p role="alert">Результат предыдущего решения не подтверждён. Аккаунт остаётся отключённым. Проверьте результат той же операции.</p>
 <button disabled={busy||waiting} onClick={()=>void execute(pending)}>Проверить результат операции</button></>:<button disabled={!disabled||busy||waiting}
 onClick={()=>void review(deleted?'activate':'delete')}>{deleted?'Подготовить повторное подключение':'Проверить ресурсы перед удалением'}</button>}
 {plan&&!pending&&<section aria-label="План изменения аккаунта">
 <p>{plan.operation==='activate'?'После подтверждения можно заново указать доступ к аккаунту.':plan.operation==='detach'?'Карточка, её IP и связи других источников сохранятся. Автоматическое сопоставление этого ресурса будет отключено.':'Удаляются созданные этим аккаунтом карточки из списка и весь реестр аккаунта: серверы, DNS и объектное хранилище. Ранее существовавшие карточки сохраняются, сведения Selectel отсоединяются. Пароль и расписание аккаунта удаляются.'}</p>
 {(['delete','retain'] as const).map(kind=><div key={kind}><h3>{kind==='delete'?'Будут удалены':'Будут сохранены'}: {plan[kind].length}</h3><ul>{plan[kind].map(row=><li key={row.model+row.id}>{row.name} (#{row.id})</li>)}</ul></div>)}
 {plan.blockers.map((b,i)=><p role="alert" key={i}>{b.name&&b.name+': '}{reasons[b.reason]||'Удаление заблокировано: требуется проверка зависимостей.'}</p>)}
 {plan.operation==='delete'&&plan.bindings?.length? <details><summary>Отсоединить отдельный ресурс</summary><p>Сохранит существующую карточку и исключит её из дальнейшего управления этим аккаунтом.</p><ul>{plan.bindings.filter(r=>r.provider_key).map(r=><li key={r.provider_key}>{r.name} <button disabled={waiting||busy} onClick={()=>void review('detach',r.provider_key)}>Проверить отсоединение</button></li>)}</ul></details>:null}
 <label><input type="checkbox" checked={confirm} onChange={e=>setConfirm(e.target.checked)}/>Я проверил список и подтверждаю {plan.operation==='delete'?'удаление перечисленных ресурсов':plan.operation==='detach'?'отсоединение':'повторное подключение'}.</label>
 <button disabled={!disabled||!confirm||plan.blockers.length>0||waiting||busy} onClick={()=>void execute(plan)}>Применить проверенный план</button>
 </section>}
 </details>;
}
