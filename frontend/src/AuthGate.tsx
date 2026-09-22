import {useFormValidation} from './ui/formValidation';
import {CredentialField} from './components/CredentialField';
import {useEffect,useState,useRef,createContext,useContext,type ReactNode,type FormEvent} from 'react';
import {useLanguage} from './ui/language';
import {LanguageControl} from './ui/LanguageControl';
import {ThemeControl} from './ui/ThemeControl';
import {Brand} from './ui/Brand';
export type Principal={principal_id:string;username:string;permissions:string[];role?:string;provider?:string};
const SessionContext=createContext<{principal:Principal;busy:boolean;error:string;logout:()=>Promise<void>}|null>(null);
export function usePrincipal(){return useContext(SessionContext)?.principal;}
export function usePermission(permission:string){return useContext(SessionContext)?.principal.permissions.includes(permission)??false;}
export function Permission({permission,children}:{permission:string;children:ReactNode}){const can=usePermission(permission),[lang]=useLanguage();return can?<>{children}</>:<p role="status">{lang==='ru'?'Недостаточно прав для этого раздела.':'You do not have permission to open this section.'}</p>;}
export function SessionControls(){
 const value=useContext(SessionContext),[lang]=useLanguage(),[open,setOpen]=useState(false);
 const root=useRef<HTMLDivElement>(null),toggle=useRef<HTMLButtonElement>(null);
 useEffect(()=>{const close=(e:PointerEvent)=>{if(!root.current?.contains(e.target as Node))setOpen(false);};document.addEventListener('pointerdown',close);return()=>document.removeEventListener('pointerdown',close);},[]);
 if(!value)return null;
 return <div className="user-menu" ref={root} onKeyDown={e=>{if(e.key==='Escape'){setOpen(false);toggle.current?.focus();}}} onBlur={e=>{if(!e.currentTarget.contains(e.relatedTarget))setOpen(false);}}>
 <button ref={toggle} aria-label={lang==='ru'?'Меню пользователя':'User menu'} aria-expanded={open} aria-controls="user-options" onClick={()=>setOpen(!open)}><svg width="24" height="24" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="8" r="4"/><path d="M4 22v-3a8 8 0 0 1 16 0v3"/></svg></button>
 {open&&<div id="user-options" className="user-options"><strong>{value.principal.username}</strong><p>{lang==='ru'?({admin:'Администратор',operator:'Оператор',viewer:'Наблюдатель'}[value.principal.role??'admin']):value.principal.role??'admin'}</p><LanguageControl/><ThemeControl language={lang}/>{value.principal.permissions.includes('identity.manage')&&<a href="/settings">{lang==='ru'?'Настройки':'Settings'}</a>}<button onClick={value.logout} disabled={value.busy}>{lang==='ru'?'Выйти':'Sign out'}</button>{value.error&&<p role="alert">{lang==='ru'?'Выход не подтверждён. Повторите запрос.':'Sign out could not be confirmed. Retry.'}</p>}</div>}
 </div>;
}

