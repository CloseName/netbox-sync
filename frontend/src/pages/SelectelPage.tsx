import {useEffect, useState, type FormEvent} from 'react';
import {useResource} from '../ui/useResource';
import {RefreshControl} from '../ui/RefreshControl';
import {exactTime} from '../ui/format';
import {ProviderIcon} from '../ui/ProviderIcon';
import {SelectelSchedule, type ProviderSchedule} from './SelectelSchedule';
import {SelectelLifecycle} from './SelectelLifecycle';

type Product = {product:string;title:string;state_label:string;observations_by_collection:Record<string,number>};
type Account = {account:string;name:string;username:string;status:string;error?:string;
 enabled?:boolean;schedule?:ProviderSchedule;next_run?:number;deleted?:boolean;
 lifecycle_pending?:{operation:string;key?:string|null;fingerprint:string};
 reconciliation?:{outcome:string;checked_at:number;run_id:string};
 url:string;run_id?:string;finished_at?:number;summary?:{projects:number;servers:number;matched:number;unmatched:number;products:Product[];
 placement_pending?:{resource:string;id:number;site_id:number;reason:string}[];
 native_mode?:string;native_created?:number;native_adopted?:number;native_blocked?:number}};
type Accounts = {items:Account[];import_ready:boolean};
const messages:Record<string,string> = {
 SELECTEL_GUARD_INCOMPATIBLE:'Версия Guard не поддерживает безопасную сверку импорта. Требуется согласованное обновление Sync и Guard. Сбор и импорт не запускались.',
 LIFECYCLE_BUSY:'Сейчас выполняется запись или сбор. Дождитесь завершения и повторите проверку; останавливать планировщик не требуется.',
 DISABLE_ACCOUNT_FIRST:'Сначала отключите аккаунт, затем проверьте список ресурсов.',
 LIFECYCLE_UNCONFIRMED:'Ответ операции не получен. Аккаунт отключён. В разделе отсоединения и удаления нажмите «Проверить результат операции».',
 PROVIDER_REVIEW_STALE:'Данные изменились после просмотра. Постройте новый план удаления или отсоединения.',
 PROVIDER_DEPENDENCIES_BLOCKED:'Обнаружены зависимые объекты. Обновите план и проверьте список препятствий.',
 PROVIDER_UNOWNED_CASCADE_BLOCKED:'Удаление затронуло бы другие объекты. Изменения отменены; отсоедините ресурс, чтобы сохранить карточку.',
 PROVIDER_APPLY_REFUSED:'NetBox отклонил операцию; изменения отменены. Проверьте права импортёра и зависимости ресурсов.',
 PROVIDER_REVIEW_REFUSED:'NetBox не смог проверить план. Проверьте версию плагина, права импортёра на просмотр зависимостей и включение режима Selectel v2.',
 ACCOUNT_DELETED:'Аккаунт удалён. Сначала подготовьте повторное подключение в разделе отсоединения и удаления.',
 RUN_ACTIVE:'Сбор уже выполняется.', SETUP_REQUIRED:'Не настроен доступ к Selectel или импорту NetBox. Проверьте сохранённые учётные данные, токен импортёра, права и версию Guard.',
 COLLECTION_FAILED:'Не удалось собрать данные. Проверьте сервисного пользователя и права чтения Selectel.',
 HTTP_401:'Selectel отклонил имя пользователя или пароль.', HTTP_403:'Недостаточно прав чтения Selectel.',
 IMPORT_UNCONFIRMED:'Ответ импорта не получен: часть данных могла сохраниться. Повторный импорт заблокирован. Проверка результата ниже только читает квитанцию Guard.',
 RUN_INTERRUPTED:'Процесс завершился без результата. Перед новым импортом администратору нужно сверить журнал запуска и данные NetBox.', RUN_INTERRUPTED_OR_BUSY:'Сбор не завершён или запись занята другим запуском. Импорт этого запуска не начинался; повторите позже.',
 ACCOUNT_DISABLED:'Аккаунт отключён. Новые сборы запрещены, сохранённые ресурсы остаются в NetBox.',
 NETBOX_IMPORT_SETUP_FAILED:'Не прошла проверка доступа к NetBox. Сбор Selectel и импорт не начинались. Проверьте доступность NetBox, токен импортёра, права и версию плагина.',
 NETBOX_IMPORT_REFUSED:'Импорт не применён: получен подтверждённый отказ Guard или запрос остановлен до отправки. Проверьте права импортёра и настройки подключения к NetBox.',
 COLLECTION_BUSY:'Сейчас собирается другой аккаунт Selectel. Дождитесь его завершения; запуск по расписанию подождёт автоматически.',
 SCHEDULE_INVALID:'Проверьте расписание: интервал от 1 до 366 дней, число месяца от 1 до 31, даты ГГГГ-ММ-ДД и часовой пояс, например Europe/Moscow.',
 SELECTEL_RESULT_TOO_LARGE:'Результат сбора превышает допустимый размер. Импорт не запускался. Передайте администратору номер аккаунта для проверки объёма данных.',
 SELECTEL_COLLECTOR_EXITED:'Процесс сбора завершился с ошибкой. Импорт не запускался. Требуется проверка сборщика администратором.',
 SELECTEL_RESULT_INVALID:'Сборщик вернул некорректный результат. Импорт не запускался. Требуется обновление или проверка сборщика.',
 COLLECTION_TOO_LARGE_OR_FAILED:'Предыдущий сбор завершился с ошибкой процесса или превышением размера результата. Обновите сборщик и выполните новый сбор.',
 RUN_TIMEOUT:'Сбор превысил отведённое время. Последние данные сохранены.',
};
const reconciliationMessages:Record<string,string> = {
 committed:'Guard подтвердил завершение именно этого запроса. Полнота данных Selectel проверяется отдельно.',
 not_found:'Квитанция запуска и следы его этапов не найдены. Это не доказывает отсутствие записей; повторный импорт остаётся заблокирован.',
 partial_evidence:'Найдены следы отдельных этапов без итоговой квитанции. Повторный импорт остаётся заблокирован.',
 intent_unavailable:'Квитанция найдена, но старый запуск не сохранил отпечаток запроса. Автоматически подтвердить соответствие нельзя.',
 conflict:'Данные квитанции не соответствуют сохранённому запуску. Повторный импорт остаётся заблокирован.',
 busy:'Guard ещё обрабатывает аккаунт. Проверку результата можно повторить позже.',
 unavailable:'Проверка недоступна или ответ несовместим. Состояние импорта сохранено.',
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
 async function configure(id:string,operation:string,value:unknown){setBusy(true);setError('');try{await request('/'+id+'/'+operation,value);resource.refresh();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 return <main className="selectel-workspace"><div className="page-heading"><div><h1><ProviderIcon provider="selectel"/> Selectel</h1><p className="muted">Серверы, DNS и объектное хранилище ваших аккаунтов.</p></div></div>
 <p role="note">Экспериментальная интеграция. Сопоставление ресурсов и подтверждение импорта ещё проходят проверку. При неопределённом результате повторный запуск заблокирован до сверки операции.</p>
 <div className="sources-actions"><button className="primary" onClick={()=>{setDraft({account:'',name:'',username:'',password:''});setForm(true);}}>Подключить аккаунт</button>
 <RefreshControl loading={resource.loading} error={resource.error} received={resource.received} refresh={resource.refresh}/></div>
 {(error||resource.error)&&<p role="alert">{error||'Не удалось загрузить аккаунты.'}</p>}
 {resource.data&&!resource.data.import_ready&&<p role="alert">Не настроен импорт в NetBox. Администратору нужно проверить токен импортёра, права и версию Guard.</p>}
 {form&&<section className="panel selectel-form"><h2>Подключение Selectel</h2><ol className="flow-steps"><li aria-current="step">Доступ</li><li>Первый сбор</li><li>Результат</li></ol><p>Используйте сервисного пользователя с правами чтения нужных проектов и продуктов. Пароль не возвращается в интерфейс.</p>
 <form onSubmit={save}>
 <label>Название подключения<input required maxLength={128} value={draft.name} onChange={e=>setDraft({...draft,name:e.target.value})}/></label>
 <label>Номер аккаунта<input required inputMode="numeric" pattern="[0-9]{1,20}" value={draft.account} onChange={e=>setDraft({...draft,account:e.target.value})}/></label>
 <label>Сервисный пользователь<input required autoComplete="off" maxLength={128} value={draft.username} onChange={e=>setDraft({...draft,username:e.target.value})}/></label>
 <label>Пароль<input type="password" required autoComplete="new-password" maxLength={1024} value={draft.password} onChange={e=>setDraft({...draft,password:e.target.value})}/></label>
 <p>Сохранение не проверяет доступ и не запускает сбор. Доступ к аккаунту и продуктам проверяется при сборе. «Собрать и обновить» также запускает импорт в NetBox. Для замены пароля укажите тот же номер аккаунта.</p>
 <div className="actions"><button className="primary" disabled={busy} type="submit">{busy?'Сохраняем…':'Сохранить подключение'}</button> <button disabled={busy} type="button" onClick={()=>{setDraft({...draft,password:''});setForm(false);}}>Отмена</button></div>
 </form></section>}
 <div className="account-cards selectel-table" aria-label="Аккаунты Selectel">
 {resource.data?.items.map(a=><section className="panel account-card" key={a.account} data-selected={a.account===selected}>
 <h2><ProviderIcon provider="selectel"/> <button className="account-name" aria-expanded={a.account===selected} onClick={()=>setSelected(a.account)}>{a.name}</button></h2><small>№ {a.account} · {a.username}</small>
 <p><span className={'badge badge-'+(a.status==='attention'||a.error?'danger':a.status==='running'?'info':'neutral')}>{({configured:'Доступ сохранён; ещё не проверен',running:'Сбор и импорт выполняются',completed:'Импорт подтверждён',attention:'Требует внимания',deleted:'Аккаунт удалён; доступ и расписание очищены'} as Record<string,string>)[a.status]||a.status}</span></p>
 {a.error&&<p className="account-error">{messages[a.error]||'Сбор не завершён. Проверьте результат аккаунта.'}</p>}
 {a.run_id&&<small>Идентификатор запуска: {a.run_id}</small>}
 {a.reconciliation&&<p role="status">Сверка: {reconciliationMessages[a.reconciliation.outcome]||reconciliationMessages.unavailable} Проверено: {exactTime(new Date(a.reconciliation.checked_at*1000).toISOString())}</p>}
 {(a.error==='IMPORT_UNCONFIRMED'||a.error==='RUN_INTERRUPTED')&&<button disabled={busy||!!a.lifecycle_pending||a.deleted} onClick={()=>void configure(a.account,'reconcile',{})}>Проверить результат импорта</button>}
 {a.finished_at&&<small>Последняя попытка: <time dateTime={new Date(a.finished_at*1000).toISOString()}>{exactTime(new Date(a.finished_at*1000).toISOString())}</time></small>}
 <div className="actions"><button disabled={busy||a.enabled===false||a.deleted||!!a.lifecycle_pending||a.error==='IMPORT_UNCONFIRMED'||a.error==='RUN_INTERRUPTED'||a.status==='running'||!resource.data?.import_ready} onClick={()=>{setSelected(a.account);void collect(a.account);}}>{a.status==='running'?'Сбор выполняется…':'Собрать и обновить'}</button><a href={a.url} target="_blank" rel="noreferrer">Ресурсы в NetBox ↗</a></div>
 <p>{a.deleted?'Сохранён только маркер удаления для защиты от повторной записи.':a.enabled===false?'Аккаунт отключён. Ресурсы сохранены.':a.next_run?'Следующий запуск: '+exactTime(new Date(a.next_run*1000).toISOString()):'Автоматический запуск не назначен.'}</p>
 <button disabled={busy||a.deleted||!!a.lifecycle_pending} onClick={()=>void configure(a.account,'enabled',{enabled:a.enabled===false})}>{a.enabled===false?'Включить аккаунт':'Отключить аккаунт'}</button>
 <p className="muted">Отключение запрещает новые запуски. Уже начатая запись в NetBox завершается.</p>
 {!a.deleted&&<SelectelSchedule key={a.account+JSON.stringify(a.schedule)} value={a.schedule} disabled={busy||!!a.lifecycle_pending} save={schedule=>configure(a.account,'schedule',{schedule})}/>}
 <SelectelLifecycle account={a.account} disabled={a.enabled===false} deleted={a.deleted} pending={a.lifecycle_pending} busy={busy} request={request} refresh={resource.refresh}/>
 <details><summary>Доступ</summary><p>Сервисный пользователь: {a.username}</p><button disabled={busy} onClick={()=>{setDraft({account:a.account,name:a.name,username:a.username,password:''});setForm(true);}}>Изменить доступ</button></details>
 </section>)}
 </div>
 {resource.data?.items.length===0&&<p>Подключите аккаунт, затем нажмите «Собрать и обновить».</p>}
 {account&&<section className="panel" id="selectel-account-detail"><h2>{account.name} · {account.account}</h2>
 {account.error&&<p role="alert">{messages[account.error]||'Сбор не завершён. Последние успешные данные сохранены.'}</p>}
 {account.summary?<><dl className="selectel-summary"><div><dt>Проектов</dt><dd>{account.summary.projects??'—'}</dd></div><div><dt>Серверов</dt><dd>{account.summary.servers}</dd></div><div><dt>Связано с NetBox</dt><dd>{account.summary.matched}</dd></div><div><dt>Без подтверждённой связи</dt><dd>{account.summary.unmatched}</dd></div></dl>
 {account.summary.native_mode==='registry_only'&&<p role="status">Данные собраны в реестр. Автоматическое создание обычных карточек NetBox не включено на сервере NetBox.</p>}
 {!!account.summary.placement_pending?.length&&<p role="alert">Для {account.summary.placement_pending.length} ресурсов площадка Selectel конфликтует с текущим размещением кластера, стойки или хоста. Сведения провайдера сохранены; размещение связанных объектов нужно проверить в NetBox.</p>}
 {account.summary.native_mode==='automatic'&&<p>Создано карточек: {account.summary.native_created}. Связано с существующими: {account.summary.native_adopted}. Требуют проверки: {account.summary.native_blocked}. <a href={account.url} target="_blank" rel="noreferrer">Проверить ресурсы и кандидатов в NetBox ↗</a></p>}
 <div className="scroll-region" tabIndex={0} role="region" aria-label="Результаты по категориям"><table><thead><tr><th scope="col">Категория</th><th scope="col">Результат</th><th scope="col">Наблюдений в списках</th></tr></thead><tbody>{(account.summary.products||[]).map(p=><tr key={p.product}><td>{p.title}</td><td>{p.state_label}</td><td>{Object.keys(p.observations_by_collection).length?Object.values(p.observations_by_collection).reduce((a,b)=>a+b,0):'—'}</td></tr>)}</tbody></table></div>
 {account.reconciliation?.outcome==='committed'&&<p>Квитанция подтверждает импорт, но не содержит отчёта о полноте категорий.</p>}
 <p className="muted">Счётчики категорий не складываются в число уникальных ресурсов. Недоступная категория не означает отсутствие ресурсов.</p></>:<p>{account.status==='configured'?'После первого сбора здесь появится результат по категориям.':account.status==='running'?'Ожидаем результат текущего сбора.':'Подробный результат по категориям не получен. Проверьте сохранённые ресурсы в NetBox.'}</p>}
 </section>}
 <details className="workspace-note"><summary>Как обновляются данные Selectel</summary><p>Кнопка «Собрать и обновить» запускает сбор и импорт реестра. Если на NetBox включён native-режим, импорт также создаёт или связывает карточки по проверкам Guard. Отдельного просмотра плана перед этой кнопкой пока нет. Адреса управления и сетевые назначения сохраняются. Подтверждение импорта не доказывает полноту аккаунта: проверьте результаты категорий и неподтверждённые связи. Расписание настраивается отдельно для каждого аккаунта, с интервалом от одного дня.</p></details>
 </main>;
}
