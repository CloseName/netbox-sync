import {useEffect,useState,type ReactNode,type FormEvent} from 'react';
import {useLanguage} from './ui/language';
import {LanguageControl} from './ui/LanguageControl';
import {ThemeControl} from './ui/ThemeControl';
import {Brand} from './ui/Brand';
export type Principal={principal_id:string;username:string;permissions:string[]};
let installed=false;
export function installAuthBoundary(){
 if(installed)return;installed=true;
 const original=window.fetch.bind(window);
 window.fetch=async(...args)=>{
  const response=await original(...args);
  const target=String(args[0] instanceof Request?args[0].url:args[0]);
  if(target.includes('/api/v1/')&&!target.includes('/api/v1/auth/')&&[401,403,503].includes(response.status)){
   try{const code=(await response.clone().json()).error?.code;
    if(['AUTH_REQUIRED','AUTH_UNAVAILABLE','AUTH_DENIED'].includes(code))window.dispatchEvent(new CustomEvent('netbox-sync.auth',{detail:code}));
   }catch{/* Never interpret remote text as an auth failure. */}
  }
  return response;
 };
}
export async function authRequest(path:string,body?:unknown){
 const response=await fetch('/api/v1/'+path,{method:body===undefined?'GET':'POST',credentials:'same-origin',cache:'no-store',
  signal:AbortSignal.timeout(10000),headers:body===undefined?undefined:{'Content-Type':'application/json','X-NetBox-Sync-CSRF':'same-origin'},
  body:body===undefined?undefined:JSON.stringify(body)});
 let data:any;try{data=await response.json();}catch{throw new Error('AUTH_UNAVAILABLE');}
 if(!response.ok)throw new Error(['AUTH_REQUIRED','AUTH_INVALID','AUTH_RATE_LIMITED','AUTH_DENIED','AUTH_UNAVAILABLE','ENROLLMENT_INVALID','POLICY_CONFLICT','POLICY_HOST_MANAGED','POLICY_INVALID'].includes(data.error?.code)?data.error.code:'AUTH_UNAVAILABLE');
 return data;
}
export function AuthGate({children}:{children:ReactNode}){
 const [lang]=useLanguage(),t=(en:string,ru:string)=>lang==='ru'?ru:en;
 const [principal,setPrincipal]=useState<Principal|null>(null),[state,setState]=useState('loading'),[enroll,setEnroll]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
 async function check(){setState('loading');try{const data=await authRequest('auth/me');if(typeof data.principal_id!=='string'||!Array.isArray(data.permissions))throw new Error('AUTH_UNAVAILABLE');setPrincipal(data);setState('ready');}catch(e){setPrincipal(null);setState(e instanceof Error?e.message:'AUTH_UNAVAILABLE');}}
 useEffect(()=>{void check();const expire=(event:Event)=>{setPrincipal(null);setState((event as CustomEvent).detail);};window.addEventListener('netbox-sync.auth',expire);return()=>window.removeEventListener('netbox-sync.auth',expire);},[]);
 async function submit(event:FormEvent<HTMLFormElement>){
  event.preventDefault();if(busy)return;setBusy(true);setError('');
  const form=event.currentTarget,data=new FormData(form),body={username:String(data.get('username')),password:String(data.get('password')),...(enroll?{invitation:String(data.get('invitation'))}:{})};
  try{await authRequest(enroll?'auth/enroll':'auth/login',body);await check();}catch(e){setError(e instanceof Error?e.message:'AUTH_UNAVAILABLE');}
  finally{form.reset();setBusy(false);}
 }
 if(principal&&state==='ready')return <>{children}<div className="session-bar"><span>{principal.username}</span><button onClick={async()=>{if(busy)return;setBusy(true);try{await authRequest('auth/logout',{});setPrincipal(null);setState('AUTH_REQUIRED');}catch(e){if(e instanceof Error&&e.message==='AUTH_REQUIRED'){setPrincipal(null);setState('AUTH_REQUIRED');}else setError('AUTH_UNAVAILABLE');}finally{setBusy(false);}}} disabled={busy}>{t('Sign out','Выйти')}</button>{error&&<span role="alert">{t('Sign out could not be confirmed. Retry.','Выход не подтверждён. Повторите запрос.')}</span>}</div></>;
 const messages:Record<string,string>={AUTH_INVALID:t('Username or password is incorrect.','Неверное имя пользователя или пароль.'),AUTH_RATE_LIMITED:t('Too many attempts. Wait five minutes.','Слишком много попыток. Подождите пять минут.'),ENROLLMENT_INVALID:t('Invitation is invalid, expired or already used. Contact the host administrator.','Приглашение недействительно, истекло или уже использовано. Обратитесь к администратору сервера.'),AUTH_DENIED:t('Access denied. Contact the administrator.','Недостаточно прав. Обратитесь к администратору.'),AUTH_UNAVAILABLE:t('Authentication service is unavailable. No operation was retried.','Служба входа недоступна. Операции повторно не отправлялись.')};
 return <><header className="app-header"><Brand/><LanguageControl/><ThemeControl language={lang}/></header><main className="auth-panel panel"><h1>{enroll?t('Create administrator','Создать администратора'):t('Sign in','Вход')}</h1>
 {state==='loading'?<p role="status">{t('Checking session…','Проверка сессии…')}</p>:<>
 {state==='AUTH_REQUIRED'&&<p>{t('Sign in to continue. After signing in, operation state will be read from the server. Writes are never retried automatically.','Войдите для продолжения. После входа состояние операций будет загружено с сервера. Записи не повторяются автоматически.')}</p>}
 {(messages[state]||error)&&<p role="alert">{messages[error]??messages[state]??messages.AUTH_UNAVAILABLE}</p>}
 {state==='AUTH_UNAVAILABLE'?<button onClick={()=>void check()}>{t('Retry session check','Повторить проверку сессии')}</button>:<form onSubmit={submit}><fieldset disabled={busy}>
 <label>{t('Username','Имя пользователя')}<input name="username" required minLength={3} maxLength={64} autoComplete="username"/></label>
 <label>{t('Password','Пароль')}<input name="password" type="password" required minLength={enroll?15:1} maxLength={256} autoComplete={enroll?'new-password':'current-password'}/></label>
 {enroll&&<><label>{t('One-time invitation','Одноразовое приглашение')}<input name="invitation" type="password" required autoComplete="off"/></label><p>{t('Obtain a 15-minute invitation from the host administrator. Use a password of at least 15 characters.','Получите у администратора сервера приглашение на 15 минут. Пароль — не менее 15 символов.')}</p></>}
 <button type="submit" className="primary">{busy?t('Waiting for server…','Ожидаем ответа сервера…'):enroll?t('Create administrator','Создать администратора'):t('Sign in','Войти')}</button>
 </fieldset></form>}
 <button disabled={busy} onClick={()=>{setEnroll(!enroll);setError('');}}>{enroll?t('Back to sign in','Вернуться ко входу'):t('I have an administrator invitation','У меня есть приглашение администратора')}</button>
 </>}</main></>;
}
