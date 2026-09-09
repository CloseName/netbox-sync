import {useEffect,useState} from 'react';
import {useLanguage} from '../ui/language';
import {authRequest} from '../AuthGate';
export function DestinationPermission({host,done}:{host:string;done:()=>void}){
 const [lang]=useLanguage(),t=(en:string,ru:string)=>lang==='ru'?ru:en;
 const [policy,setPolicy]=useState<any>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false),[key,setKey]=useState(()=>crypto.randomUUID());
 async function load(){try{setPolicy(await authRequest('policy'));setError('');setKey(crypto.randomUUID());}catch{setError(t('Policy unavailable or access denied.','Политика недоступна или недостаточно прав.'));}}
 useEffect(()=>{void load();},[host]);
 async function allow(){if(busy||!policy)return;setBusy(true);try{await authRequest('policy',{host,expected_revision:policy.revision,request_id:key});done();}catch(e){setError(e instanceof Error&&e.message==='POLICY_CONFLICT'?t('Policy changed. Reload and review before confirming.','Политика изменилась. Обновите и проверьте её перед подтверждением.'):t('Permission change not confirmed. Retry the same request or reload policy.','Изменение разрешения не подтверждено. Повторите тот же запрос или обновите политику.'));}finally{setBusy(false);}}
 return <section className="panel"><h2>{t('Destination permission','Разрешение назначения')}</h2><p>{t('This changes the connection-check policy only, not a firewall for subsequent synchronization.','Это политика проверки подключения, а не межсетевой экран последующей синхронизации.')}</p>
 {error&&<p role="alert">{error}</p>}
 {policy?.mode==='managed'&&policy?.ceiling==='public-ipv4'?<><p>{t('Allow this exact hostname or public IPv4 address:','Разрешить это точное имя или публичный IPv4-адрес:')} <strong>{host}</strong></p><p>{t('Protected addresses stay blocked. Only provider protocol ports are used. Test the connection again after this separate change.','Защищённые адреса остаются запрещены. Используются только порты протокола провайдера. После отдельного изменения повторите проверку подключения.')}</p><button disabled={busy} onClick={()=>void allow()}>{t('Allow destination','Разрешить назначение')}</button></>:policy&&<p>{t('Host-managed limits do not permit a web exception. Ask the host administrator to enable managed policy with an explicit ceiling once.','Ограничения сервера не допускают исключение через панель. Администратор сервера должен один раз включить веб-управление с явными границами доступа.')}</p>}
 <button disabled={busy} onClick={()=>void load()}>{t('Reload policy','Обновить политику')}</button></section>;
}
