import {useEffect,useRef,useState} from 'react';
import {inspectConnection,cancelOnboarding} from '../api/onboarding';
import type {ConnectionInput} from '../api/onboarding';
import {fetchSource} from '../api/sources';
import type {Source} from '../api/sources';
import {useLanguage} from '../ui/language';

type Proof={digest:string;host_uuid:string;site_id:number;cluster_id:number;blockers:string[];
  owned:{kind:string;id:number}[];retained_manual:{kind:string;id:number}[]};
type Review={operation_id:string;name:string;proof:Proof};
const messages:Record<string,[string,string]>={
 SOURCE_RECOVERY_EVIDENCE_CHANGED:['The evidence changed. Check and review again.','Данные изменились. Повторите проверку и просмотр.'],
 SOURCE_RECOVERY_NOT_REMOVED:['The source is already active. Open its existing page.','Источник уже активен. Откройте существующий источник.'],
 SOURCE_RECOVERY_IDENTITY_REVIEW:['Hardware identity or original placement is not proved. Administrator review is required.','Аппаратная идентичность или прежнее размещение не подтверждены. Нужна проверка администратора.'],
 SOURCE_RECOVERY_IDENTITY_CONFLICT:['Another active source claims this host. Recovery is blocked.','На этот хост претендует другой активный источник. Восстановление заблокировано.'],
 SOURCE_APPLY_UNCONFIRMED:['Resolve the previous uncertain synchronization before recovery.','До восстановления нужно сверить предыдущую синхронизацию с неопределённым результатом.'],
 SOURCE_RECOVERY_ACTIVE:['Another recovery attempt is pending. Reconcile it first.','Другая попытка восстановления ещё не завершена. Сначала нужно сверить её результат.'],
 HOST_IDENTITY_UNAVAILABLE:['This host does not match the recorded hardware identity.','Хост не соответствует сохранённой аппаратной идентичности.'],
};
const blockers:Record<string,[string,string]>={
 OBJECT_IDENTITY_CONFLICT:['Object provenance does not identify exactly one compatible object','Принадлежность объекта не задаёт единственную совместимую идентичность'],
 DUPLICATE_OBJECT_IDENTITY:['Several objects claim the same provider identity','Несколько объектов имеют одну идентичность провайдера'],
 PLACEMENT_CHANGED:['NetBox placement changed','Изменилось размещение NetBox'],
 HOST_IDENTITY_MISMATCH:['Hardware identity does not match','Не совпадает аппаратная идентичность'],
 SHARED_OWNERSHIP:['Objects have shared ownership','Объекты имеют нескольких владельцев'],
 FOREIGN_SOURCE_IN_PLACEMENT:['The cluster contains objects owned by another source','В кластере есть объекты другого источника'],
 HOST_OWNED_BY_OTHER_SOURCE:['This host is owned by another source','Хост принадлежит другому источнику'],
 OWNED_OBJECT_OUTSIDE_PLACEMENT:['Owned objects exist outside the original placement','Есть собственные объекты вне прежнего размещения'],
 DUPLICATE_MANAGED_HOST:['Several managed host records match','Найдено несколько записей управляемого хоста'],
 LEGACY_OWNERSHIP_REVIEW_REQUIRED:['Legacy ownership requires review','Нужно проверить прежнюю схему принадлежности'],
};
class RecoveryFailure extends Error {readonly code:string;constructor(code:string){super(code);this.code=code;}}
async function post(source:string,action:string,payload:object){
 let response:Response;
 try{response=await fetch(`/api/v1/sources/${encodeURIComponent(source)}/${action}`,{method:'POST',
  headers:{'Content-Type':'application/json','X-NetBox-Sync-CSRF':'same-origin'},body:JSON.stringify(payload),signal:AbortSignal.timeout(90000)});}
 catch{throw new RecoveryFailure('OUTCOME_UNCERTAIN');}
 const value=await response.json().catch(()=>null);
 if(!response.ok)throw new RecoveryFailure(typeof value?.error?.code==='string'?value.error.code:'OUTCOME_UNCERTAIN');
 if(!value)throw new RecoveryFailure('OUTCOME_UNCERTAIN');return value;
}
export function SourceRecovery({source,readCredentials,clearSecret,busyChanged,done}:{source:string;
 readCredentials:()=>ConnectionInput|null;clearSecret:()=>void;busyChanged:(busy:boolean)=>void;done:(source:Source)=>void}){
 const [language]=useLanguage();const index=language==='ru'?1:0;const t=(en:string,ru:string)=>index?ru:en;
 const token=useRef('');const active=useRef(false);const mounted=useRef(true);
 const [review,setReview]=useState<Review|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[uncertain,setUncertain]=useState(false);
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;if(token.current)void cancelOnboarding(token.current).catch(()=>{});};},[]);
 const working=(value:boolean)=>{active.current=value;setBusy(value);busyChanged(value);};
 function failure(error:unknown){const code=error instanceof RecoveryFailure?error.code:(error as {code?:string})?.code;
  return code&&messages[code]?messages[code][index]:t('The operation could not be confirmed. Check server state before retrying.','Результат не подтверждён. Перед повтором сверьте состояние сервера.');}
 async function check(){
  if(active.current)return;const credentials=readCredentials();if(!credentials)return;
  working(true);setError('');setUncertain(false);
  try{
   if(token.current)await cancelOnboarding(token.current);token.current='';
   const checked=await inspectConnection({...credentials,recovery_source:source});
   if(!mounted.current){void cancelOnboarding(checked.onboarding_token);return;}
   token.current=checked.onboarding_token;clearSecret();
   const value=await post(source,'recovery-review',{onboarding_token:token.current});
   const p=value?.proof;
   if(value.source_instance!==source||typeof value.name!=='string'||typeof value.operation_id!=='string'||!p
      ||!/^[a-f0-9]{64}$/.test(p.digest)||typeof p.host_uuid!=='string'||!Array.isArray(p.blockers)
      ||!p.blockers.every((code:unknown)=>typeof code==='string')
      ||!Number.isInteger(p.site_id)||p.site_id<=0||!Number.isInteger(p.cluster_id)||p.cluster_id<=0
      ||!Array.isArray(p.owned)||!Array.isArray(p.retained_manual)||p.owned.length+p.retained_manual.length>10000
      ||![...p.owned,...p.retained_manual].every(r=>r&&['device','vm'].includes(r.kind)&&Number.isInteger(r.id)&&r.id>0))throw new RecoveryFailure('RESPONSE_INVALID');
   setReview(value);
  }catch(error){setReview(null);setError(failure(error));}finally{working(false);}
 }
 async function restore(){
  if(active.current||!review||review.proof.blockers.length)return;working(true);setError('');
  try{
   const result=await post(source,'recover',{onboarding_token:token.current,operation_id:review.operation_id,digest:review.proof.digest,confirmed:true});
   if(result.status!=='RESTORED'||result.source_instance!==source)throw new RecoveryFailure('OUTCOME_UNCERTAIN');
   token.current='';done(await fetchSource(source,AbortSignal.timeout(15000)));
  }catch(error){setUncertain(true);setError(failure(error));}finally{working(false);}
 }
 async function reconcile(){
  if(active.current||!review)return;working(true);
  try{const state=await post(source,'recovery-status',{operation_id:review.operation_id});
   if(state.state==='RESTORED'&&state.enabled===true)done(await fetchSource(source,AbortSignal.timeout(15000)));
   else setError(t('Recovery is not confirmed as active. Recheck the credentials and review the same attempt.','Активное восстановление не подтверждено. Повторно проверьте доступ и просмотрите ту же попытку.'));
  }catch(error){setError(failure(error));}finally{working(false);}
 }
 return <section className="card" aria-busy={busy}>
  <h2>{t('Restore removed source','Восстановить удалённый источник')}</h2>
  <p>{t('Verify this host with the credentials in the form. Recovery retains the original Source ID and history; scheduling stays off.','Проверьте хост с доступом, введённым в форме. Восстановление сохраняет прежний Source ID и историю; расписание останется выключенным.')}</p>
  <p>Source ID: <code>{source}</code></p>
  {error&&<p role="alert">{error}</p>}
  <button type="button" disabled={busy} onClick={()=>void check()}>{t('Check recovery','Проверить восстановление')}</button>
  {review&&<><h3>{review.name}</h3><p>UUID: <code>{review.proof.host_uuid}</code></p>
   <p>{t('NetBox site','Площадка NetBox')} #{review.proof.site_id}; {t('cluster','кластер')} #{review.proof.cluster_id}</p>
   <p>{t('Previously owned objects','Ранее управляемые объекты')}: {review.proof.owned.length}. {t('Manual objects retained','Ручные объекты сохраняются')}: {review.proof.retained_manual.length}.</p>
   {!!review.proof.blockers.length&&<div role="alert"><strong>{t('Recovery blocked','Восстановление заблокировано')}</strong><ul>{review.proof.blockers.map(code=><li key={code}>{blockers[code]?.[index]??t('Ownership requires review','Нужно проверить принадлежность')}</li>)}</ul></div>}
   <details><summary>{t('Review every object','Просмотреть все объекты')}</summary><ul>{review.proof.owned.map(row=><li key={row.kind+row.id}>{row.kind==='vm'?t('Virtual machine','Виртуальная машина'):t('Host','Хост')} #{row.id}</li>)}</ul>
    {!!review.proof.retained_manual.length&&<><h4>{t('Manual objects retained','Ручные объекты сохраняются')}</h4><ul>{review.proof.retained_manual.map(row=><li key={row.kind+row.id}>{row.kind==='vm'?t('Virtual machine','Виртуальная машина'):t('Host','Хост')} #{row.id}</li>)}</ul></>}
   </details>
   <button type="button" disabled={busy||uncertain||!!review.proof.blockers.length} onClick={()=>void restore()}>{t('Confirm recovery of this source','Подтвердить восстановление этого источника')}</button>
   {uncertain&&<button type="button" disabled={busy} onClick={()=>void reconcile()}>{t('Check recovery result','Сверить результат восстановления')}</button>}
  </>}
 </section>;
}
