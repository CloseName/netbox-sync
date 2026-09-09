import {useEffect,useState} from 'react';
import {useLanguage} from './language';
export function OperationFeedback({operation,phase,started}:{operation:string;phase:'sending'|'running'|'uncertain';started?:number}){
 const [language]=useLanguage(),[now,setNow]=useState(Date.now());
 useEffect(()=>{const timer=setInterval(()=>setNow(Date.now()),1000);return()=>clearInterval(timer);},[]);
 const status=language==='ru'?{sending:'Запрос отправлен. Ожидаем подтверждение сервера.',running:'Сервер подтвердил выполнение.',uncertain:'Связь потеряна: результат не подтверждён. Проверьте состояние перед повтором.'}:{sending:'Request sent. Waiting for server acknowledgement.',running:'Execution confirmed by the server.',uncertain:'Connection lost: outcome unconfirmed. Check server state before retrying.'};
 return <div className={'operation-feedback '+(phase==='uncertain'?'operation-uncertain':'')}>
  <p role={phase==='uncertain'?'alert':'status'}><span className={phase==='uncertain'?'':'activity-indicator'} aria-hidden="true">{phase==='uncertain'?'?':''}</span><strong>{operation}</strong> — {status[phase]}</p>
  {started&&<small aria-live="off">{language==='ru'?'Прошло':'Elapsed'} {Math.max(0,Math.floor((now-started)/1000))} {language==='ru'?'с':'s'}</small>}
 </div>;
}
