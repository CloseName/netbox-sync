import {useEffect,useId,useState,useRef} from 'react';
import {catalog,CatalogFailure} from '../api/onboarding';
import type {CatalogItem,CatalogPage,HostPreview} from '../api/onboarding';
export const genericModel=(value:string|null)=>!value||['super server','system product name','to be filled by o.e.m.','default string','unknown'].includes(value.trim().toLowerCase());
const equal=(a:string|null|undefined,b:string|null|undefined)=>!!a&&!!b&&a.trim().toLowerCase()===b.trim().toLowerCase();
export function suggestion(kind:string,rows:CatalogItem[],name:string,host?:HostPreview){
 const candidates=rows.filter(row=>kind==='device_type'? !genericModel(host?.model??null)&&equal(row.name,host?.model)&&equal(row.manufacturer?.name,host?.manufacturer):equal(row.name,name)||equal(row.slug,name));
 return candidates.length===1?candidates[0]:null;
}
export function Lookup({kind,label,value,change,language,hint='',host,onCreate}:{kind:string;label:string;value?:CatalogItem;change:(r:CatalogItem)=>void;language:string;hint?:string;host?:HostPreview;onCreate?:()=>void}){
 const t=(en:string,ru:string)=>language==='ru'?ru:en;
 const currentValue=useRef(value);currentValue.current=value;
 const id=useId();const root=useRef<HTMLElement>(null);const control=useRef<HTMLButtonElement>(null);const searchInput=useRef<HTMLInputElement>(null);
 const [search,setSearch]=useState(hint),[offset,setOffset]=useState(0),[refresh,setRefresh]=useState(0),[open,setOpen]=useState(false),[active,setActive]=useState(0);
 const [page,setPage]=useState<CatalogPage|null>(null),[error,setError]=useState(''),[loading,setLoading]=useState(true);
 useEffect(()=>{const controller=new AbortController();setLoading(true);setError('');
 const timer=setTimeout(()=>catalog(kind,search,offset,controller.signal).then(result=>{setPage(result);setLoading(false);setActive(0);
 if(!currentValue.current&&!result.more&&offset===0&&hint&&search===hint){const proposed=suggestion(kind,result.items,hint,host);if(proposed)change({...proposed,suggested:true});}
 }).catch(failure=>{if(!controller.signal.aborted){setLoading(false);setError(failure instanceof CatalogFailure?failure.code:'CATALOG_UNAVAILABLE');}}),200);
 return()=>{clearTimeout(timer);controller.abort();};},[kind,search,offset,refresh]);
 useEffect(()=>{if(open)searchInput.current?.focus();},[open]);
 useEffect(()=>{if(open)document.getElementById(id+'-option-'+active)?.scrollIntoView({block:'nearest'});},[open,active,id]);
 const context=(row:CatalogItem)=>[row.manufacturer?.name,row.type?.name,row.scope?.name||row.site?.name,`#${row.id}`].filter(Boolean).join(' · ');
 const close=()=>{setOpen(false);control.current?.focus();};
 const choose=(row:CatalogItem)=>{change({...row,suggested:false});close();};
 return <section className="catalog-lookup" ref={root} onBlur={e=>{if(!e.currentTarget.contains(e.relatedTarget as Node))setOpen(false);}}>
 <label id={id+'-label'} htmlFor={id}>{label} <span aria-hidden="true">*</span></label>
 <button ref={control} id={id} type="button" role="combobox" aria-label={label} aria-required="true" aria-expanded={open} aria-controls={id+'-list'} aria-haspopup="listbox"
 className={'catalog-control '+(value&&!value.suggested?'is-selected':'')} onClick={()=>setOpen(v=>!v)} onKeyDown={e=>{if(['ArrowDown','ArrowUp'].includes(e.key)){e.preventDefault();setOpen(true);}}}>
 <span>{value?value.name:t('Choose an existing object','Выберите существующий объект')}{value&&<small>{context(value)}</small>}</span><span aria-hidden="true">{value&&!value.suggested?'✓':'⌄'}</span>
 </button>
 {value?.suggested&&<small>{t('Suggested — review before confirming.','Предложено — проверьте перед подтверждением.')}</small>}
 {value&&!value.suggested&&<small>{t('Selected from NetBox. Rechecked when saving.','Выбрано из NetBox. При сохранении проверим повторно.')}</small>}
 {loading&&<p role="status">{t('Loading from NetBox: ','Загружаем из NetBox: ')}{label}…</p>}
 {error&&<p role="alert">{error.includes('PERMISSION')||error.includes('AUTH')?t('NetBox read access was denied.','NetBox отклонил доступ на чтение.'):t('Could not load this list. Your choices are retained.','Не удалось загрузить список. Ваш выбор сохранён.')}</p>}
 {open&&<div className="catalog-popup">
 <input ref={searchInput} type="search" aria-label={t('Search: ','Поиск: ')+label} aria-controls={id+'-list'} aria-activedescendant={page?.items[active]?id+'-option-'+active:undefined} placeholder={t('Search by name','Поиск по названию')} value={search} maxLength={100}
 onChange={e=>{setSearch(e.target.value);setOffset(0);}} onKeyDown={e=>{if(e.key==='Escape'){e.preventDefault();close();}else if(['ArrowDown','ArrowUp'].includes(e.key)){e.preventDefault();setActive(i=>Math.max(0,Math.min((page?.items.length??1)-1,i+(e.key==='ArrowDown'?1:-1))));}else if(e.key==='Enter'){e.preventDefault();if(!loading&&!error&&page?.items[active])choose(page.items[active]);}}}/>
 {!loading&&!error&&<>
 {!value&&(page?.count??0)>1&&<p>{t('Several results: choose the intended object explicitly.','Найдено несколько вариантов: выберите нужный объект.')}</p>}
 <ul id={id+'-list'} role="listbox" aria-label={label} className="catalog-options">{page?.items.map((row,index)=><li id={id+'-option-'+index} role="option" aria-selected={row.id===value?.id} key={row.id} data-catalog-id={row.id} className={active===index?'is-active':''} onMouseDown={e=>e.preventDefault()} onClick={()=>choose(row)}>{row.name}<small>{context(row)}</small></li>)}</ul>
 {page?.count===0&&<p>{search?t('No matches. Try another search.','Совпадений нет. Измените поиск.'):t('This NetBox list is empty.','Этот справочник NetBox пуст.')}</p>}
 {(!!page?.more||offset>0)&&<div className="catalog-pagination"><button type="button" disabled={offset===0} onClick={()=>setOffset(Math.max(0,offset-20))}>{t('Previous','Назад')}</button><span>{offset+1}–{offset+(page?.items.length??0)} / {page?.count??0}</span><button type="button" disabled={!page?.more||offset>=10000} onClick={()=>setOffset(offset+20)}>{t('Next','Далее')}</button></div>}
 </>}
 <div className="catalog-actions"><button type="button" onClick={()=>setRefresh(r=>r+1)} disabled={loading}>{t('Refresh list','Обновить список')}</button>{onCreate&&<button type="button" onClick={onCreate}>{t('Create…','Создать…')}</button>}{page?.url.startsWith('https://')&&<a href={page.url} target="_blank" rel="noreferrer">{t('Open NetBox list','Открыть справочник NetBox')}</a>}</div>
 <button type="button" onClick={close}>{t('Close list','Закрыть список')}</button>
 </div>}
 </section>;
}
