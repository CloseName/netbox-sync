import {useEffect, useState, type FormEvent} from 'react';
import {useResource} from '../ui/useResource';
import {RefreshControl} from '../ui/RefreshControl';
import {exactTime} from '../ui/format';
import {ProviderIcon} from '../ui/ProviderIcon';

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
 return <main className="selectel-workspace"><div className="page-heading"><div><h1><ProviderIcon provider="selectel"/> Selectel</h1><p className="muted">Серверы, DNS и объектное хранилище ваших аккаунтов.</p></div></div>
 <div className="sources-actions"><button className="primary" onClick={()=>{setDraft({account:'',name:'',username:'',password:''});setForm(true);}}>Подключить аккаунт</button>
 <RefreshControl loading={resource.loading} error={resource.error} received={resource.received} refresh={resource.refresh}/></div>
 {(error||resource.error)&&<p role="alert">{error||'Не удалось загрузить аккаунты.'}</p>}
 {resource.data&&!resource.data.import_ready&&<p role="alert">Не настроен импорт в NetBox. Сначала выполните обновление Selectel MVP.</p>}
 {form&&<section className="panel selectel-form"><h2>Подключение Selectel</h2><ol className="flow-steps"><li aria-current="step">Доступ</li><li>Первый сбор</li><li>Результат</li></ol><p>Используйте сервисного пользователя с правами чтения нужных проектов и продуктов. Пароль не возвращается в интерфейс.</p>
 <form onSubmit={save}>
 <label>Название подключения<input required maxLength={128} value={draft.name} onChange={e=>setDraft({...draft,name:e.target.value})}/></label>
 <label>Номер аккаунта<input required inputMode="numeric" pattern="[0-9]{1,20}" value={draft.account} onChange={e=>setDraft({...draft,account:e.target.value})}/></label>
 <label>Сервисный пользователь<input required autoComplete="off" maxLength={128} value={draft.username} onChange={e=>setDraft({...draft,username:e.target.value})}/></label>
 <label>Пароль<input type="password" required autoComplete="new-password" maxLength={1024} value={draft.password} onChange={e=>setDraft({...draft,password:e.target.value})}/></label>
 <p>Сохранение подключения не запускает сбор. Для замены пароля укажите тот же номер аккаунта.</p>
 <div className="actions"><button className="primary" disabled={busy} type="submit">{busy?'Сохраняем…':'Сохранить подключение'}</button> <button disabled={busy} type="button" onClick={()=>{setDraft({...draft,password:''});setForm(false);}}>Отмена</button></div>
 </form></section>}
 <div className="account-cards selectel-table" aria-label="Аккаунты Selectel">
 {resource.data?.items.map(a=><section className="panel account-card" key={a.account} data-selected={a.account===selected}>
 <h2><ProviderIcon provider="selectel"/> <button className="account-name" aria-expanded={a.account===selected} onClick={()=>setSelected(a.account)}>{a.name}</button></h2><small>№ {a.account} · {a.username}</small>
 <p><span className={'badge badge-'+(a.status==='attention'||a.error?'danger':a.status==='running'?'info':'neutral')}>{({configured:'Готов к первому сбору',running:'Сбор выполняется',completed:'Данные обновлены',attention:'Требует внимания'} as Record<string,string>)[a.status]||a.status}</span></p>
 {a.error&&<p className="account-error">{messages[a.error]||'Сбор не завершён. Проверьте результат аккаунта.'}</p>}
 {a.finished_at&&<small>Последняя попытка: <time dateTime={new Date(a.finished_at*1000).toISOString()}>{exactTime(new Date(a.finished_at*1000).toISOString())}</time></small>}
 <div className="actions"><button disabled={busy||a.status==='running'||!resource.data?.import_ready} onClick={()=>{setSelected(a.account);void collect(a.account);}}>{a.status==='running'?'Сбор выполняется…':'Собрать и обновить'}</button><a href={a.url} target="_blank" rel="noreferrer">Ресурсы в NetBox ↗</a></div>
 <details><summary>Доступ</summary><p>Сервисный пользователь: {a.username}</p><button disabled={busy} onClick={()=>{setDraft({account:a.account,name:a.name,username:a.username,password:''});setForm(true);}}>Изменить доступ</button></details>
 </section>)}
 </div>
 {resource.data?.items.length===0&&<p>Подключите аккаунт, затем нажмите «Собрать и обновить».</p>}
 {account&&<section className="panel" id="selectel-account-detail"><h2>{account.name} · {account.account}</h2>
 {account.error&&<p role="alert">{messages[account.error]||'Сбор не завершён. Последние успешные данные сохранены.'}</p>}
 {account.summary?<><dl className="selectel-summary"><div><dt>Проектов</dt><dd>{account.summary.projects}</dd></div><div><dt>Серверов</dt><dd>{account.summary.servers}</dd></div><div><dt>Связано с NetBox</dt><dd>{account.summary.matched}</dd></div><div><dt>Без подтверждённой связи</dt><dd>{account.summary.unmatched}</dd></div></dl>
 <div className="scroll-region" tabIndex={0} role="region" aria-label="Результаты по категориям"><table><thead><tr><th scope="col">Категория</th><th scope="col">Результат</th><th scope="col">Наблюдений в списках</th></tr></thead><tbody>{account.summary.products.map(p=><tr key={p.product}><td>{p.title}</td><td>{p.state_label}</td><td>{Object.keys(p.observations_by_collection).length?Object.values(p.observations_by_collection).reduce((a,b)=>a+b,0):'—'}</td></tr>)}</tbody></table></div>
 <p className="muted">Счётчики категорий не складываются в число уникальных ресурсов. Недоступная категория не означает отсутствие ресурсов.</p></>:<p>{account.status==='configured'?'После первого сбора здесь появится результат по категориям.':account.status==='running'?'Ожидаем результат текущего сбора.':'Подробный результат по категориям не получен. Проверьте сохранённые ресурсы в NetBox.'}</p>}
 </section>}
 <details className="workspace-note"><summary>Как обновляются данные Selectel</summary><p>Обновляются реестр и сведения уже связанных серверов. Адреса управления и сетевые назначения сохраняются. Для новых связей и создания карточек требуется отдельный просмотр плана. Автоматическое расписание пока недоступно. Имена проектов и ресурсов сохраняются как у провайдера.</p></details>
 </main>;
}