let installed=false;
export function installAuthBoundary(){
 if(installed)return;installed=true;
 const original=window.fetch.bind(window);
 window.fetch=async(...args)=>{
  const response=await original(...args);
  const target=String(args[0] instanceof Request?args[0].url:args[0]);
  if(target.includes('/api/v1/')&&!target.includes('/api/v1/auth/')&&[401,403,503].includes(response.status)){
   try{const code=(await response.clone().json()).error?.code;
    if(['AUTH_REQUIRED','AUTH_REAUTH_REQUIRED','AUTH_UNAVAILABLE'].includes(code))window.dispatchEvent(new CustomEvent('netbox-sync.auth',{detail:code}));
   }catch{/* Never interpret remote text as an auth failure. */}
  }
  return response;
 };
}
export async function authRequest(path:string,body?:unknown){
 const response=await fetch('/api/v1/'+path,{method:body===undefined?'GET':'POST',credentials:'same-origin',cache:'no-store',
  signal:AbortSignal.timeout(60000),headers:body===undefined?undefined:{'Content-Type':'application/json','X-NetBox-Sync-CSRF':'same-origin'},
  body:body===undefined?undefined:JSON.stringify(body)});
 let data:any;try{data=await response.json();}catch{throw new Error('AUTH_UNAVAILABLE');}
 if(!response.ok)throw new Error(['API_VALIDATION_FAILED','AUTH_REAUTH_REQUIRED','AUTH_REQUIRED','AUTH_INVALID','AUTH_RATE_LIMITED','AUTH_DENIED','AUTH_UNAVAILABLE','ENROLLMENT_INVALID','POLICY_CONFLICT','POLICY_HOST_MANAGED','POLICY_INVALID','LDAP_INVALID','LDAP_TLS_FAILED','LDAP_UNAVAILABLE','LDAP_BIND_FAILED','LDAP_ACCESS_DENIED','LDAP_CONFLICT'].includes(data.error?.code)?data.error.code:'AUTH_UNAVAILABLE');
 return data;
}
export function AuthGate({children}:{children:ReactNode}){
 const [lang]=useLanguage(),t=(en:string,ru:string)=>lang==='ru'?ru:en;
 const validation=useFormValidation(lang);
 const [reauth,setReauth]=useState(false),[reauthBusy,setReauthBusy]=useState(false),[reauthError,setReauthError]=useState(''),[confirmed,setConfirmed]=useState(false);
 const [principal,setPrincipal]=useState<Principal|null>(null),[state,setState]=useState('loading'),[enroll,setEnroll]=useState(new URLSearchParams(window.location.search).get('recovery')==='1'),[available,setAvailable]=useState(false),[visible,setVisible]=useState(false),[unavailable,setUnavailable]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
 async function check(){setState('loading');try{const data=await authRequest('auth/me');if(typeof data.principal_id!=='string'||!Array.isArray(data.permissions))throw new Error('AUTH_UNAVAILABLE');setPrincipal(data);setState('ready');}catch(e){const code=e instanceof Error?e.message:'AUTH_UNAVAILABLE';if(code==='AUTH_REQUIRED')setPrincipal(null);setState(code);}}
 useEffect(()=>{void check();void authRequest('auth/status').then(data=>setAvailable(data.enrollment_available===true)).catch(()=>setAvailable(false));const expire=(event:Event)=>{const code=(event as CustomEvent).detail;if(code==='AUTH_REQUIRED'){setPrincipal(null);setState(code);setReauth(false);}else if(code==='AUTH_REAUTH_REQUIRED'){setReauth(true);setConfirmed(false);setReauthError('');}else setUnavailable(true);};window.addEventListener('netbox-sync.auth',expire);return()=>window.removeEventListener('netbox-sync.auth',expire);},[]);
 async function submit(event:FormEvent<HTMLFormElement>){
  event.preventDefault();if(busy||!validation.validate(event.currentTarget))return;setBusy(true);setError('');
  const form=event.currentTarget,data=new FormData(form),body={username:String(data.get('username')),password:String(data.get('password')),...(enroll?{invitation:String(data.get('invitation'))}:{})};
  try{await authRequest(enroll?'auth/enroll':'auth/login',body);setAvailable(false);setEnroll(false);setUnavailable(false);await check();}catch(e){setError(e instanceof Error?e.message:'AUTH_UNAVAILABLE');}
  finally{const input=form.elements.namedItem('password') as HTMLInputElement|null;if(input)input.value='';setBusy(false);}
 }
 async function confirmIdentity(event:FormEvent<HTMLFormElement>){
  event.preventDefault();if(reauthBusy)return;
  const form=event.currentTarget,input=form.elements.namedItem('reauth-password') as HTMLInputElement;
  const password=input.value;input.value='';setReauthBusy(true);setReauthError('');
  try{await authRequest('auth/reauthenticate',{password});setReauth(false);setConfirmed(true);}
  catch(e){const code=e instanceof Error?e.message:'AUTH_UNAVAILABLE';if(code==='AUTH_REQUIRED'){setPrincipal(null);setState(code);setReauth(false);}else setReauthError(code);}
  finally{setReauthBusy(false);}
 }
 async function logout(){if(busy)return;setBusy(true);try{await authRequest('auth/logout',{});setPrincipal(null);setState('AUTH_REQUIRED');}catch(e){if(e instanceof Error&&e.message==='AUTH_REQUIRED'){setPrincipal(null);setState('AUTH_REQUIRED');}else setError('AUTH_UNAVAILABLE');}finally{setBusy(false);}}
 if(principal)return <SessionContext.Provider value={{principal,busy,error,logout}}>
 {reauth&&<section className="panel" role="region" aria-label={t('Confirm your identity','Подтвердите личность')}><h2>{t('Confirm your identity','Подтвердите личность')}</h2><p>{t('Your session is still active. Confirm your password for this protected action. Your draft stays open; no action will be retried automatically.','Сессия действует. Подтвердите пароль для защищённого действия. Форма остаётся открытой; действие не будет повторено автоматически.')}</p><p>{principal.username}</p>
 {reauthError&&<p role="alert">{reauthError==='AUTH_INVALID'?t('Password is incorrect.','Неверный пароль.'):reauthError==='AUTH_RATE_LIMITED'?t('Too many attempts. Wait five minutes.','Слишком много попыток. Подождите пять минут.'):t('Identity confirmation is unavailable. No action was performed.','Подтверждение личности недоступно. Действие не выполнено.')}</p>}
 <form onSubmit={confirmIdentity}><label>{t('Your account password','Пароль вашей учётной записи')}<input name="reauth-password" type="password" autoComplete="current-password" required maxLength={256} disabled={reauthBusy}/></label><button type="submit" disabled={reauthBusy}>{t('Confirm identity','Подтвердить личность')}</button><button type="button" disabled={reauthBusy} onClick={()=>setReauth(false)}>{t('Cancel','Отмена')}</button></form></section>}
 {confirmed&&<p role="status">{t('Identity confirmed. Review and repeat the action explicitly.','Личность подтверждена. Проверьте данные и повторите действие явно.')}</p>}
 {unavailable&&<div className="auth-warning" role="alert">{t('Authorization is temporarily unavailable. Your draft remains open; server authorization is still required for every operation.','Проверка доступа временно недоступна. Черновик сохранён; каждая операция по-прежнему требует разрешения сервера.')}<button onClick={async()=>{try{const data=await authRequest('auth/me');setPrincipal(data);setUnavailable(false);}catch(e){if(e instanceof Error&&e.message==='AUTH_REQUIRED'){setPrincipal(null);setState('AUTH_REQUIRED');}}}}>{t('Check session','Проверить сессию')}</button></div>}{children}</SessionContext.Provider>;
 const messages:Record<string,string>={AUTH_INVALID:t('Username or password is incorrect.','Неверный логин или пароль'),AUTH_RATE_LIMITED:t('Too many attempts. Wait five minutes.','Слишком много попыток. Подождите пять минут.'),ENROLLMENT_INVALID:t('Invitation is invalid, expired or already used. Contact the host administrator.','Приглашение недействительно, истекло или уже использовано. Обратитесь к администратору сервера.'),AUTH_DENIED:t('Access denied. Contact the administrator.','Недостаточно прав. Обратитесь к администратору.'),LDAP_UNAVAILABLE:t('Directory is unavailable. Local emergency administrator login remains available.','Каталог недоступен. Аварийный локальный вход остаётся доступен.'),LDAP_TLS_FAILED:t('Directory certificate could not be verified. Contact the administrator.','Сертификат каталога не прошёл проверку. Обратитесь к администратору.'),LDAP_BIND_FAILED:t('Directory access is unavailable. Contact the administrator.','Доступ к каталогу недоступен. Обратитесь к администратору.'),AUTH_UNAVAILABLE:t('Authentication service is unavailable. No operation was retried.','Служба входа недоступна. Операции повторно не отправлялись.')};
 return <><header className="app-header"><Brand/><LanguageControl/><ThemeControl language={lang}/></header><main className="auth-panel panel"><h1>{enroll?t('Create administrator','Создать администратора'):t('Sign in','Вход')}</h1>
 {state==='loading'?<p role="status">{t('Checking session…','Проверка сессии…')}</p>:<>
 {state==='AUTH_REQUIRED'&&<p>{t('Sign in to continue.','Войдите для продолжения.')}</p>}
 {(messages[state]||error)&&<p className="auth-error" role="alert">{messages[error]??messages[state]??messages.AUTH_UNAVAILABLE}</p>}
 {state==='AUTH_UNAVAILABLE'&&<button onClick={()=>void check()}>{t('Retry session check','Повторить проверку сессии')}</button>}{validation.summary}<form noValidate onSubmit={submit}><fieldset disabled={busy}>

 <CredentialField label={t('Username','Имя пользователя')} name="username" required minLength={3} maxLength={64} autoComplete="username"/>
 <CredentialField label={t('Password','Пароль')} name="password" secret visible={visible} onVisibilityChange={setVisible} required minLength={enroll?15:1} maxLength={256} autoComplete={enroll?'new-password':'current-password'}/>
 {enroll&&<><label>{t('One-time invitation','Одноразовое приглашение')}<input name="invitation" type="password" required autoComplete="off"/></label><p>{t('Obtain a 15-minute invitation from the host administrator. Use a password of at least 15 characters.','Получите у администратора сервера приглашение на 15 минут. Пароль — не менее 15 символов.')}</p></>}
 <button type="submit" className="primary">{busy?t('Waiting for server…','Ожидаем ответа сервера…'):enroll?t('Create administrator','Создать администратора'):t('Sign in','Войти')}</button>
 </fieldset></form>
 {(available||enroll)&&<button disabled={busy} onClick={()=>{setEnroll(!enroll);setError('');}}>{enroll?t('Back to sign in','Вернуться ко входу'):t('I have an administrator invitation','У меня есть приглашение администратора')}</button>}
 </>}</main></>;
}
