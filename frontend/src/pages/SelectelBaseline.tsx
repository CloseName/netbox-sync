import {useState} from 'react';

type Plan={operation:string;key:string;fingerprint:string;retain:{model:string;id:number;name:string;url:string}[];inventory_count:number;native_counts:Record<string,number>};
export function SelectelBaseline({account,runId,disabled,pending,busy,request,refresh}:{account:string;runId:string;disabled:boolean;pending:boolean;busy:boolean;request:(path:string,body:unknown)=>Promise<unknown>;refresh:()=>void}){
 const [plan,setPlan]=useState<Plan|null>(null),[waiting,setWaiting]=useState(false),[error,setError]=useState('');
 const [checks,setChecks]=useState([false,false,false]);
 async function review(){setWaiting(true);setError('');setPlan(null);setChecks([false,false,false]);try{
  const result=await request('/'+account+'/lifecycle-review',{operation:'baseline',key:runId}) as Plan;
  if(result.operation!=='baseline'||result.key!==runId||!Array.isArray(result.retain))throw new Error('Не удалось проверить текущее состояние.');
  setPlan(result);
 }catch(e){setError((e as Error).message);}finally{setWaiting(false);}}
 async function accept(){if(!plan)return;setWaiting(true);setError('');try{
  await request('/'+account+'/lifecycle-execute',{operation:'baseline',key:runId,fingerprint:plan.fingerprint,confirmed:true});
  setPlan(null);
 }catch(e){setError((e as Error).message);}finally{setWaiting(false);refresh();}}
 return <details><summary>Принять текущее состояние после сверки</summary>
 <p>Старый результат останется неизвестным. Карточки, IP и привязки не изменятся. Старый запуск будет закрыт для повторной записи; аккаунт и расписание останутся выключенными.</p>
 {!disabled&&<p>Сначала отключите аккаунт.</p>}
 {error&&<p role="alert">{error}</p>}
 <button disabled={!disabled||pending||waiting||busy} onClick={()=>void review()}>Проверить текущее состояние NetBox</button>
 {plan&&<section aria-label="Сверка исторического импорта">
 <p>Серверов в реестре аккаунта: {plan.inventory_count}. Подтверждённых привязок: {plan.retain.length}.</p>
 <p>Список ниже показывает привязанные карточки. Проверьте также ресурсы аккаунта в NetBox: отсутствие привязки не доказывает отсутствие прежних записей.</p>
 <ul>{plan.retain.map(row=><li key={row.model+row.id}>{row.name} — {row.model} #{row.id}</li>)}</ul>
 {['Я проверил текущие ресурсы аккаунта в NetBox.','Я подтвердил, что старые процессы записи остановлены и не будут запущены повторно.','Я принимаю текущее состояние; старый результат остаётся неизвестным. Следующий сбор запущу вручную после проверки.'].map((label,i)=><label key={label}><input type="checkbox" checked={checks[i]} onChange={e=>setChecks(checks.map((v,j)=>i===j?e.target.checked:v))}/>{label}</label>)}
 <button disabled={!disabled||pending||waiting||busy||checks.some(v=>!v)} onClick={()=>void accept()}>Принять состояние и разрешить новый ручной сбор</button>
 </section>}
 </details>;
}
