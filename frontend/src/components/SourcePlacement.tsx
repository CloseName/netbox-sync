import type {Dispatch,SetStateAction} from 'react';
import {useEffect,useId,useState} from 'react';
import {catalog,CatalogFailure} from '../api/onboarding';
import type {CatalogItem,CatalogPage,HostPreview,SourcePreview} from '../api/onboarding';
export interface Placement {source_instance:string;name:string;interval:number;references:Record<string,CatalogItem>;host_types:Record<string,CatalogItem>;}
export const genericModel=(value:string|null)=>!value||['super server','system product name','to be filled by o.e.m.','default string','unknown'].includes(value.trim().toLowerCase());
const equal=(a:string|null|undefined,b:string|null|undefined)=>!!a&&!!b&&a.trim().toLowerCase()===b.trim().toLowerCase();
export function suggestion(kind:string,rows:CatalogItem[],name:string,host?:HostPreview){
 const candidates=rows.filter(row=>kind==='device_type'? !genericModel(host?.model??null)&&equal(row.name,host?.model)&&equal(row.manufacturer?.name,host?.manufacturer):equal(row.name,name)||equal(row.slug,name));
 return candidates.length===1?candidates[0]:null;
}
function Lookup({kind,label,value,change,language,hint='',host}:{kind:string;label:string;value?:CatalogItem;change:(r:CatalogItem)=>void;language:string;hint?:string;host?:HostPreview}){
 const t=(en:string,ru:string)=>language==='ru'?ru:en;
 const id=useId();const [search,setSearch]=useState(hint);const [offset,setOffset]=useState(0);const [refresh,setRefresh]=useState(0);
 const [page,setPage]=useState<CatalogPage|null>(null);const [error,setError]=useState('');const [loading,setLoading]=useState(true);
 useEffect(()=>{const controller=new AbortController();setLoading(true);setError('');
 const timer=setTimeout(()=>catalog(kind,search,offset,controller.signal).then(result=>{setPage(result);setLoading(false);
 if(!value&&!result.more&&offset===0&&hint&&search===hint){const proposed=suggestion(kind,result.items,hint,host);if(proposed)change(proposed);}
 }).catch(failure=>{if(!controller.signal.aborted){setLoading(false);setError(failure instanceof CatalogFailure?failure.code:'CATALOG_UNAVAILABLE');}}),200);
 return()=>{clearTimeout(timer);controller.abort();};},[kind,search,offset,refresh]);
 const context=(row:CatalogItem)=>[row.manufacturer?.name,row.type?.name,row.scope?.name||row.site?.name,`#${row.id}`].filter(Boolean).join(' · ');
 return <section className="catalog-lookup" aria-busy={loading}>
 <label htmlFor={id}>{label}</label>
 <input id={id} type="search" aria-label={t('Search: ','Поиск: ')+label} value={search} maxLength={100} onChange={e=>{setSearch(e.target.value);setOffset(0);}}/>
 {loading?<p role="status">{t('Loading from NetBox: ','Загружаем из NetBox: ')}{label}…</p>:error?<p role="alert">{error.includes('PERMISSION')||error.includes('AUTH')?t('NetBox read access was denied.','NetBox отклонил доступ на чтение.'):t('Could not load this list. Your choices are retained.','Не удалось загрузить список. Ваш выбор сохранён.')}</p>:<>
 {!value&&(page?.count??0)>1&&<p>{t('Several results: choose the intended object explicitly.','Найдено несколько вариантов: выберите нужный объект.')}</p>}
 <select aria-label={label} value={value?.id??''} onChange={e=>{const row=page?.items.find(r=>r.id===Number(e.target.value));if(row)change(row);}}>
 <option value="">{t('Choose an existing object','Выберите существующий объект')}</option>
 {value&&!page?.items.some(r=>r.id===value.id)&&<option value={value.id}>{value.name} · {context(value)}</option>}
 {page?.items.map(row=><option key={row.id} value={row.id}>{row.name} · {context(row)}</option>)}
 </select>
 {page?.count===0&&<p>{search?t('No matches. Try another search.','Совпадений нет. Измените поиск.'):t('This NetBox list is empty.','Этот справочник NetBox пуст.')}</p>}
 {(!!page?.more||offset>0)&&<div className="catalog-pagination"><button type="button" disabled={offset===0} onClick={()=>setOffset(Math.max(0,offset-20))}>{t('Previous','Назад')}</button><span>{offset+1}–{offset+(page?.items.length??0)} / {page?.count??0}</span><button type="button" disabled={!page?.more||offset>=10000} onClick={()=>setOffset(offset+20)}>{t('Next','Далее')}</button></div>}
 </>}
 <details open={!!error||page?.count===0}><summary>{t('Missing an object?','Нет нужного объекта?')}</summary><div className="catalog-actions"><button type="button" onClick={()=>setRefresh(r=>r+1)} disabled={loading}>{t('Refresh list','Обновить список')}</button>{page?.url.startsWith('https://')&&<a href={page.url} target="_blank" rel="noreferrer">{t('Open NetBox list','Открыть справочник NetBox')}</a>}</div></details>
 {value&&<small>{t('Selected: ','Выбрано: ')}{value.name} · {context(value)}</small>}
 </section>;
}
export function SourcePlacement({preview,draft,setDraft,language}:{preview:SourcePreview;draft:Placement;setDraft:Dispatch<SetStateAction<Placement>>;language:string}){
 const t=(en:string,ru:string)=>language==='ru'?ru:en;
 const update=(kind:string,row:CatalogItem)=>setDraft(d=>({...d,references:{...d.references,[kind]:row}}));
 const definitions=[['site',t('Site','Площадка (Site)'), ''],['cluster',t('Cluster','Кластер (Cluster)'),preview.cluster||''],['platform',t('Platform','Платформа (Platform)'),preview.provider==='esxi'?'VMware ESXi':'Proxmox VE'],['device_role',t('Device role','Роль устройства (Device role)'),'hypervisor'],['cluster_type',t('Cluster type','Тип кластера (Cluster type)'),preview.provider==='esxi'?'VMware ESXi':'Proxmox VE']];
 return <>
 <section className="source-panel"><h2>{t('Detected hosts','Обнаруженные хосты')}</h2><p>{preview.cluster?t('Detected cluster: ','Обнаруженный кластер: ')+preview.cluster:t('No provider cluster name was reported. Select the intended existing NetBox cluster below.','Источник не сообщил имя кластера. Ниже выберите существующий целевой кластер NetBox.')}</p>
 {preview.hosts.map(host=><article className="host-preview" key={host.id}><h3>{host.name||host.id}</h3><dl className="source-facts"><div><dt>{t('Manufacturer / model','Производитель / модель')}</dt><dd>{host.manufacturer||t('Not reported','Нет данных')} / {host.model||t('Not reported','Нет данных')}</dd></div><div><dt>{t('Hypervisor version','Версия гипервизора')}</dt><dd>{host.version||t('Not reported','Нет данных')}</dd></div><div><dt>CPU</dt><dd>{host.cpu||t('Not reported','Нет данных')}</dd></div><div><dt>{t('Memory','Память')}</dt><dd>{host.memory_bytes?`${(host.memory_bytes/1024**3).toFixed(1)} GiB`:t('Not reported','Нет данных')}</dd></div></dl>
 <Lookup kind="device_type" label={t('Device type for ','Тип устройства (Device type) для ')+(host.name||host.id)} language={language} value={draft.host_types[host.id]} hint={genericModel(host.model)?'':host.model!} host={host} change={row=>setDraft(d=>({...d,host_types:{...d.host_types,[host.id]:row}}))}/>
 {genericModel(host.model)&&<p className="muted">{t('The reported model is absent or generic. Choose the exact device type explicitly; no hardware model is inferred.','Модель не указана или слишком общая. Выберите точный тип устройства самостоятельно; модель оборудования не определяется предположением.')}</p>}</article>)}
 </section>
 <section className="source-panel"><h2>{t('Placement in NetBox','Размещение в NetBox')}</h2><label>{t('Display name','Название источника')}<input required maxLength={200} value={draft.name} onChange={e=>setDraft({...draft,name:e.target.value})}/></label><div className="form-grid">{definitions.map(([kind,label,hint])=><Lookup key={kind} kind={kind} label={label} hint={hint} language={language} value={draft.references[kind]} change={row=>update(kind,row)}/>)}</div><p className="muted">{t('Choose a cluster scoped to the selected site and its existing cluster type. Missing objects must be prepared separately in NetBox; refreshing keeps this form.','Выберите кластер выбранной площадки и его существующий тип. Недостающие объекты подготовьте отдельно в NetBox; обновление списка сохраняет форму.')}</p></section>
 <details className="source-panel"><summary>{t('Advanced settings','Дополнительные настройки')}</summary><label>Source ID<input required pattern="[a-z0-9][a-z0-9._-]{1,62}" value={draft.source_instance} onChange={e=>setDraft({...draft,source_instance:e.target.value})}/></label><p>{t('Generated once before registration. This stable identity is independent of display name and address.','Создаётся автоматически до регистрации. Постоянная идентичность не зависит от названия и адреса.')}</p><label>{t('Schedule interval, seconds (sync remains off)','Интервал расписания, секунд (синхронизация выключена)')}<input name="interval" type="number" min={1} max={2147483647} value={draft.interval} onChange={e=>setDraft({...draft,interval:Number(e.target.value)})} required/></label></details>
 </>;
}
