import {useEffect,useState,type Dispatch,type SetStateAction} from 'react';
import {usePermission} from '../AuthGate';
import {authRequest} from '../AuthGate';
import {Lookup} from './CatalogLookup';
import {CatalogCreate} from './CatalogCreate';
import type {Placement} from './SourcePlacement';
import type {CatalogItem,SourcePreview} from '../api/onboarding';
type Resolution={references:Record<string,CatalogItem>;host_types:Record<string,CatalogItem>;sites:CatalogItem[];create_cluster:boolean;issues:{kind:string;code:string;host_id?:string}[]};
export function AutomaticPlacement({preview,draft,setDraft,language,receipt}:{preview:SourcePreview;draft:Placement;setDraft:Dispatch<SetStateAction<Placement>>;language:string;receipt:string}){
 const t=(en:string,ru:string)=>language==='ru'?ru:en,admin=usePermission('catalog.create');
 const [result,setResult]=useState<Resolution|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(true),[revision,setRevision]=useState(0),[creating,setCreating]=useState<{kind:string;host_id?:string}|null>(null);
 const [site,setSite]=useState(draft.references.site?.id);
 useEffect(()=>{let current=true;setBusy(true);setError('');setDraft(d=>({...d,resolution_ready:false}));
 const timer=setTimeout(()=>authRequest('sources/resolve-placement',{onboarding_token:receipt,name:draft.name,site_id:site}).then(value=>{
  if(!current)return;
  if(!value||!Array.isArray(value.issues)||!Array.isArray(value.sites)||!value.references||!value.host_types||typeof value.create_cluster!=='boolean')throw new Error();
  setResult(value);setDraft(d=>({...d,resolution_name:draft.name,resolution_site:value.references.site?.id,resolution_ready:value.issues.length===0,references:value.references,host_types:value.host_types,create_cluster:value.create_cluster,registration_id:d.registration_id||crypto.randomUUID()}));setBusy(false);
 }).catch(()=>{if(current){setError(t('NetBox parameters could not be checked. Retry.','Не удалось проверить параметры NetBox. Повторите проверку.'));setBusy(false);}}),300);
 return()=>{current=false;clearTimeout(timer);};},[receipt,draft.name,site,revision]);
 const labels:Record<string,string>={site:t('Site','Площадка'),platform:t('Platform','Платформа'),device_role:t('Device role','Роль устройства'),cluster_type:t('Cluster type','Тип кластера'),device_type:t('Device type','Тип устройства'),cluster:t('Cluster','Кластер')};
 return <section className="wizard-section" aria-busy={busy}>
 <h2>{t('Source settings','Настройки источника')}</h2>
 <label>{t('Display name','Название источника')}<input id="source-name" required maxLength={100} value={draft.name} onChange={e=>setDraft(d=>({...d,name:e.target.value}))}/></label>
 {!busy&&result?.issues.filter(issue=>issue.kind==='cluster').map((issue,index)=><p key={index} className="field-error" role="alert">{issue.code==='OWNERSHIP_REVIEW_REQUIRED'?t('This cluster contains existing objects. An administrator must verify their ownership; source recovery is not available yet.','В кластере уже есть объекты. Администратор должен проверить их принадлежность; восстановление источника пока недоступно.'):t('This source name cannot be used for the selected placement. Change it or ask an administrator to resolve the conflict.','Это название источника нельзя использовать в выбранном размещении. Измените его или попросите администратора разрешить конфликт.')}</p>)}
 {busy&&<p role="status">{t('Checking NetBox parameters…','Проверяем параметры NetBox…')}</p>}
 {error&&<p role="alert">{error}</p>}
 {preview.hosts.map(host=><article className="host-preview" key={host.id}><h3>{host.name||preview.name}</h3><dl className="source-facts">{[[t('Manufacturer','Производитель'),host.manufacturer],[t('Model','Модель'),host.model],['CPU',host.cpu],[t('Memory','Память'),host.memory_bytes?`${(host.memory_bytes/1024**3).toFixed(1)} GiB`:null],[t('Hypervisor version','Версия гипервизора'),host.version],[t('Site','Площадка'),draft.references.site?.name]].filter(([,value])=>!!value).map(([label,value])=><div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl></article>)}
 {result&&result.sites.length>1&&<Lookup kind="site" label={t('Site','Площадка')} language={language} value={draft.references.site} change={row=>{setSite(row.id);setDraft(d=>({...d,resolution_ready:false,references:{...d.references,site:row}}));}}/>}
 {!busy&&result?.issues.filter(issue=>issue.kind!=='cluster').map((issue,index)=>{const host=preview.hosts.find(h=>h.id===issue.host_id);return <div className="source-error" key={index} role="alert">
  <p>{issue.code==='OWNERSHIP_REVIEW_REQUIRED'?t('This cluster contains existing objects. An administrator must verify their ownership; source recovery is not available yet.','В кластере уже есть объекты. Администратор должен проверить их принадлежность; восстановление источника пока недоступно.'):issue.kind==='cluster'?t('This source name cannot be used for the selected placement. Change it or ask an administrator to resolve the conflict.','Это название источника нельзя использовать в выбранном размещении. Измените его или попросите администратора разрешить конфликт.'):issue.kind==='device_type'?`${issue.code==='MISSING'?t('No NetBox device type: ','В NetBox нет типа устройства '):t('Several matching device types: ','Найдено несколько подходящих типов устройства: ')}${[host?.manufacturer,host?.model].filter(Boolean).join(' / ')}`:`${labels[issue.kind]}: ${issue.code==='AMBIGUOUS'?t('several matching entries','найдено несколько совпадений'):t('a matching entry is required','нужна подходящая запись')}`}</p>
  {!admin&&<p>{t('Ask an administrator to complete the mapping.','Попросите администратора завершить сопоставление.')}</p>}
  {admin&&issue.code==='MISSING'&&issue.kind!=='cluster'&&issue.kind!=='site'&&(issue.kind!=='device_type'||(host?.model&&host?.manufacturer))&&<button type="button" onClick={()=>setCreating(issue)}>{t('Create missing entry','Создать недостающую запись')}</button>}
 </div>;})}
 <details><summary>{t('View NetBox parameters','Посмотреть параметры NetBox')}</summary><dl className="source-facts">{Object.entries(draft.references).map(([kind,row])=><div key={kind}><dt>{labels[kind]}</dt><dd>{row.name}</dd></div>)}{Object.entries(draft.host_types).map(([id,row])=><div key={id}><dt>{t('Device type','Тип устройства')}</dt><dd>{row.manufacturer?.name} / {row.name}</dd></div>)}</dl><p>{draft.create_cluster?t('Cluster will be created: ','Будет создан кластер: ')+draft.name:t('Existing cluster','Существующий кластер')}</p></details>
 <button type="button" disabled={busy} onClick={()=>setRevision(r=>r+1)}>{t('Check parameters again','Перепроверить параметры')}</button>
 {creating&&<CatalogCreate kind={creating.kind} initial={creating.kind==='device_role'?'Hypervisor':creating.kind==='device_type'?preview.hosts.find(h=>h.id===creating.host_id)?.model||'':preview.provider==='esxi'?'VMware ESXi':'Proxmox VE'} manufacturer={preview.hosts.find(h=>h.id===creating.host_id)?.manufacturer||''} references={draft.references} language={language} onClose={()=>setCreating(null)} onCreated={()=>{setCreating(null);setRevision(r=>r+1);}}/>}
 </section>;
}
