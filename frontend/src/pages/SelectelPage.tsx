import {useEffect, useState, type FormEvent} from 'react';
import {useResource} from '../ui/useResource';
import {RefreshControl} from '../ui/RefreshControl';

type Product = {product:string;title:string;state_label:string;observations_by_collection:Record<string,number>};
type Account = {account:string;name:string;username:string;status:string;error?:string;
 url:string;finished_at?:number;summary?:{projects:number;servers:number;matched:number;unmatched:number;products:Product[]}};
type Accounts = {items:Account[];import_ready:boolean};
const messages:Record<string,string> = {
 RUN_ACTIVE:'Сбор уже выполняется.', SETUP_REQUIRED:'Не настроен доступ к реестру NetBox. Запустите обновление MVP на тестовом сервере.',
 COLLECTION_FAILED:'Не удалось собрать данные. Проверьте сервисного пользователя и права чтения Selectel.',
 HTTP_401:'Selectel отклонил имя пользователя или пароль.', HTTP_403:'Недостаточно прав чтения Selectel.',
 IMPORT_UNCONFIRMED:'Импорт не подтверждён. Последние сохранённые данные доступны в NetBox; повторите сбор.',
 RUN_INTERRUPTED:'Запуск прерван. Повторите сбор.', RUN_INTERRUPTED_OR_BUSY:'Сбор отложен или прерван. Повторите запуск.',
 RUN_TIMEOUT:'Сбор превысил отведённое время. Последние данные сохранены.',
};
async function request(path='', body?:unknown, signal?:AbortSignal){
 const response=await fetch('/api/v1/selectel'+path,{method:body===undefined?'GET':'POST',
  signal,cache:'no-store',credentials:'same-origin',headers:body===undefined?undefined:{'Content-Type':'application/json','X-NetBox-Sync-CSRF':'same-origin'},
  body:body===undefined?undefined:JSON.stringify(body)});
 const result=await response.json();
 if(!response.ok)throw new Error(messages[result.error]||'Операция недоступна. Обновите страницу и проверьте подключение.');
 return result;
}
const fetchAccounts=(signal:AbortSignal):Promise<Accounts>=>request('',undefined,signal);

export function SelectelPage(){
 const resource=useResource(fetchAccounts);
 const [selected,setSelected]=useState(''),[form,setForm]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const [draft,setDraft]=useState({account:'',name:'',username:'',password:''});
 const account=resource.data?.items.find(x=>x.account===selected);
 const running=resource.data?.items.some(x=>x.status==='running');
 useEffect(()=>{if(!running)return;const timer=setInterval(resource.refresh,5000);return()=>clearInterval(timer);},[running,resource.refresh]);
 async function save(event:FormEvent){event.preventDefault();setBusy(true);setError('');
  try{await request('',draft);setSelected(draft.account);setDraft({account:'',name:'',username:'',password:''});setForm(false);resource.refresh();}
  catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 async function collect(id:string){setBusy(true);setError('');try{await request('/'+id+'/collect',{});resource.refresh();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 return <main><h1>Selectel</h1><p>Серверы, DNS и объектное хранилище ваших аккаунтов. Имена проектов и ресурсов сохраняются как у провайдера.</p>
 <div className="sources-actions"><button onClick={()=>{setDraft({account:'',name:'',username:'',password:''});setForm(true);}}>Подключить аккаунт</button>
 <RefreshControl loading={resource.loading} error={resource.error} received={resource.received} refresh={resource.refresh}/></div>
 {(error||resource.error)&&<p role="alert">{error||'Не удалось загрузить аккаунты.'}</p>}
 {resource.data&&!resource.data.import_ready&&<p role="alert">Не настроен импорт в NetBox. Сначала выполните обновление Selectel MVP.</p>}
 {form&&<section className="panel"><h2>Подключение Selectel</h2><p>Используйте сервисного пользователя с правами чтения нужных проектов и продуктов. Пароль не возвращается в интерфейс.</p>
 <form onSubmit={save}>
 <label>Название подключения<input required maxLength={128} value={draft.name} onChange={e=>setDraft({...draft,name:e.target.value})}/></label>
 <label>Номер аккаунта<input required inputMode="numeric" pattern="[0-9]{1,20}" value={draft.account} onChange={e=>setDraft({...draft,account:e.target.value})}/></label>
 <label>Сервисный пользователь<input required autoComplete="off" maxLength={128} value={draft.username} onChange={e=>setDraft({...draft,username:e.target.value})}/></label>
 <label>Пароль<input type="password" required autoComplete="new-password" maxLength={1024} value={draft.password} onChange={e=>setDraft({...draft,password:e.target.value})}/></label>
 <p>Сохранение подключения не запускает сбор. Для замены пароля укажите тот же номер аккаунта.</p>
 <button disabled={busy} type="submit">Сохранить подключение</button> <button type="button" onClick={()=>{setDraft({...draft,password:''});setForm(false);}}>Отмена</button>
 </form></section>}
 <div className="scroll-region"><table><thead><tr><th>Аккаунт</th><th>Состояние</th><th>Последняя попытка</th><th>Действия</th></tr></thead><tbody>
 {resource.data?.items.map(a=><tr key={a.account}><td><button onClick={()=>setSelected(a.account)}>{a.name}</button><br/><small>№ {a.account}</small></td>
 <td>{({configured:'Готов к первому сбору',running:'Сбор выполняется',completed:'Данные обновлены',attention:'Требует внимания'} as Record<string,string>)[a.status]||a.status}</td>
 <td>{a.finished_at?new Date(a.finished_at*1000).toLocaleString('ru-RU'):'—'}</td><td><button disabled={busy||a.status==='running'||!resource.data?.import_ready} onClick={()=>collect(a.account)}>Собрать и обновить</button> <a href={a.url} target="_blank" rel="noreferrer">Ресурсы в NetBox ↗</a></td></tr>)}
 </tbody></table></div>
 {resource.data?.items.length===0&&<p>Подключите аккаунт, затем нажмите «Собрать и обновить».</p>}
 {account&&<section className="panel"><h2>{account.name} · {account.account}</h2>
 {account.error&&<p role="alert">{messages[account.error]||'Сбор не завершён. Последние успешные данные сохранены.'}</p>}
 {account.summary?<><p>Проектов: {account.summary.projects} · Серверов: {account.summary.servers} · Связано с NetBox: {account.summary.matched} · Без подтверждённой связи: {account.summary.unmatched}</p>
 <table><thead><tr><th>Категория</th><th>Результат</th><th>Наблюдений в списках</th></tr></thead><tbody>{account.summary.products.map(p=><tr key={p.product}><td>{p.title}</td><td>{p.state_label}</td><td>{Object.values(p.observations_by_collection).reduce((a,b)=>a+b,0)||'—'}</td></tr>)}</tbody></table>
 <p>Счётчики категорий не складываются в число уникальных ресурсов. Недоступная категория не означает отсутствие ресурсов.</p></>:<p>После первого сбора здесь появится результат по категориям.</p>}
 </section>}
 <p>Обновляются реестр и сведения уже связанных серверов. Адреса управления и сетевые назначения сохраняются. Для новых связей и создания карточек требуется отдельный просмотр плана. Автоматическое расписание пока недоступно.</p>
 </main>;
}
