import {useState} from 'react';
import {useLanguage} from './language';
import {exactTime} from './format';
export function RefreshControl({loading,error,received,refresh}:{loading:boolean;error:boolean;received:string|null;refresh:()=>void}){
 const [requested,setRequested]=useState(false),[language]=useLanguage();
 const t=(en:string,ru:string)=>language==='ru'?ru:en;
 return <div className="refresh-control"><button disabled={loading} aria-busy={loading} onClick={()=>{setRequested(true);refresh();}}>{loading?t('Refreshing…','Обновляем…'):t('Refresh','Обновить')}</button><span role="status" aria-live="polite">{loading?t('Loading fresh data…','Загружаем свежие данные…'):error?t('Refresh failed. Retry.','Не удалось обновить. Повторите.'):requested&&received?t('Updated: ','Обновлено: ')+exactTime(received):''}</span></div>;
}
