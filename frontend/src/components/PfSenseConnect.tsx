import {exactTime} from '../ui/format';
import {useEffect,useRef,useState} from 'react';
import type {PfSenseVM} from '../api/pfsense';
import {usePermission} from '../AuthGate';
import {useLanguage} from '../ui/language';
const errors: Record<string, [string, string]> = {
  GUARD_UPGRADE_REQUIRED: ['Upgrade NetBox Guard before connecting.', 'Перед подключением обновите NetBox Guard.'],
  NETBOX_PREFLIGHT_FAILED: ['NetBox readiness check failed.', 'Проверка готовности NetBox не прошла; подготовка pfSense не запускалась.'],
  PFSENSE_FIELDS_REQUIRED: ['Set up the required pfSense fields in NetBox.', 'В NetBox отсутствуют служебные поля pfSense. Откройте подготовку NetBox в настройках Sync.'],
  PFSENSE_FIELDS_INCOMPATIBLE: ['The NetBox pfSense fields have incompatible types or assignments.', 'Служебные поля pfSense в NetBox имеют несовместимый тип или привязку.'],
  PERMISSION_DENIED: ['The apply token cannot change this VM.', 'Apply Token не имеет права изменять выбранную виртуальную машину в NetBox.'],
  TOKEN_WRITE_REQUIRED: ['Enable writes on the NetBox apply token.', 'Для Apply Token выключена запись в NetBox.'],
  GUARD_INSTANCE_CHANGED: ['The NetBox Guard instance has changed.', 'Идентификатор установки NetBox Guard изменился. Проверьте подключение NetBox.'],
  PFSENSE_SNAPSHOT_INVALID: ['NetBox rejected the snapshot or interface mapping.', 'NetBox отклонил структуру снимка или сопоставление интерфейсов pfSense.'],
  PATH_CONFLICT: ['The collector directory has unexpected ownership or permissions.', 'Каталог сборщика pfSense имеет другого владельца или небезопасные права.'],
  INSTALL_FAILED: ['Collector installation failed.', 'Не удалось установить файлы сборщика pfSense.'],
  USER_CONFLICT: ['The collector account already exists with a different owner.', 'Учётная запись сборщика уже существует и не принадлежит этому подключению. Требуется проверка.'],
  SOURCE_APPLY_ACTIVE: ['Another sync is running.', 'Сейчас выполняется синхронизация. Повторите после её завершения.'],
  POLICY_CONFLICT: ['The access policy changed. Retry the connection.', 'Правила доступа изменились. Повторите подключение.'],
  AUTH_DENIED: ['Insufficient permissions.', 'Недостаточно прав для этой операции.'],
  AUTH_REQUIRED: ['Sign in to Sync again.', 'Войдите в Sync повторно.'],
  TLS_FAILED: ['Certificate verification failed.', 'Не удалось проверить сертификат.'],
  UNSUPPORTED_VERSION: ['This version of pfSense is unsupported.', 'Поддерживаются стабильные pfSense CE 2.6.0 и новее в ветке 2.x. Plus и предварительные версии требуют отдельной проверки.'],
  UNSUPPORTED_CAPABILITIES: ['Required system utilities or PHP features are unavailable.', 'На pfSense отсутствуют необходимые функции PHP или системные средства. Подготовка остановлена до изменений.'],
  SSH_DISABLED: ['Enable SSH on pfSense and reconnect.', 'На pfSense выключен SSH. Включите его и повторите подключение.'],
  VM_IDENTITY_MISMATCH: ['The pfSense MAC addresses do not match the selected VM.', 'MAC-адреса pfSense не совпадают с выбранной VM.'],
  GUI_COMMAND_FAILED: ['Check access to Diagnostics: Command.', 'Не удалось выполнить подготовку. Проверьте вход и права Diagnostics: Command.'],
  GUI_ACCESS_DENIED: ['Sign-in or access to Diagnostics: Command was denied.', 'Вход или доступ к Diagnostics: Command запрещён.'],
  NETBOX_IMPORT_FAILED: ['NetBox rejected the collected snapshot. Check Guard and the apply token.', 'Сбор выполнен, но NetBox не принял снимок. Проверьте версию Guard и права записи.'],
  OUTCOME_UNKNOWN: ['Refresh status to check the outcome.', 'Результат не подтверждён. Проверьте состояние перед повторным подключением.'],
  ENDPOINT_CHANGED: ['This VM already has a different confirmed endpoint.', 'Для этой VM сохранён другой адрес. Автоматическая замена подключения запрещена.'],
  CONNECTION_FAILED: ['Check the destination, credentials and connectivity from the Sync server.', 'Подключение не завершено. Проверьте адрес, учётные данные и сетевую доступность с сервера Sync.'],
  CONNECT_REQUIRED: ['Complete setup with an administrator account first.', 'Сначала завершите подключение с административной учётной записью.'],
  SSH_HOST_KEY_CHANGED: ['The SSH host key changed.', 'SSH-ключ устройства изменился. Подключение остановлено.'],
};
export function PfSenseConnect({vm,refreshRevision=0}:{vm:PfSenseVM;refreshRevision?:number}){
 const [enabled,setEnabled]=useState(true),[interval,setIntervalMinutes]=useState(60);
 const [success,setSuccess]=useState('');
 const dialog=useRef<HTMLDialogElement>(null),[language]=useLanguage(),t=(en:string,ru:string)=>language==='ru'?ru:en;
 const allowed=usePermission('source.register'),canCollect=usePermission('source.apply');
 const [address,setAddress]=useState(vm.address),[port,setPort]=useState(443),[verify,setVerify]=useState(true),[username,setUsername]=useState(''),[password,setPassword]=useState('');
 const [refreshing,setRefreshing]=useState(false);
 const refreshLock=useRef(false);
 const [busy,setBusy]=useState(false),[status,setStatus]=useState<Record<string,unknown>|null>(null),[failure,setFailure]=useState('');
 useEffect(()=>{void refresh();const timer=window.setInterval(()=>{if(!dialog.current?.open)void refresh();},30000);return ()=>window.clearInterval(timer);},[vm.id,refreshRevision]);
 function failureMessage(value:Record<string, unknown>) {
   const code=String(value.error??'');
   if(!code)return '';
   const stage=value.error_stage;
   const port=stage==='ssh'?value.ssh_port:value.port;
   const endpoint=(stage==='https'||stage==='ssh') && value.address && port
     ? `${String(stage).toUpperCase()} ${value.address}:${port}` : stage==='netbox'?'NetBox':'';
   const messages:Record<string,string>={
     TIMEOUT:t('Connection timed out. Check connectivity from the Sync server.','Время ожидания соединения истекло. Проверьте доступность с сервера Sync.'),
     COLLECT_TIMEOUT:t('Collection timed out.','Время ожидания сбора истекло.'),
     DNS_FAILED:t('DNS lookup failed.','Не удалось разрешить имя через DNS.'),
     DESTINATION_DENIED:t('Destination denied by Sync policy.','Адрес запрещён политикой Sync.'),
   };
   const reason=messages[code] || (errors[code] ? t(...errors[code]) : code);
   return endpoint ? `${endpoint} — ${reason}` : reason;
 }
 async function refresh(){if(refreshLock.current)return;refreshLock.current=true;setRefreshing(true);try{const r=await fetch(`/api/v1/pfsense/${vm.id}/status`,{cache:'no-store',signal:AbortSignal.timeout(15000)});const value=await r.json();if(!r.ok&&!value.status)throw Error();setStatus(value);setEnabled(value.sync_enabled??true);setIntervalMinutes(value.interval_minutes??60);setFailure(failureMessage(value));if(value.address){setAddress(value.address);setPort(value.port);setVerify(value.verify_tls);}}catch{setFailure(t('Status unavailable. Try again.','Состояние недоступно. Повторите обновление.'));}finally{refreshLock.current=false;setRefreshing(false);}}
 async function run(operation:'connect'|'collect'|'schedule'){
 setBusy(true);setFailure('');setSuccess('');
 const credential=password;setPassword('');
 try{
 const policy=await fetch('/api/v1/policy',{cache:'no-store'});if(!policy.ok)throw Error();const {revision}=await policy.json();
 const response=await fetch(`/api/v1/pfsense/${vm.id}/${operation}`,{method:'POST',headers:{'Content-Type':'application/json','X-Netbox-Sync-CSRF':'same-origin'},body:JSON.stringify(operation==='connect'?{address,port,verify_tls:verify,username,password:credential,sync_enabled:enabled,interval_minutes:interval,policy_revision:revision}:operation==='schedule'?{sync_enabled:enabled,interval_minutes:interval,policy_revision:revision}:{policy_revision:revision})});
 const result=await response.json();setStatus(current=>({...current,...result}));
 if(response.ok&&!result.error){setSuccess(operation==='schedule'?t('Schedule saved.','Расписание сохранено.'):operation==='connect'?t('NetBox Sync account is ready. Collection completed.','Учётная запись NetBox Sync готова. Данные успешно собраны.'):t('Collection completed successfully.','Данные успешно собраны.'));dialog.current?.close();}
 if(!response.ok||result.error)setFailure(failureMessage(result)||t('Operation failed. Refresh status.','Операция не завершена. Обновите состояние.'));
 }catch{setFailure(t('Result unknown. Refresh status.','Результат неизвестен. Обновите состояние.'));}finally{setBusy(false);}
 }
 return <><td>{String(status?.confirmed_address || vm.address || '—')}</td><td><div className="pfsense-connection-cell"><div className="pfsense-row-status"><span className={'badge badge-'+(status?.status==='CONNECTED'?'success':status?.status==='ATTENTION'?'warning':'neutral')}>{status?.status==='CONNECTED'?t('Connected','Подключён'):status?.status==='ATTENTION'?t('Needs attention','Нужна проверка'):t('Not connected','Не подключён')}</span>{!!status?.collected_at&&<small>{t('Last collection: ','Последний сбор: ')}{exactTime(String(status.collected_at))}</small>}{!!status?.ssh_port&&<small>{status.sync_enabled?t('Automatic collection enabled','Автосбор включён'):t('Manual collection','Ручной сбор')}</small>}{success&&<div className="pfsense-success" role="status">{success}</div>}</div><button onClick={()=>{dialog.current?.showModal();void refresh();}}>{t('Connection','Подключение')}</button><dialog className="pfsense-connect" ref={dialog} onClose={()=>setPassword('')}><h2>{vm.name} — {vm.cluster}</h2>
 <p>{t('Connect once to create the NetBox Sync account and collect data. Your administrator password is not saved.','Подключитесь один раз: Sync создаст учётную запись NetBox Sync и соберёт данные. Пароль администратора не сохраняется.')}</p>
 <p>{t('pfSense CE 2.6.0+ (2.x RELEASE) · SSH enabled · LDAP or local administrator with Diagnostics: Command access.','pfSense CE 2.6.0+ (2.x RELEASE) · SSH включён · Администратор LDAP или локальный с доступом к Diagnostics: Command.')}</p>
 <p className={status?.status==='CONNECTED'?'pfsense-success':''}>{t('Status','Состояние')}: {({NOT_CONNECTED:t('Not connected','Не подключён'),RUNNING:t('Working…','Выполняется…'),ATTENTION:t('Needs attention','Нужна проверка'),CONNECTED:t('Connected','Подключён')}[String(status?.status)]??'…')}{status?.collected_at?' · '+String(status.collected_at):''}</p>
 {failure&&<p role="alert">{failure}</p>}
 {allowed&&<form onSubmit={e=>{e.preventDefault();void run('connect');}}><label>{t('pfSense hostname or IPv4','Имя хоста или IPv4 pfSense')}<input required value={address} onChange={e=>setAddress(e.target.value)} disabled={busy}/></label><label>{t('HTTPS port','Порт HTTPS')}<input type="number" min="1" max="65535" value={port} onChange={e=>setPort(Number(e.target.value))} disabled={busy}/></label>
 <label><input type="checkbox" checked={verify} onChange={e=>setVerify(e.target.checked)} disabled={busy}/>{t('Verify TLS certificate','Проверять TLS-сертификат')}</label>
 {!verify&&<p>{t('The server certificate will not be verified for this connection.','Для этого подключения сертификат сервера проверяться не будет.')}</p>}
 <label>{t('Administrator (LDAP or local)','Администратор (LDAP или локальный)')}<input required autoComplete="username" value={username} onChange={e=>setUsername(e.target.value)} disabled={busy}/></label>
 <label>{t('Password','Пароль')}<input type="password" required autoComplete="off" value={password} onChange={e=>setPassword(e.target.value)} disabled={busy}/></label>
 <label><input type="checkbox" checked={enabled} onChange={e=>setEnabled(e.target.checked)} disabled={busy}/>{t('Collect automatically','Собирать автоматически')}</label>
 {enabled&&<label>{t('Interval (minutes)','Интервал (минуты)')}<input type="number" min="5" max="10080" value={interval} onChange={e=>setIntervalMinutes(Number(e.target.value))} disabled={busy}/></label>}
 <button className="primary" disabled={busy}>{busy?t('Working…','Выполняется…'):t('Set up and collect','Подключить и собрать')}</button></form>}
 {canCollect&&!!status?.ssh_port&&<button disabled={busy} onClick={()=>void run('schedule')}>{t('Save schedule','Сохранить расписание')}</button>}
 {canCollect&&<button disabled={busy||!status?.ssh_port} onClick={()=>void run('collect')}>{t('Collect now','Собрать сейчас')}</button>}
 <button type="button" disabled={refreshing} onClick={()=>void refresh()}>{refreshing?t('Refreshing…','Обновляем…'):t('Refresh status','Обновить состояние')}</button><button type="button" onClick={()=>dialog.current?.close()}>{t('Close','Закрыть')}</button></dialog></div></td></>;
}
