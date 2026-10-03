import {useEffect,useRef,useState} from 'react';
import type {PfSenseVM} from '../api/pfsense';
import {usePermission} from '../AuthGate';
import {useLanguage} from '../ui/language';
const errors:Record<string,string>={USER_CONFLICT:'Учётная запись netbox-sync уже существует и не принадлежит этому подключению. Требуется проверка.',SOURCE_APPLY_ACTIVE:'Сейчас выполняется синхронизация. Повторите после её завершения.',POLICY_CONFLICT:'Правила доступа изменились. Повторите подключение.',AUTH_DENIED:'Недостаточно прав для этой операции.',AUTH_REQUIRED:'Войдите в Sync повторно.',TLS_FAILED:'Не удалось проверить сертификат pfSense.',UNSUPPORTED_VERSION:'Автоматическая подготовка пока поддерживает pfSense CE 2.7.2.',SSH_DISABLED:'На pfSense выключен SSH. Включите его и повторите подключение.',VM_IDENTITY_MISMATCH:'MAC-адреса pfSense не совпадают с выбранной VM.',GUI_COMMAND_FAILED:'Не удалось выполнить подготовку. Проверьте вход и права Diagnostics: Command.',GUI_ACCESS_DENIED:'Вход или доступ к Diagnostics: Command запрещён.',NETBOX_IMPORT_FAILED:'Сбор выполнен, но NetBox не принял снимок. Проверьте версию Guard и права записи.',OUTCOME_UNKNOWN:'Результат не подтверждён. Проверьте состояние перед повторным подключением.',ENDPOINT_CHANGED:'Для этой VM сохранён другой адрес. Автоматическая замена подключения запрещена.',CONNECTION_FAILED:'Подключение не завершено. Проверьте адрес, учётные данные и доступность SSH.',CONNECT_REQUIRED:'Сначала завершите подключение с административной учётной записью.',SSH_HOST_KEY_CHANGED:'SSH-ключ устройства изменился. Подключение остановлено.'};
export function PfSenseConnect({vm}:{vm:PfSenseVM}){
 const [enabled,setEnabled]=useState(true),[interval,setInterval]=useState(60);
 const [success,setSuccess]=useState('');
 const dialog=useRef<HTMLDialogElement>(null),[language]=useLanguage(),t=(en:string,ru:string)=>language==='ru'?ru:en;
 const allowed=usePermission('source.register'),canCollect=usePermission('source.apply');
 const [address,setAddress]=useState(vm.address),[port,setPort]=useState(443),[verify,setVerify]=useState(true),[username,setUsername]=useState(''),[password,setPassword]=useState('');
 const [busy,setBusy]=useState(false),[status,setStatus]=useState<Record<string,unknown>|null>(null),[failure,setFailure]=useState('');
 useEffect(()=>{void refresh();const timer=setInterval(()=>{if(!dialog.current?.open)void refresh();},30000);return ()=>clearInterval(timer);},[vm.id]);
 async function refresh(){try{const r=await fetch(`/api/v1/pfsense/${vm.id}/status`,{cache:'no-store'});if(!r.ok)throw Error();const value=await r.json();setStatus(value);setEnabled(value.sync_enabled??true);setInterval(value.interval_minutes??60);setFailure(value.error?(errors[value.error]||String(value.error)):'');if(value.address){setAddress(value.address);setPort(value.port);setVerify(value.verify_tls);}}catch{setFailure(t('Status unavailable','Состояние недоступно'));}}
 async function run(operation:'connect'|'collect'|'schedule'){
 setBusy(true);setFailure('');setSuccess('');
 const credential=password;setPassword('');
 try{
 const policy=await fetch('/api/v1/policy',{cache:'no-store'});if(!policy.ok)throw Error();const {revision}=await policy.json();
 const response=await fetch(`/api/v1/pfsense/${vm.id}/${operation}`,{method:'POST',headers:{'Content-Type':'application/json','X-Netbox-Sync-CSRF':'same-origin'},body:JSON.stringify(operation==='connect'?{address,port,verify_tls:verify,username,password:credential,sync_enabled:enabled,interval_minutes:interval,policy_revision:revision}:operation==='schedule'?{sync_enabled:enabled,interval_minutes:interval,policy_revision:revision}:{policy_revision:revision})});
 const result=await response.json();setStatus(result);
 if(response.ok&&!result.error){setSuccess(operation==='schedule'?t('Schedule saved.','Расписание сохранено.'):operation==='connect'?t('NetBox Sync account is ready. Collection completed.','Учётная запись NetBox Sync готова. Данные успешно собраны.'):t('Collection completed successfully.','Данные успешно собраны.'));dialog.current?.close();}
 if(!response.ok||result.error)setFailure(errors[result.error]||t('Operation failed. Refresh status.','Операция не завершена. Обновите состояние.'));
 }catch{setFailure(t('Result unknown. Refresh status.','Результат неизвестен. Обновите состояние.'));}finally{setBusy(false);}
 }
 return <><div className="pfsense-row-status"><span className={status?.status==='CONNECTED'?'pfsense-success':''}>{status?.status==='CONNECTED'?t('Connected','Подключён'):status?.status==='ATTENTION'?t('Needs attention','Нужна проверка'):t('Not connected','Не подключён')}</span>{!!status?.collected_at&&<small>{t('Last collection: ','Последний сбор: ')}{new Date(String(status.collected_at)).toLocaleString()}</small>}{!!status?.ssh_port&&<small>{status.sync_enabled?t('Automatic collection enabled','Автосбор включён'):t('Manual collection','Ручной сбор')}</small>}{success&&<div className="pfsense-success" role="status">{success}</div>}</div><button onClick={()=>{dialog.current?.showModal();void refresh();}}>{t('Connection','Подключение')}</button><dialog className="pfsense-connect" ref={dialog} onClose={()=>setPassword('')}><h2>{vm.name} — {vm.cluster}</h2>
 <p>{t('Connect once to create the NetBox Sync account and collect data. Your administrator password is not saved.','Подключитесь один раз: Sync создаст учётную запись NetBox Sync и соберёт данные. Пароль администратора не сохраняется.')}</p>
 <p>{t('pfSense CE 2.7.2 · SSH enabled · LDAP or local administrator with Diagnostics: Command access.','pfSense CE 2.7.2 · SSH включён · Администратор LDAP или локальный с доступом к Diagnostics: Command.')}</p>
 <p className={status?.status==='CONNECTED'?'pfsense-success':''}>{t('Status','Состояние')}: {({NOT_CONNECTED:t('Not connected','Не подключён'),RUNNING:t('Working…','Выполняется…'),ATTENTION:t('Needs attention','Нужна проверка'),CONNECTED:t('Connected','Подключён')}[String(status?.status)]??'…')}{status?.collected_at?' · '+String(status.collected_at):''}</p>
 {failure&&<p role="alert">{failure}</p>}
 {allowed&&<form onSubmit={e=>{e.preventDefault();void run('connect');}}><label>{t('pfSense hostname or IPv4','Имя хоста или IPv4 pfSense')}<input required value={address} onChange={e=>setAddress(e.target.value)} disabled={busy}/></label><label>HTTPS port<input type="number" min="1" max="65535" value={port} onChange={e=>setPort(Number(e.target.value))} disabled={busy}/></label>
 <label><input type="checkbox" checked={verify} onChange={e=>setVerify(e.target.checked)} disabled={busy}/>{t('Verify TLS certificate','Проверять TLS-сертификат')}</label>
 {!verify&&<p>{t('The server certificate will not be verified for this connection.','Для этого подключения сертификат сервера проверяться не будет.')}</p>}
 <label>{t('Administrator (LDAP or local)','Администратор (LDAP или локальный)')}<input required autoComplete="username" value={username} onChange={e=>setUsername(e.target.value)} disabled={busy}/></label>
 <label>{t('Password','Пароль')}<input type="password" required autoComplete="off" value={password} onChange={e=>setPassword(e.target.value)} disabled={busy}/></label>
 <label><input type="checkbox" checked={enabled} onChange={e=>setEnabled(e.target.checked)} disabled={busy}/>{t('Collect automatically','Собирать автоматически')}</label>
 {enabled&&<label>{t('Interval (minutes)','Интервал (минуты)')}<input type="number" min="5" max="10080" value={interval} onChange={e=>setInterval(Number(e.target.value))} disabled={busy}/></label>}
 <button className="primary" disabled={busy}>{busy?t('Working…','Выполняется…'):t('Set up and collect','Подключить и собрать')}</button></form>}
 {canCollect&&!!status?.ssh_port&&<button disabled={busy} onClick={()=>void run('schedule')}>{t('Save schedule','Сохранить расписание')}</button>}
 {canCollect&&<button disabled={busy||!status?.ssh_port} onClick={()=>void run('collect')}>{t('Collect now','Собрать сейчас')}</button>}
 <button disabled={busy} onClick={()=>void refresh()}>{t('Refresh status','Обновить состояние')}</button><button disabled={busy} onClick={()=>dialog.current?.close()}>{t('Close','Закрыть')}</button></dialog></>;
}
