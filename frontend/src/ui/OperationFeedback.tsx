import {useEffect,useState} from 'react';
import {useLanguage} from './language';
export function OperationFeedback({operation,phase,started}:{operation:string;phase:'sending'|'running'|'completed'|'uncertain';started?:number}){
 const [language]=useLanguage(),[now,setNow]=useState(Date.now());
 useEffect(()=>{if(phase!=='sending'&&phase!=='running')return;const timer=setInterval(()=>setNow(Date.now()),1000);return()=>clearInterval(timer);},[phase]);
 const status=language==='ru'?{sending:'Запрос отправлен. Ожидаем подтверждение сервера.',running:'Операция выполняется.',completed:'Операция завершена.',uncertain:'Результат неизвестен. Проверьте состояние перед повтором.'}:{sending:'Request sent. Waiting for server acknowledgement.',running:'Operation in progress.',completed:'Operation completed.',uncertain:'Outcome unknown. Check operation state before retrying.'};
 return <div className={'operation-feedback '+(phase==='uncertain'?'operation-uncertain':'')}>
  <p role={phase==='uncertain'?'alert':'status'}><span className={phase==='sending'||phase==='running'?'activity-indicator':''} aria-hidden="true">{phase==='uncertain'?'?':phase==='completed'?'✓':''}</span>{phase==='uncertain'||phase==='completed'?' ':null}<strong>{operation}</strong> — {status[phase]}</p>
  {started&&phase!=='completed'&&phase!=='uncertain'&&<small aria-live="off">{language==='ru'?'Прошло':'Elapsed'} {Math.max(0,Math.floor((now-started)/1000))} {language==='ru'?'с':'s'}</small>}
 </div>;
}
