import {useState} from 'react';
import {NetworkScopeEditor} from './NetworkScopeEditor';
import type {NetworkScopeRule} from './NetworkScopeEditor';
import {SourcePlacement} from './SourcePlacement';
import type {Placement} from './SourcePlacement';
import type {SourcePreview} from '../api/onboarding';
import {useLanguage} from '../ui/language';
export function SourceMappingEditor({source,onSaved}:{source:string;onSaved:()=>void}) {
 const [language]=useLanguage(),t=(en:string,ru:string)=>language==='ru'?ru:en;
 const [state,setState]=useState<{revision:string;discovery_id:string;preview:SourcePreview}|null>(null);
 const [draft,setDraft]=useState<Placement>({source_instance:source,name:'',interval:600,references:{},host_types:{}});
 const [busy,setBusy]=useState(false),[message,setMessage]=useState(''),[review,setReview]=useState(false);
 const [ipPolicy,setIpPolicy]=useState<'strict'|'observe'>('strict');
 const [scopes,setScopes]=useState<NetworkScopeRule[]>([]);
 const path='/api/v1/sources/'+encodeURIComponent(source)+'/placement';
 async function open(){setBusy(true);setMessage('');setReview(false);try{
  const response=await fetch(path,{cache:'no-store',signal:AbortSignal.timeout(15000)});
  if(!response.ok)throw new Error();const value=await response.json();
  setScopes(value.network_scope_rules??[]);setIpPolicy(value.ip_conflict_policy==='observe'?'observe':'strict');setState(value);setDraft(d=>({...d,references:value.references,host_types:value.host_types}));
 }catch{setMessage(t('Run Discovery, then reopen placement. Your source has not been changed.','Выполните Discovery и откройте сопоставления снова. Источник не изменён.'));}finally{setBusy(false);}}
 async function save(){if(!state||busy)return;setBusy(true);setMessage('');try{
  const response=await fetch(path,{method:'PATCH',credentials:'same-origin',signal:AbortSignal.timeout(45000),headers:{'Content-Type':'application/json','X-NetBox-Sync-CSRF':'same-origin'},body:JSON.stringify({network_scope_rules:scopes,ip_conflict_policy:ipPolicy,revision:state.revision,discovery_id:state.discovery_id,references:draft.references,host_types:draft.host_types})});
  if(!response.ok)throw new Error();setState(null);onSaved();setMessage(t('Placement saved. Build and review a new plan before synchronization.','Сопоставления сохранены. Создайте и проверьте новый план перед синхронизацией.'));
 }catch{setState(null);setMessage(t('Result requires review. Reopen current placement before another save.','Проверьте результат: откройте текущие сопоставления перед повторным сохранением.'));}finally{setBusy(false);}}
 return <section className="source-panel"><h2>{t('Source placement','Сопоставления источника')}</h2>
 <p>{t('Use a successful Discovery from the last 24 hours. Saving invalidates old plans; synchronization does not start automatically.','Используется успешный Discovery за последние 24 часа. Сохранение отменяет старые планы; синхронизация автоматически не запускается.')}</p>
 {message&&<p role="status">{message}</p>}
 {!state?<button type="button" disabled={busy} onClick={open}>{t('Edit placement','Изменить сопоставления')}</button>:<fieldset disabled={busy}>
 <label><input type="checkbox" checked={ipPolicy==='observe'} disabled={review} onChange={event=>setIpPolicy(event.target.checked?'observe':'strict')}/>{t('Save ambiguous IPs as NetBox observations','Сохранять неоднозначные IP как наблюдения в NetBox')}</label>
 <p>{ipPolicy==='observe'?t('VMs and interfaces can sync; disputed IPAM assignments remain incomplete. Requires the network observations field in NetBox.','VM и интерфейсы могут синхронизироваться; спорные назначения IPAM останутся неполными. Требуется поле сетевых наблюдений в NetBox.'):t('Address ambiguity blocks the entire plan.','Неоднозначность адресов блокирует весь план.')}</p>
 <NetworkScopeEditor hosts={state.preview.hosts} rules={scopes} onChange={setScopes} readOnly={review} language={language}/>
 {!review?<><SourcePlacement preview={state.preview} draft={draft} setDraft={setDraft} language={language} editing/>
 <button type="button" disabled={Object.keys(draft.references).length!==5||state.preview.hosts.some(h=>!draft.host_types[h.id])} onClick={()=>setReview(true)}>{t('Review changes','Проверить изменения')}</button></>:<><dl>{Object.entries(draft.references).map(([key,value])=><div key={key}><dt>{key}</dt><dd>{value.name}</dd></div>)}{state.preview.hosts.map(h=><div key={h.id}><dt>{h.name||h.id}</dt><dd>{draft.host_types[h.id]?.name}</dd></div>)}</dl><button type="button" onClick={save}>{t('Confirm placement','Подтвердить сопоставления')}</button><button type="button" onClick={()=>setReview(false)}>{t('Back','Назад')}</button></>}
 <button type="button" onClick={()=>setState(null)}>{t('Cancel','Отмена')}</button></fieldset>}</section>;
}
