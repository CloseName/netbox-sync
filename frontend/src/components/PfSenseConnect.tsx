import {useRef,useState} from 'react';
import type {PfSenseVM} from '../api/pfsense';
import {usePermission} from '../AuthGate';
import {useLanguage} from '../ui/language';
const errors:Record<string,string>={SOURCE_APPLY_ACTIVE:'Сейчас выполняется синхронизация. Повторите после её завершения.',POLICY_CONFLICT:'Правила доступа изменились. Повторите подключение.',AUTH_DENIED:'Недостаточно прав для этой операции.',AUTH_REQUIRED:'Войдите в Sync повторно.',TLS_FAILED:'Не удалось проверить сертификат pfSense.',UNSUPPORTED_VERSION:'Автоматическая подготовка пока поддерживает pfSense CE 2.7.2.',SSH_DISABLED:'На pfSense выключен SSH. Включите его и повторите подключение.',VM_IDENTITY_MISMATCH:'MAC-адреса pfSense не совпадают с выбранной VM.',GUI_COMMAND_FAILED:'Не удалось выполнить подготовку. Проверьте вход и права Diagnostics: Command.',GUI_ACCESS_DENIED:'Вход или доступ к Diagnostics: Command запрещён.',NETBOX_IMPORT_FAILED:'Сбор выполнен, но NetBox не принял снимок. Проверьте версию Guard и права записи.',OUTCOME_UNKNOWN:'Результат не подтверждён. Проверьте состояние перед повторным подключением.',ENDPOINT_CHANGED:'Для этой VM сохранён другой адрес. Автоматическая замена подключения запрещена.',CONNECTION_FAILED:'Подключение не завершено. Проверьте адрес, учётные данные и доступность SSH.',CONNECT_REQUIRED:'Сначала завершите подключение с административной учётной записью.',SSH_HOST_KEY_CHANGED:'SSH-ключ устройства изменился. Подключение остановлено.'};
export function PfSenseConnect({vm}:{vm:PfSenseVM}){
 const dialog=useRef<HTMLDialogElement>(null),[language]=useLanguage(),t=(en:string,ru:string)=>language==='ru'?ru:en;
 const allowed=usePermission('source.register'),canCollect=usePermission('source.apply');
 const [address,setAddress]=useState(vm.address),[port,setPort]=useState(443),[verify,setVerify]=useState(true),[username,setUsername]=useState(''),[password,setPassword]=useState('');
 const [busy,setBusy]=useState(false),[status,setStatus]=useState<Record<string,unknown>|null>(null),[failure,setFailure]=useState('');
 async function refresh(){try{const r=await fetch(`/api/v1/pfsense/${vm.id}/status`,{cache:'no-store'});if(!r.ok)throw Error();const value=await r.json();setStatus(value);setFailure(value.error?(errors[value.error]||String(value.error)):'');if(value.address){setAddress(value.address);setPort(value.port);setVerify(value.verify_tls);}}catch{setFailure(t('Status unavailable','Состояние недоступно'));}}
 async function run(operation:'connect'|'collect'){
 setBusy(true);setFailure('');
 const credential=password;setPassword('');
 try{
 const policy=await fetch('/api/v1/policy',{cache:'no-store'});if(!policy.ok)throw Error();const {revision}=await policy.json();
 const response=await fetch(`/api/v1/pfsense/${vm.id}/${operation}`,{method:'POST',headers:{'Content-Type':'application/json','X-Netbox-Sync-CSRF':'same-origin'},body:JSON.stringify(operation==='connect'?{address,port,verify_tls:verify,username,password:credential,policy_revision:revision}:{policy_revision:revision})});
 const result=await response.json();setStatus(result);
 if(!response.ok||result.error)setFailure(errors[result.error]||t('Operation failed. Refresh status.','Операция не завершена. Обновите состояние.'));
 }catch{setFailure(t('Result unknown. Refresh status.','Результат неизвестен. Обновите состояние.'));}finally{setBusy(false);}
 }
 return <><button onClick={()=>{dialog.current?.showModal();void refresh();}}>{t('Connection','Подключение')}</button><dialog className="pfsense-connect" ref={dialog} onClose={()=>setPassword('')}><h2>{vm.name} — {vm.cluster}</h2>
 <p>{t('Setup creates a dedicated collector account and key, installs the collector, verifies VM interfaces and saves a snapshot. The administrator password is not stored.','Подключение создаст отдельную служебную учётную запись и ключ, установит сборщик, проверит интерфейсы VM и сохранит снимок. Административный пароль не сохраняется.')}</p>
 <p>{t('Automatic setup: pfSense CE 2.7.2; SSH must be enabled. Use an LDAP or local administrator with Diagnostics: Command access.','Автоматическая подготовка: pfSense CE 2.7.2; SSH должен быть включён. Используйте администратора LDAP или локального пользователя с доступом к Diagnostics: Command.')}</p>
 <p>{t('Status','Состояние')}: {({NOT_CONNECTED:t('Not connected','Не подключён'),RUNNING:t('Working…','Выполняется…'),ATTENTION:t('Needs attention','Нужна проверка'),CONNECTED:t('Connected','Подключён')}[String(status?.status)]??'…')}{status?.collected_at?' · '+String(status.collected_at):''}</p>
 {failure&&<p role="alert">{failure}</p>}
 {allowed&&<form onSubmit={e=>{e.preventDefault();void run('connect');}}><label>{t('pfSense hostname or IPv4','Имя хоста или IPv4 pfSense')}<input required value={address} onChange={e=>setAddress(e.target.value)} disabled={busy}/></label><label>HTTPS port<input type="number" min="1" max="65535" value={port} onChange={e=>setPort(Number(e.target.value))} disabled={busy}/></label>
 <label><input type="checkbox" checked={verify} onChange={e=>setVerify(e.target.checked)} disabled={busy}/>{t('Verify TLS certificate','Проверять TLS-сертификат')}</label>
 {!verify&&<p>{t('The server certificate will not be verified for this connection.','Для этого подключения сертификат сервера проверяться не будет.')}</p>}
 <label>{t('Administrator (LDAP or local)','Администратор (LDAP или локальный)')}<input required autoComplete="username" value={username} onChange={e=>setUsername(e.target.value)} disabled={busy}/></label>
 <label>{t('Password','Пароль')}<input type="password" required autoComplete="off" value={password} onChange={e=>setPassword(e.target.value)} disabled={busy}/></label>
 <button className="primary" disabled={busy}>{busy?t('Working…','Выполняется…'):t('Set up and collect','Подключить и собрать')}</button></form>}
 {canCollect&&<button disabled={busy||!status?.ssh_port} onClick={()=>void run('collect')}>{t('Collect now','Собрать сейчас')}</button>}
 <button disabled={busy} onClick={()=>void refresh()}>{t('Refresh status','Обновить состояние')}</button><button disabled={busy} onClick={()=>dialog.current?.close()}>{t('Close','Закрыть')}</button></dialog></>;
}
