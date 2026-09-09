import {useEffect,useState} from 'react';
import {useLanguage} from '../ui/language';
import {authRequest} from '../AuthGate';
export function DestinationPolicyPage(){
 const [lang]=useLanguage(),t=(en:string,ru:string)=>lang==='ru'?ru:en;
 const [policy,setPolicy]=useState<any>(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
 async function load(){setError('');try{setPolicy(await authRequest('policy'));}catch{setError(t('Policy unavailable or access denied.','Политика недоступна или недостаточно прав.'));}}
 useEffect(()=>{void load();},[]);
 async function revoke(host:string){if(busy)return;setBusy(true);try{await authRequest('policy',{host,operation:'revoke',expected_revision:policy.revision,request_id:crypto.randomUUID()});await load();}catch{setError(t('Change was not confirmed. Reload policy before retrying.','Изменение не подтверждено. Обновите политику перед повтором.'));}finally{setBusy(false);}}
 return <main><h1>{t('Source destinations','Назначения источников')}</h1><p>{t('Rules apply to connection checks during source registration. They do not stop existing scheduled synchronization. Host restrictions and protected-address rules cannot be overridden here.','Правила действуют на проверки подключения при регистрации источника. Они не останавливают существующую синхронизацию по расписанию. Ограничения сервера и защищённых адресов нельзя обойти через панель.')}</p>
 {error&&<p role="alert">{error}</p>}<button disabled={busy} onClick={()=>void load()}>{t('Reload policy','Обновить политику')}</button>
 {policy&&<section className="panel"><h2>{t('Web permissions','Разрешения панели')}</h2><p>{t('Revision','Ревизия')}: {policy.revision}</p>
 {policy.mode!=='managed'||policy.ceiling!=='public-ipv4'?<p>{t('Changes are limited by host policy.','Изменения ограничены политикой сервера.')}</p>:<p>{t('Add a destination from the Add source form when a connection is denied. Revoking a web permission invalidates pending connection checks.','Разрешите назначение в форме добавления источника при отказе подключения. Отзыв разрешения делает ожидающие результаты проверок недействительными.')}</p>}
 <ul>{policy.allowed_hosts.map((host:string)=><li key={host}><span>{host}</span> <button disabled={busy||policy.mode!=='managed'||policy.ceiling!=='public-ipv4'} onClick={()=>void revoke(host)}>{t('Revoke web permission','Отозвать разрешение панели')}</button></li>)}</ul>
 {!policy.allowed_hosts.length&&<p>{t('No web permissions added.','Разрешения через панель не добавлены.')}</p>}
 <details><summary>{t('Effective limits','Действующие ограничения')}</summary><pre>{JSON.stringify(policy.effective,null,2)}</pre></details>
 </section>}</main>;
}
