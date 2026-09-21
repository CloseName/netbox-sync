import {authRequest,usePermission} from '../AuthGate';
import {useTeams} from '../components/SourceTeams';
import {RegistrationFailure} from '../api/onboarding';
import {updateTokenUser} from '../ui/proxmoxToken';
import {SourcePlacement} from '../components/SourcePlacement';
import type {Placement} from '../components/SourcePlacement';
import type {SourcePreview} from '../api/onboarding';
import {DestinationPermission} from "../components/DestinationPermission";
import {OperationFeedback} from "../ui/OperationFeedback";
import {tr} from "../ui/i18n";
import {useLanguage} from "../ui/language";
import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import {
  cancelOnboarding,
  registerSource,
  SourceIdReservedError,
  SourceConnectionError,
  connectionMessages,
  inspectConnection,
  reviewPlacement,
  checkDestination,
  CatalogFailure,
} from "../api/onboarding";
import { SourceAccessHelp } from "../components/SourceAccessHelp";
import type { Source } from "../api/sources";

import { Link, useNavigate, useSearchParams, useBlocker } from "react-router-dom";
import { PageHeader } from "../ui/primitives";
import { sourcePath } from "../ui/routes";
// In-memory non-secret draft survives an auth-boundary remount; no token or password.
let remembered: {type:'proxmox'|'esxi';connection:{address:string;verify_ssl:boolean;port:number};draft:Placement;preview:SourcePreview|null;uncertain:boolean}|null=null;
export function AddSourcePage() {
  const [language] = useLanguage();
  const t = (en: string, ru: string) => language === "ru" ? ru : en;
  const [type, setType] = useState<"proxmox" | "esxi">(remembered?.type??"proxmox");
  const [connection, setConnection] = useState(remembered?.connection??{
    address: "",
    port: 8006,
    verify_ssl: true,
  });
  const [token, setToken] = useState("");
  const [preview,setPreview]=useState<SourcePreview|null>(remembered?.preview??null);
  const [review,setReview]=useState(false);
  const [draft,setDraft]=useState<Placement>(remembered?.draft??{source_instance:'',name:'',interval:600,references:{},host_types:{}});
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false); const [started,setStarted]=useState(0);
  const [error, setError] = useState("");
  const [notice,setNotice]=useState('');
  const [connectionCode,setConnectionCode]=useState<keyof typeof connectionMessages|null>(null);
  const [identity,setIdentity]=useState({user:'',token:'',edited:false,parsed:false});
  const [expiresAt,setExpiresAt]=useState<number|null>(null);
  const [uncertain,setUncertain]=useState(remembered?.uncertain??false);
  const [reconciled,setReconciled]=useState(false);
  const [created, setCreated] = useState<Source | null>(null);

  const navigate=useNavigate(),[params,setParams]=useSearchParams();
  const canPolicy=usePermission('policy.write'), canAssignTeam=usePermission('source.configure');
  const teams=useTeams(),[team,setTeam]=useState(''),[teamSearch,setTeamSearch]=useState('');
  const [teamUnconfirmed,setTeamUnconfirmed]=useState(false);
  const [showSecret,setShowSecret]=useState(false);
  const [hasSecret,setHasSecret]=useState(false);
  const mounted=useRef(true);
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
  const requested=Number(params.get('step')||1);
  const step=Math.min([1,2,3].includes(requested)?requested:1, token?(review?3:2):1);
  const dirty=!!(connection.address||identity.user||identity.token||hasSecret||draft.name);
  const blocker=useBlocker(({nextLocation})=>dirty&&!created&&nextLocation.pathname!=='/sources/add');
  const exitDialog=useRef<HTMLDialogElement>(null);
  useEffect(()=>{if(blocker.state==='blocked')exitDialog.current?.showModal();else exitDialog.current?.close();},[blocker.state]);
  useEffect(()=>{const leave=(event:BeforeUnloadEvent)=>{if(dirty&&!created){event.preventDefault();event.returnValue='';}};window.addEventListener('beforeunload',leave);return()=>window.removeEventListener('beforeunload',leave);},[dirty,created]);
  const go=(next:number)=>setParams({step:String(next)});
  function invalidate(){if(token)void cancelOnboarding(token).catch(()=>{});setToken('');setReview(false);setExpiresAt(null);}
  useEffect(()=>{if(created){remembered=null;navigate('/sources',{replace:true,state:{addedSource:{name:created.name,id:created.source_instance,teamUnconfirmed}}});}},[created,navigate,teamUnconfirmed]);
  useEffect(()=>{remembered=created?null:{type,connection,draft,preview,uncertain};},[type,connection,draft,preview,created,uncertain]);
  const workspace = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!error && !token && !created) return;
    const target = workspace.current?.querySelector<HTMLElement>(
      error ? '[role="alert"]' : created ? "h1" : "form h2, form legend",
    );
    if (target) {
      target.tabIndex = -1;
      target.focus();
    }
  }, [error, token, created, step]);
  async function checkAddress(){
    if(inFlight.current)return;inFlight.current=true;setBusy(true);setError('');setNotice('');setConnectionCode(null);
    try{await checkDestination({source_type:type,address:connection.address,port:connection.port});setNotice(t('Address allowed by current DNS and destination policy. Authentication is not checked; the connection test rechecks the address.','Адрес разрешён текущими DNS и политикой назначений. Вход не проверен; проверка подключения повторно проверит адрес.'));}
    catch(failure){if(failure instanceof SourceConnectionError)setConnectionCode(failure.code);setError(failure instanceof SourceConnectionError?connectionMessages[failure.code][language==='ru'?1:0]:t('Address could not be checked. No credentials were sent.','Адрес не удалось проверить. Учётные данные не отправлялись.'));}
    finally{inFlight.current=false;setBusy(false);}
  }

  async function test(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (inFlight.current) return;
    if(token){go(2);return;}
    inFlight.current=true; setStarted(Date.now());
    const form = event.currentTarget;
    const data = new FormData(form);
    setBusy(true);
    setError(""); setConnectionCode(null);
    try {
      const result = await inspectConnection({
        source_type: type,
        ...connection,
        username: String(data.get("username")),
        secret: String(data.get("secret")),
        ...(type === "proxmox"
          ? { token_id: String(data.get("token_id")) }
          : {}),
      });
      if(!mounted.current){void cancelOnboarding(result.onboarding_token).catch(()=>{});return;}
      const secret=form.elements.namedItem('secret') as HTMLInputElement|null;if(secret)secret.value='';setHasSecret(false);setShowSecret(false);
      go(2);
      setExpiresAt(Number.isFinite(result.expires_in_seconds)?Date.now()+result.expires_in_seconds!*1000:null);setToken(result.onboarding_token);setPreview(result.preview);setReview(false);
      setDraft(d=>({...d,source_instance:d.source_instance||result.suggested_source_instance,name:d.name||result.preview.name||connection.address,host_types:Object.fromEntries(Object.entries(d.host_types).filter(([id])=>result.preview.hosts.some(h=>h.id===id&&preview?.hosts.some(old=>old.id===id&&old.model===h.model&&old.manufacturer===h.manufacturer))))}));
    } catch (failure) {
      if(failure instanceof SourceConnectionError)setConnectionCode(failure.code);
      setError(
        failure instanceof SourceConnectionError ? connectionMessages[failure.code][language === 'ru' ? 1 : 0] :
        t("Connection check did not complete. Your fields are retained; nothing was registered.", "Проверка подключения не завершена. Поля сохранены; источник не зарегистрирован."),
      );
    } finally {
      inFlight.current=false; setBusy(false);
    }
  }

  async function reviewRegistration(){
    if(inFlight.current)return;
    const cluster=draft.references.cluster,site=draft.references.site,kind=draft.references.cluster_type;
    if(!draft.create_cluster&&cluster?.name!==draft.name.trim()){setError(t('Choose a compatible cluster with the same name as this source.','Выберите совместимый кластер с тем же именем, что у источника.'));return;}
    if(!draft.create_cluster&&(cluster?.scope_type!=='dcim.site'||cluster.scope_id!==site?.id||cluster.type?.id!==kind?.id)){
      setError(t('Cluster: choose the selected site scope and cluster type.','Кластер: выберите привязку к выбранной площадке и соответствующий тип кластера.'));return;
    }
    inFlight.current=true;setBusy(true);setError('');
    try{await reviewPlacement(token,draft.references,draft.host_types,!!draft.create_cluster);setReview(true);go(3);}
    catch(failure){if(failure instanceof RegistrationFailure&&['ONBOARDING_TOKEN_INVALID','PROBE_RECEIPT_INVALID'].includes(failure.code)){invalidate();go(1);setError(t('The connection check expired or is no longer valid. Re-enter the secret and continue; your placement is retained.','Проверка подключения истекла или больше не действует. Введите секрет и продолжите; размещение сохранено.'));return;}setError(failure instanceof CatalogFailure&&failure.code==='CATALOG_CLUSTER_SCOPE_MISMATCH'?t('Cluster: its site or type changed. Select a compatible cluster.','Кластер: площадка или тип изменились. Выберите совместимый кластер.'):t('Placement could not be verified. Your selections are retained.','Размещение не удалось проверить. Ваш выбор сохранён.'));}
    finally{inFlight.current=false;setBusy(false);}
  }

  async function register(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (inFlight.current) return;
    if (uncertain || !review || step!==3) return;
    inFlight.current=true; setStarted(Date.now());
    let selectionRejected=false;
    setBusy(true);
    setError(""); setConnectionCode(null);
    try {
      const refs=draft.references;const firstType=Object.values(draft.host_types)[0];
      const metadata={source_instance:draft.source_instance,name:draft.name,site_slug:refs.site.slug,
        cluster_name:draft.create_cluster?draft.name:refs.cluster.name,platform_slug:refs.platform.slug,device_role_slug:refs.device_role.slug,
        device_type_slug:firstType.slug,cluster_type_slug:refs.cluster_type.slug,references:refs,host_types:draft.host_types};
      const result = await registerSource({
        ...metadata,
        create_cluster:!!draft.create_cluster,registration_id:draft.registration_id,
        source_type: type,
        ...connection,
        onboarding_token: token,
        sync_interval_seconds: 600,
        confirm_sync_disabled: true,
      });
      if(team&&canAssignTeam&&teams.data){try{await authRequest('teams',{operation:'assign',revision:teams.data.revision,source_instance:result.source_instance,team_id:team});}catch{setTeamUnconfirmed(true);}}
      setCreated(result);
    } catch (failure) {
      if(failure instanceof CatalogFailure){selectionRejected=true;setReview(false);}
      if(failure instanceof RegistrationFailure&&failure.uncertain){selectionRejected=true;setUncertain(true);setReconciled(false);}

      setError(
        failure instanceof RegistrationFailure?failure.code==='REGISTRATION_CLUSTER_RETAINED'?t('The cluster was created, but adding the source is not confirmed. Check the saved source before retrying; the cluster is retained.','Кластер создан, но добавление источника не подтверждено. Перед повтором проверьте сохранённый источник; кластер оставлен.'):failure.uncertain?t('The registration outcome is unknown. Check server state before any further action. Your choices are retained.','Результат регистрации неизвестен. Сначала сверьте состояние сервера. Ваш выбор сохранён.'):t('The connection check or session is no longer valid. Sign in if needed, re-enter credentials and repeat the check; your placement choices are retained.','Проверка подключения или сеанс больше не действуют. При необходимости войдите, повторно введите данные доступа и выполните проверку; выбранное размещение сохранено.'):
        failure instanceof CatalogFailure&&failure.code==='CATALOG_PERMISSION_DENIED'?t('NetBox refused the required permission. Ask an administrator to check the configured NetBox access; no source was registered.','NetBox отказал в необходимом праве. Попросите администратора проверить настроенный доступ к NetBox; источник не зарегистрирован.'):
        failure instanceof CatalogFailure?t('NetBox selection changed or could not be verified. Refresh the lists and review the site, cluster and host device types; nothing was registered.','Выбор NetBox изменился или не прошёл проверку. Обновите списки, проверьте площадку, кластер и типы устройств хостов; источник не зарегистрирован.'):
        failure instanceof SourceIdReservedError ? failure.message :
        "Registration failed or outcome is uncertain. Ask the operator before retrying.",
      );
    } finally {
      if(!selectionRejected)setToken("");
      inFlight.current=false; setBusy(false);
    }
  }

  return (
    <main className="add-source-workspace" ref={workspace}>
      <PageHeader
        title={tr("Add source")}
        description={t('Connect the server and choose where to place its objects. Automatic synchronization stays off.','Подключите сервер и выберите размещение его объектов. Автоматическая синхронизация останется выключенной.')}
      />
      <nav className="wizard-steps" aria-label={t('Source setup steps','Шаги добавления источника')}>
        {[t('Connection','Подключение'),t('Source settings','Настройки источника'),t('Review and add','Проверка и добавление')].map((label,i)=><button type="button" key={i} aria-current={step===i+1?'step':undefined} disabled={busy||i+1>(token?(review?3:2):1)} onClick={()=>go(i+1)}><span>{i+1}</span>{label}</button>)}
      </nav>
      <dialog ref={exitDialog} onCancel={event=>{event.preventDefault();if(blocker.state==='blocked')blocker.reset();}}>
        <h2>{t('Your entered data will be lost','Введённые данные будут потеряны')}</h2>
        <div className="page-actions"><button autoFocus type="button" onClick={()=>{if(blocker.state==='blocked')blocker.reset();}}>{t('Stay','Остаться')}</button><button type="button" onClick={()=>{remembered=null;if(token)void cancelOnboarding(token).catch(()=>{});if(blocker.state==='blocked')blocker.proceed();}}>{t('Leave','Выйти')}</button></div>
      </dialog>
      {uncertain&&<section className="source-panel"><p>{t('No registration request will be retried automatically.','Запрос регистрации не будет повторён автоматически.')}</p><button type="button" disabled={busy} onClick={async()=>{
        setBusy(true);try{const response=await fetch('/api/v1/sources/'+encodeURIComponent(draft.source_instance),{cache:'no-store',signal:AbortSignal.timeout(10000)});
          if(response.status===404&&draft.create_cluster&&draft.registration_id){
            const checked=await fetch('/api/v1/sources/registration-status',{method:'POST',headers:{'Content-Type':'application/json','X-NetBox-Sync-CSRF':'same-origin'},body:JSON.stringify({source_instance:draft.source_instance,registration_id:draft.registration_id}),signal:AbortSignal.timeout(40000)});
            if(!checked.ok)throw new Error();const result=await checked.json();
            setError(result.status==='CREATED'?t('The cluster is saved; the source is not registered. Review the existing cluster before starting a new connection check.','Кластер сохранён; источник не зарегистрирован. Проверьте существующий кластер перед новой проверкой подключения.'):result.status==='EXISTS_REVIEW_REQUIRED'?t('A matching cluster exists, but ownership of this write is unconfirmed. Ask an administrator to review it before continuing.','Совпадающий кластер существует, но результат этой записи не подтверждён. Обратитесь к администратору для проверки перед продолжением.'):t('The result remains unconfirmed. No creation request was repeated.','Результат остаётся неподтверждённым. Запрос создания не повторялся.'));
            setReconciled(false);return;
          }
          setReconciled(response.ok);setError(response.ok?t('A source with this ID exists. Open it and verify the saved configuration.','Источник с этим ID существует. Откройте его и проверьте сохранённую конфигурацию.'):t('The outcome is still unconfirmed. Ask the operator to inspect the operation before retrying.','Результат пока не подтверждён. Перед повтором оператор должен проверить состояние операции.'));
        }catch{setError(t('Could not check server state. No registration was repeated.','Не удалось сверить состояние сервера. Регистрация не повторялась.'));}finally{setBusy(false);}
      }}>{t('Check server state','Сверить состояние сервера')}</button>{reconciled&&<Link to={sourcePath(draft.source_instance)}>{t('Open source for review','Открыть источник для проверки')}</Link>}</section>}
      {step>1&&expiresAt&&<p className="muted">{t('Connection check valid until: ','Проверка подключения действует до: ')}{new Date(expiresAt).toLocaleTimeString(language)}</p>}
      {notice&&<p role="status">{notice}</p>}
      {error && (
        <p role="alert" tabIndex={-1} className="source-error">
          {connectionCode?connectionMessages[connectionCode][language==='ru'?1:0]:tr(error)}
        </p>
      )}
      {canPolicy&&connectionCode==='SOURCE_DESTINATION_DENIED'&&<DestinationPermission host={connection.address} done={()=>{setConnectionCode(null);setError('');setNotice(t('Destination allowed. Test the connection.','Назначение разрешено. Проверьте подключение.'));}}/>}
      {busy && <OperationFeedback operation={token?t('Registering source','Регистрация источника'):t('Checking connection and reading host information','Проверяем подключение и получаем сведения о хостах')} phase="sending" started={started}/>}
      {step===1 ? (
        <form onSubmit={test} onChangeCapture={invalidate} className="source-form wizard-form" autoComplete="off">
          <fieldset disabled={busy} aria-busy={busy}>
            <legend>{tr("Connection")}{" "}</legend>
            <p>{t('Prepare the server address and a dedicated service account.','Подготовьте адрес сервера и отдельную сервисную учётную запись.')}</p>
            <SourceAccessHelp provider={type} language={language}/>
            <div className="form-grid">
              <label>
                {tr("Source type")}{" "}<select
                  value={type}
                  onChange={(event) => {
                    const nextType = event.target.value as typeof type;
                    event.currentTarget.form?.reset();setHasSecret(false);setShowSecret(false);
                    setType(nextType);setIdentity({user:'',token:'',edited:false,parsed:false});
                    setDraft(d=>({...d,references:Object.fromEntries(d.references.site?[['site',d.references.site]]:[]),host_types:{}}));
                    setConnection(c=>({...c,port:nextType==='proxmox'?8006:443}));
                  }}
                >
                  <option value="proxmox">{tr("Proxmox VE")}{" "}</option>
                  <option value="esxi">{tr("VMware ESXi")}{" "}</option>
                </select>
              </label>
              <label>
                {tr("Hostname or IPv4 address")}{" "}<input
                  required
                  value={connection.address}
                  pattern="[^/@%?#:\\\\ ]+"
                  onChange={(event) =>
                    setConnection({
                      ...connection,
                      address: event.target.value,
                    })
                  }
                />
              </label>
            </div>
            <label>{t('HTTPS port', 'Порт HTTPS')} *
              <input type="number" min={1} max={65535} step={1} required value={connection.port || ''}
                onChange={event=>setConnection({...connection,port:Number(event.target.value)})}/>
              <span className="muted">{t('Used for connection checks and synchronization. No automatic port fallback.', 'Используется для проверки и синхронизации. Автоматического перебора портов нет.')}</span>
            </label>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={connection.verify_ssl}
                onChange={(event) =>
                  setConnection({
                    ...connection,
                    verify_ssl: event.target.checked,
                  })
                }
              />{" "}
              {tr("Verify TLS certificate")}{" "}</label>
            <details><summary>{t("Connection options","Параметры подключения")}</summary><button type="button" disabled={busy||!connection.address} onClick={()=>void checkAddress()}>{t('Check address without credentials','Проверить адрес без учётных данных')}</button>
            {canPolicy&&connection.address&&<details><summary>{t('Review destination permission before entering credentials','Проверить разрешение адреса до ввода учётных данных')}</summary><DestinationPermission host={connection.address} done={()=>{setError('');setConnectionCode(null);setNotice(t('Destination allowed. Test the connection.','Назначение разрешено. Проверьте подключение.'));}}/></details>}
            <p className="muted">{t('Use the certificate hostname and a complete chain from a CA trusted by the standard worker image. Ask the source operator to correct the certificate or hostname. A separate provider CA upload is not supported yet; the optional NetBox CA does not establish provider trust.','Используйте имя из сертификата и полную цепочку CA, которому доверяет штатный образ обработчиков. Исправить сертификат или имя должен оператор источника. Отдельная загрузка CA источника пока не поддерживается; настройка CA для NetBox не распространяется на источники.')}</p>
            </details><h2>{t('Source credentials', 'Доступ к источнику')}</h2>
            <p className="muted">
              {t('Credentials apply only to this source. The secret is cleared after a successful check; the username is retained.', 'Данные доступа относятся только к этому источнику. После успешной проверки секрет удаляется, имя пользователя сохраняется.')}
            </p>
            <div className="form-grid">
              <label>
                {type === "proxmox" ? tr("Token user (user@realm)") : tr("Username")}
                <input autoComplete="section-source-access username" name="username" required aria-describedby="source-user-hint" value={identity.user} onChange={e=>setIdentity(old=>type==='proxmox'?updateTokenUser(old,e.target.value):{...old,user:e.target.value})} />
                <small id="source-user-hint">{type === 'proxmox' ? t('Include your actual realm, e.g. netbox-sync@pve. You can paste user@realm!token here; the two fields are separated explicitly.', 'Укажите свой realm, например netbox-sync@pve. Здесь можно вставить user@realm!token — идентификатор будет разделён на два поля.') : t('Local ESXi user, e.g. netbox-sync.', 'Локальный пользователь ESXi, например netbox-sync.')}</small>
              </label>
              {type === "proxmox" && (
                <label>
                  {tr("Token name (without user prefix)")}{" "}<input name="token_id" required aria-describedby="source-token-hint" value={identity.token} onChange={e=>setIdentity(old=>({...old,token:e.target.value,edited:true,parsed:false}))} />
                  <small id="source-token-hint">{identity.parsed?t('Full identifier split into user and token name. Review both fields.', 'Полный идентификатор разделён на пользователя и имя токена. Проверьте оба поля.'):t('Suggested from the user name. Editable: enter your actual token name if different.', 'Предлагается по имени пользователя. Можно изменить: укажите фактическое имя токена, если оно отличается.')}</small>
                </label>
              )}
              <label>
                {type === "proxmox" ? tr("Token secret") : tr("Password")}
                <input
                  name="secret"
                  onChange={event=>setHasSecret(!!event.target.value)}
                  type={showSecret?"text":"password"}
                  required={!token}
                  aria-describedby="source-secret-hint"
                  autoComplete="section-source-access new-password"
                />
                <button type="button" aria-pressed={showSecret} onClick={()=>setShowSecret(value=>!value)}>{type==='proxmox'?(showSecret?t('Hide token secret','Скрыть секрет токена'):t('Show token secret','Показать секрет токена')):(showSecret?t('Hide password','Скрыть пароль'):t('Show password','Показать пароль'))}</button>
                <small id="source-secret-hint">{type === 'proxmox' ? t('The value saved at token issuance; not the user password.', 'Значение, сохранённое при выдаче токена; не пароль пользователя.') : t('Separate password for this host’s account.', 'Отдельный пароль пользователя на этом хосте.')}</small>
              </label>
            </div>
            <details className="source-access-help"><summary>{t('If access is blocked by policy','Если доступ запрещён политикой')}</summary><p>{t('The server checks every resolved address before authentication. A policy denial is not a password error. Existing deployment restrictions remain in force; Test Connection does not change them.', 'Сервер проверяет все полученные адреса до входа. Запрет политики не означает ошибку пароля. Действующие ограничения установки сохраняются; проверка подключения их не изменяет.')}</p><p>{t('For a denied public destination, use the separate permission action below the error. The server checks administrator permissions; host-managed limits may require a one-time transition by the host operator.', 'Для запрещённого публичного назначения используйте отдельное разрешение под сообщением об ошибке. Сервер проверяет права администратора; ограничения сервера могут требовать однократного перехода, выполняемого его оператором.')}</p></details>
            <button className="primary" disabled={busy}>
              {busy ? tr("Testing…") : t("Continue","Продолжить")}
            </button>
          </fieldset>
        </form>
      ) : (
        <form onSubmit={register} className="source-form wizard-form">
          {preview&&step===2&&<fieldset disabled={busy}><SourcePlacement wizard preview={preview} draft={draft} setDraft={value=>{setDraft(value);setReview(false);}} language={language}/>
          <section className="wizard-section"><h2>{t('Team','Команда')}</h2>{canAssignTeam?<>
            {teams.error&&<p role="alert">{t('Teams could not be loaded. You can add the source without a team.','Не удалось загрузить команды. Можно добавить источник без команды.')}</p>}
            <label>{t('Search teams','Поиск команд')}<input type="search" value={teamSearch} onChange={e=>setTeamSearch(e.target.value)}/></label>
            <label>{t('Assigned team','Назначенная команда')}<select value={team} onChange={e=>setTeam(e.target.value)}><option value="">{t('No team','Без команды')}</option>{Object.values(teams.data?.teams??{}).filter(row=>row.id===team||row.name.toLowerCase().includes(teamSearch.toLowerCase())).map(row=><option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
          </>:<p>{t('An administrator will assign a team','Команду назначит администратор')}</p>}</section>
          {Object.keys(draft.references).length!==(draft.create_cluster?4:5)||preview.hosts.some(h=>!draft.host_types[h.id])?<p role="status">{t('Choose the required placement objects and a device type for each host to continue.','Для продолжения выберите объекты размещения и тип устройства для каждого хоста.')}</p>:null}
          <div className="page-actions"><button type="button" disabled={busy} onClick={()=>go(1)}>{t("Back","Назад")}</button><button type="button" className="primary" disabled={Object.keys(draft.references).length!==(draft.create_cluster?4:5)||preview.hosts.some(h=>!draft.host_types[h.id])||!draft.name.trim()} onClick={event=>{if(event.currentTarget.form?.reportValidity())void reviewRegistration();}}>{t('Continue','Продолжить')}</button></div></fieldset>}
          {step===3&&<fieldset disabled={busy}><legend>{t('Review and add','Проверка и добавление')}</legend>
          <h2>{draft.name}</h2><p>{connection.address} · {type==='esxi'?'VMware ESXi':'Proxmox VE'}</p><dl className="source-facts">{Object.entries(draft.references).map(([kind,row])=><div key={kind}><dt>{({site:t('Site','Площадка'),cluster:t('Cluster','Кластер'),platform:t('Platform','Платформа'),device_role:t('Device role','Роль устройства'),cluster_type:t('Cluster type','Тип кластера')} as Record<string,string>)[kind]}</dt><dd>{row.name}</dd></div>)}</dl>
          {preview?.hosts.map(h=><p key={h.id}>{h.name||h.id} → {draft.host_types[h.id]?.manufacturer?.name} / {draft.host_types[h.id]?.name}</p>)}
          <p>{t('Team','Команда')}: {team?teams.data?.teams[team]?.name:t('No team','Без команды')}</p>
          {draft.create_cluster&&<p><strong>{t('Will create cluster: ','Будет создан кластер: ')}{draft.name}</strong></p>}
          <p>{t('The source and protected credentials will be saved. NetBox infrastructure objects and automatic synchronization remain unchanged.','Сохранятся источник и защищённые данные доступа. Инфраструктурные объекты NetBox и автоматическая синхронизация не изменяются.')}</p>

            <p>{t('HTTPS port','Порт HTTPS')}: {connection.port}. {t('Change connection and re-test to edit.','Для изменения вернитесь к подключению и повторите проверку.')}</p>
            <p><strong>{t('Automatic synchronization','Автоматическая синхронизация')}: {t('Off','Выключена')}</strong></p>
            <p>{t('Enable a schedule explicitly in the source settings after registration.','Расписание можно явно включить в настройках источника после регистрации.')}</p>
            <div className="page-actions"><button type="button" onClick={()=>go(2)}>{t("Back","Назад")}</button>
            <button className="primary" disabled={busy||uncertain}>
              {busy ? tr("Registering…") : t("Add source","Добавить источник")}
            </button></div>
          </fieldset>}
        </form>
      )}
    </main>
  );
}
