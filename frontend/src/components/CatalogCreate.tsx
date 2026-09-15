import {useEffect,useRef,useState} from 'react';
import {Lookup} from './CatalogLookup';
import type {CatalogItem} from '../api/onboarding';
interface Result {operation_id:string;status:'CREATED'|'REFUSED'|'UNCERTAIN'|'EXISTS_REVIEW_REQUIRED';item:CatalogItem|null;error?:string;}
export function CatalogCreate({kind,initial,manufacturer='',references,language,onClose,onCreated}:{kind:string;initial:string;manufacturer?:string;references:Record<string,CatalogItem>;language:string;onClose:()=>void;onCreated:(row:CatalogItem)=>void}){
 const t=(en:string,ru:string)=>language==='ru'?ru:en;
 const dialog=useRef<HTMLDialogElement>(null),fields=useRef<HTMLFieldSetElement>(null),inFlight=useRef(false);
 const [name,setName]=useState(initial),[slug,setSlug]=useState(''),[height,setHeight]=useState(''),[token,setToken]=useState('');
 const [selected,setSelected]=useState<Record<string,CatalogItem>>({...references});
 const [nested,setNested]=useState<string|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const [operation,setOperation]=useState<string>(()=>crypto.randomUUID()),[result,setResult]=useState<Result|null>(null);
 useEffect(()=>{dialog.current?.showModal();return()=>dialog.current?.close();},[]);
 const titles:Record<string,string>={manufacturer:t('Manufacturer','Производитель (Manufacturer)'),device_type:t('Device type','Тип устройства (Device type)'),platform:t('Platform','Платформа (Platform)'),device_role:t('Device role','Роль устройства (Device role)'),cluster_type:t('Cluster type','Тип кластера (Cluster type)'),cluster:t('Cluster','Кластер (Cluster)')};
 const locked=busy||!!result&&result.status!=='REFUSED';
 function definition(){return {...(kind==='device_type'?{model:name,manufacturer:selected.manufacturer?.id,u_height:Number(height)}:{name}),...(kind==='cluster'?{type:selected.cluster_type?.id,scope_type:'dcim.site',scope_id:selected.site?.id}:{slug})};}
 async function request(reconcile=false){
  if(inFlight.current)return;
  if(!reconcile){
   for(const control of Array.from(fields.current?.querySelectorAll<HTMLInputElement>('input')??[]))if(!control.reportValidity())return;
   if(kind==='device_type'&&!selected.manufacturer||kind==='cluster'&&(!selected.cluster_type||!selected.site)){setError(t('Choose the required dependencies first.','Сначала выберите обязательные связанные объекты.'));return;}
  }
  inFlight.current=true;setBusy(true);setError('');
  try{
   const response=await fetch(reconcile?'/api/v1/catalog-operations/'+operation:'/api/v1/catalog/'+kind,{method:reconcile?'GET':'POST',credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(35000),...(!reconcile?{headers:{'Content-Type':'application/json','X-NetBox-Sync-CSRF':'same-origin'},body:JSON.stringify({operation_id:operation,object:definition(),write_token:token,confirm:true})}:{})});
   if(!response.ok){if([401,403,409,422].includes(response.status)){setError(t('The server refused this action. Check permissions and the selected definition.','Сервер отклонил действие. Проверьте права и выбранное определение.'));setResult({operation_id:operation,status:'REFUSED',item:null});return;}throw new Error();}
   const value=await response.json() as Result;
   if(!value||!['CREATED','REFUSED','UNCERTAIN','EXISTS_REVIEW_REQUIRED'].includes(value.status)||typeof value.operation_id!=='string'||!/^[a-f0-9-]{36}$/.test(value.operation_id))throw new Error();
   setOperation(value.operation_id);setResult(value);
   if(value.status==='CREATED'){
    if(!value.item||!Number.isSafeInteger(value.item.id)||typeof value.item.fingerprint!=='string')throw new Error();
    onCreated({...value.item,suggested:false});
   }
   if(value.status==='REFUSED')setError(['PERMISSION_DENIED','AUTH_FAILED'].includes(value.error??'')?t('NetBox refused access. Use a separate token with the required catalog add/view permissions. The existing read token was not changed.','NetBox отклонил доступ. Нужен отдельный токен с правами add/view для справочника. Существующий токен чтения не изменён.'):t('NetBox refused this definition. Review its fields and dependencies.','NetBox отклонил определение. Проверьте поля и связанные объекты.'));
  }catch{setResult({operation_id:operation,status:'UNCERTAIN',item:null});setError(t('The write outcome is unknown. Check the operation; do not repeat creation.','Результат записи неизвестен. Сверьте операцию; не повторяйте создание.'));}
  finally{setToken('');inFlight.current=false;setBusy(false);}
 }
 return <dialog ref={dialog} className="sync-dialog" aria-label={t('Create in NetBox','Создать в NetBox')} onCancel={e=>{e.preventDefault();if(!busy)onClose();}}>
 <h2>{t('Create in NetBox: ','Создать в NetBox: ')}{titles[kind]}</h2>
 <p>{t('This explicitly creates a catalog object in NetBox. Source registration and infrastructure sync are separate actions.','Это действие создаст справочный объект в NetBox. Регистрация источника и синхронизация инфраструктуры выполняются отдельно.')}</p>
 {initial&&<p className="muted">{t('Suggested name — review it. Hardware descriptions may be generic; no height or SKU is inferred.','Предложенное имя — проверьте его. Описание оборудования может быть общим; высота и SKU не определяются предположением.')}</p>}
 <fieldset ref={fields} disabled={locked}><label>{kind==='device_type'?t('Model','Модель'):t('Name','Название')} *<input required maxLength={100} value={name} onChange={e=>setName(e.target.value)}/></label>
 {kind!=='cluster'&&<label>Slug *<input aria-label="Slug *" required maxLength={100} pattern="[a-zA-Z0-9_-]+" value={slug} onChange={e=>setSlug(e.target.value)}/><small>{t('Explicit unique identifier in NetBox.','Явный уникальный идентификатор в NetBox.')}</small></label>}
 {kind==='device_type'&&<><Lookup kind="manufacturer" label={titles.manufacturer} language={language} hint={manufacturer} value={selected.manufacturer} change={row=>setSelected(s=>({...s,manufacturer:row}))} onCreate={()=>setNested('manufacturer')}/><label>{t('Height (U), as confirmed by the operator','Высота (U), подтверждённая оператором')} *<input type="number" min={0} max={100} step="0.5" required value={height} onChange={e=>setHeight(e.target.value)}/></label></>}
 {kind==='cluster'&&<><Lookup kind="site" label={t('Site','Площадка (Site)')} language={language} value={selected.site} change={row=>setSelected(s=>({...s,site:row}))}/><Lookup kind="cluster_type" label={titles.cluster_type} language={language} value={selected.cluster_type} change={row=>setSelected(s=>({...s,cluster_type:row}))} onCreate={()=>setNested('cluster_type')}/></>}
 <details><summary>{t('Review exact definition','Проверить точное определение')}</summary><pre>{JSON.stringify(definition(),null,2)}</pre></details>
 <label>{t('Separate temporary catalog write token','Отдельный временный токен записи справочников')} *<input type="password" required minLength={8} maxLength={4096} autoComplete="new-password" value={token} onChange={e=>setToken(e.target.value)}/></label>
 <p className="muted">{t('Use an operator-issued NetBox token with add/view rights only for the required catalog models. It is sent for this action, never saved. Provider credentials and the configured read token are not used to authorize creation.','Используйте выданный оператором токен NetBox с правами add/view только для нужных справочных моделей. Он передаётся для этого действия и не сохраняется. Данные провайдера и настроенный токен чтения не разрешают создание.')}</p></fieldset>
 {error&&<p role="alert">{error}</p>}
 {result?.status==='EXISTS_REVIEW_REQUIRED'&&<div><p>{t('An object already exists. Review it before choosing; it was not silently adopted.','Объект уже существует. Проверьте его перед выбором; автоматическое принятие не выполнялось.')}</p>{result.item&&<><p>{result.item.name} · #{result.item.id} · {result.item.scope?.name||result.item.manufacturer?.name}</p><button type="button" onClick={()=>onCreated({...result.item!,suggested:false})}>{t('Choose this existing object','Выбрать этот существующий объект')}</button></>}</div>}
 {result?.status==='UNCERTAIN'&&<><p>{t('Operation ID: ','Идентификатор операции: ')}<code>{operation}</code></p><button type="button" disabled={busy} onClick={()=>request(true)}>{t('Check operation','Сверить операцию')}</button></>}
 <div className="page-actions"><button type="button" disabled={busy} onClick={onClose}>{t('Close','Закрыть')}</button><button type="button" className="primary" disabled={locked} onClick={()=>{if(result?.status==='REFUSED'){setOperation(crypto.randomUUID());setResult(null);setError('');}else void request();}}>{result?.status==='REFUSED'?t('Review before another attempt','Проверить перед новой попыткой'):t('Confirm creation','Подтвердить создание')}</button></div>
 {nested&&<CatalogCreate kind={nested} initial={nested==='manufacturer'?manufacturer:''} references={{}} language={language} onClose={()=>setNested(null)} onCreated={row=>{setSelected(s=>({...s,[nested]:row}));setNested(null);}}/>}
 </dialog>;
}
