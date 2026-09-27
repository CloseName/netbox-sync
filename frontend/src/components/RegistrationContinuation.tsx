import {useEffect,useRef,useState,type FormEvent} from 'react';
import {Link} from 'react-router-dom';
import {CredentialField} from './CredentialField';
import {inspectConnection,registerSource,HostRegistrationFailure,hostRegistrationMessages,SourceConnectionError,connectionMessages,RegistrationFailure} from '../api/onboarding';
import type {RegistrationInput} from '../api/onboarding';
import type {Source} from '../api/sources';
import {sourcePath} from '../ui/routes';

type SavedRequest=Omit<RegistrationInput,'onboarding_token'>;
type Attempt={source_instance:string;registration_id:string;request:SavedRequest|null;created_at:string};
/** Only server-held, actor-bound non-secret requests survive browser closure. */
export function RegistrationContinuation({language,done}:{language:string;done:(source:Source)=>void}){
 const t=(en:string,ru:string)=>language==='ru'?ru:en;
 const [attempts,setAttempts]=useState<Attempt[]>([]),[selected,setSelected]=useState<Attempt|null>(null);
 const [token,setToken]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[message,setMessage]=useState(''),[existing,setExisting]=useState(false);
 const running=useRef(false),checking=useRef(false);
 const selectedRef=useRef(selected);selectedRef.current=selected;
 useEffect(()=>{const controller=new AbortController();void fetch('/api/v1/registration-attempts',{cache:'no-store',signal:controller.signal}).then(async r=>{
   if(!r.ok)throw new Error();const data=await r.json();if(!Array.isArray(data.attempts))throw new Error();setAttempts(data.attempts);
 }).catch(()=>{if(!controller.signal.aborted)setError(t('Saved registration attempts could not be loaded.','Не удалось загрузить сохранённые попытки добавления.'));});return()=>controller.abort();},[]);
 function failure(value:unknown){setError(value instanceof HostRegistrationFailure?hostRegistrationMessages[value.code]?.[language==='ru'?1:0]||t('Identity requires review.','Нужна проверка идентичности.'):value instanceof SourceConnectionError?connectionMessages[value.code][language==='ru'?1:0]:value instanceof RegistrationFailure&&value.uncertain?t('The result is unconfirmed. Check server state; do not start a new source.','Результат не подтверждён. Сверьте состояние сервера; не создавайте новый источник.'):t('Continuation was not confirmed. Recheck server state and the connection; the original request is retained.','Продолжение не подтверждено. Сверьте состояние сервера и подключение; исходный запрос сохранён.'));}
 async function check(){if(!selected||checking.current||running.current)return;const attempt=selected;checking.current=true;try{
   const r=await fetch('/api/v1/sources/registration-status',{method:'POST',cache:'no-store',headers:{'Content-Type':'application/json','X-NetBox-Sync-CSRF':'same-origin'},body:JSON.stringify({source_instance:selected.source_instance,registration_id:selected.registration_id}),signal:AbortSignal.timeout(40000)});
   if(!r.ok)throw new Error();const result=await r.json();if(selectedRef.current!==attempt)return;setError('');setExisting(result.status==='REGISTERED');
   setMessage(result.status==='REGISTERED'?t('The source is registered. Open the saved result.','Источник зарегистрирован. Откройте сохранённый результат.'):result.catalog_status==='CREATED'?t('Cluster creation is confirmed. Recheck access to continue the original source registration.','Создание кластера подтверждено. Повторите проверку доступа для продолжения исходной регистрации.'):t('Registration is not confirmed. Its result is checked automatically; no write is repeated.','Регистрация не подтверждена. Результат проверяется автоматически; запись не повторяется.'));
 }catch(value){if(selectedRef.current===attempt)failure(value);}finally{checking.current=false;}}
 const checkRef=useRef(check);checkRef.current=check;
 useEffect(()=>{if(!selected||existing)return;void checkRef.current();const timer=window.setInterval(()=>void checkRef.current(),5000);return()=>window.clearInterval(timer);},[selected,existing]);
 async function connect(event:FormEvent<HTMLFormElement>){event.preventDefault();if(!selected?.request||running.current)return;const form=event.currentTarget;if(!form.reportValidity())return;running.current=true;setBusy(true);setError('');setMessage('');try{
   const values=new FormData(form),request=selected.request;
   const result=await inspectConnection({source_type:request.source_type,address:request.address,port:request.port,verify_ssl:request.verify_ssl,username:String(values.get('username')),secret:String(values.get('secret')),registration_resume:{source_instance:selected.source_instance,registration_id:selected.registration_id}});
   (form.elements.namedItem('secret') as HTMLInputElement).value='';setToken(result.onboarding_token);
 }catch(value){failure(value);}finally{running.current=false;setBusy(false);}}
 async function confirm(){if(!selected?.request||!token||running.current)return;running.current=true;setBusy(true);setError('');setMessage('');try{
   done(await registerSource({...selected.request,onboarding_token:token}));
 }catch(value){failure(value);setToken('');}finally{running.current=false;setBusy(false);}}
 if(!attempts.length&&!error)return null;
 return <section className="source-panel" aria-label={t('Continue a saved registration','Продолжить сохранённое добавление')}>
 <h2>{t('Unfinished registrations','Незавершённое добавление')}</h2><p>{t('Your saved settings are retained. If access was not stored before interruption, enter it again to continue.','Сохранённые настройки не потеряны. Если данные доступа не были сохранены до прерывания, введите их снова для продолжения.')}</p>
 {error&&<p role="alert">{error}</p>}{message&&<p role="status">{message}</p>}
 {!selected?<ul>{attempts.map(a=><li key={a.registration_id}><button type="button" onClick={()=>{setSelected(a);setError('');setMessage('');setExisting(false);setToken('');}}>{a.request?.name||a.source_instance}</button></li>)}</ul>:<>
 <h3>{selected.request?.name||selected.source_instance}</h3><details><summary>{t('Technical details','Технические сведения')}</summary><code>{selected.source_instance}</code> · <code>{selected.registration_id}</code></details>
 <p>{t('The saved result is checked automatically.','Сохранённый результат проверяется автоматически.')}</p>
 {existing?<Link to={sourcePath(selected.source_instance)}>{t('Open source','Открыть источник')}</Link>:selected.request?<>
 <dl className="source-facts"><div><dt>{t('Address','Адрес')}</dt><dd>{selected.request.address}:{selected.request.port}</dd></div><div><dt>{t('Site','Площадка')}</dt><dd>{selected.request.site_slug}</dd></div><div><dt>{t('Cluster','Кластер')}</dt><dd>{selected.request.cluster_name}</dd></div></dl>
 <details><summary>{t('Exact placement references','Точные ссылки размещения')}</summary><ul>{Object.entries(selected.request.references||{}).map(([kind,row])=><li key={kind}>{kind}: {row.id}</li>)}{Object.entries(selected.request.host_types||{}).map(([host,row])=><li key={host}>{host}: device_type {row.id}</li>)}</ul></details>
 {!token?<form onSubmit={connect} autoComplete="off"><fieldset disabled={busy}><legend>{t('Check source access again','Повторная проверка доступа к источнику')}</legend><CredentialField label={t('Username','Имя пользователя')} name="username" required/><CredentialField label={t('Password','Пароль')} secret name="secret" required autoComplete="new-password"/><button type="submit">{t('Check connection','Проверить подключение')}</button></fieldset></form>:<><p>{t('Access verified. Confirm continuation with the saved parameters. Automatic sync remains off.','Доступ проверен. Подтвердите продолжение с сохранёнными параметрами. Автосинхронизация останется выключенной.')}</p><button type="button" disabled={busy} onClick={()=>void confirm()}>{t('Confirm and continue registration','Подтвердить и продолжить добавление')}</button></>}
 </>:<p>{t('This older attempt has no saved request. Its identity reservation is retained; an administrator must review it before any new registration.','У старой попытки нет сохранённых параметров. Резерв идентичности сохранён; перед новым добавлением администратор должен проверить его.')}</p>}
 <button type="button" disabled={busy} onClick={()=>{setSelected(null);setToken('');setMessage('');setError('');}}>{t('Back to saved attempts','К сохранённым попыткам')}</button>
 </>}{busy&&<p role="status">{t('Operation in progress','Операция выполняется')}</p>}
 </section>;
}
