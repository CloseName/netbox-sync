import {useState,useRef} from 'react';
import {sourceLifecycle} from '../api/lifecycle';
import {useLanguage} from '../ui/language';
export function SourceNameEditor({source,name,onSaved}:{source:string;name:string;onSaved:()=>void}){
 const [lang]=useLanguage(),t=(en:string,ru:string)=>lang==='ru'?ru:en;
 const dialog=useRef<HTMLDialogElement>(null),trigger=useRef<HTMLButtonElement>(null);
 const [value,setValue]=useState(name),[revision,setRevision]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const close=()=>{dialog.current?.close();trigger.current?.focus();};
 async function open(){setBusy(true);setError('');setRevision('');setValue(name);dialog.current?.showModal();
  try{const state=await sourceLifecycle(source,AbortSignal.timeout(10000));if(!state.revision)throw new Error();setValue(state.display_name);setRevision(state.revision);}
  catch{setError(t('Could not read the current source. Close and retry.','Не удалось прочитать текущее состояние. Закройте окно и повторите.'));}finally{setBusy(false);}}
 async function save(){if(busy||!revision||!value.trim())return;setBusy(true);setError('');
  try{const response=await fetch('/api/v1/sources/'+encodeURIComponent(source)+'/name',{method:'PATCH',credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(10000),headers:{'Content-Type':'application/json','X-NetBox-Sync-CSRF':'same-origin'},body:JSON.stringify({revision,name:value})});
   if(!response.ok){setRevision('');setError(t('Name could not be saved. Close and reopen to check current state before retrying.','Не удалось сохранить название. Закройте и откройте окно, чтобы проверить актуальное состояние перед повтором.'));return;}
   const result=await response.json();if(result.source_instance!==source||result.display_name!==value)throw new Error();onSaved();close();
  }catch{setRevision('');setError(t('The outcome is unconfirmed. Reopen to check the saved name; no automatic retry.','Результат не подтверждён. Откройте окно повторно и проверьте название; автоматического повтора нет.'));}finally{setBusy(false);}}
 return <><button ref={trigger} type="button" aria-label={t('Edit name','Изменить название')} onClick={open}>✎</button>
 <dialog ref={dialog} className="sync-dialog" onCancel={e=>{e.preventDefault();if(!busy)close();}} aria-label={t('Edit name','Изменить название')}>
 <h2>{t('Edit name','Изменить название')}</h2><p>{t('Only the source display name changes. NetBox objects keep their names.','Изменится только название источника. Имена объектов NetBox сохранятся.')}</p>
 <label>{t('Display name','Название источника')}<input value={value} onChange={e=>setValue(e.target.value)} maxLength={200} required disabled={busy}/></label>
 {error&&<p role="alert">{error}</p>}<div className="page-actions"><button type="button" disabled={busy} onClick={close}>{t('Cancel','Отмена')}</button><button type="button" className="primary" disabled={busy||!revision||!value.trim()} onClick={save}>{t('Save','Сохранить')}</button></div>
 </dialog></>;
}
