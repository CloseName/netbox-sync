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
  CatalogFailure,
} from "../api/onboarding";
import { SourceAccessHelp } from "../components/SourceAccessHelp";
import type { Source } from "../api/sources";

import { Link } from "react-router-dom";
import { PageHeader } from "../ui/primitives";
import { sourcePath } from "../ui/routes";
// In-memory non-secret draft survives an auth-boundary remount; no token or password.
let remembered: {type:'proxmox'|'esxi';connection:{address:string;verify_ssl:boolean};draft:Placement;preview:SourcePreview|null}|null=null;
export function AddSourcePage() {
  const [language] = useLanguage();
  const t = (en: string, ru: string) => language === "ru" ? ru : en;
  const [type, setType] = useState<"proxmox" | "esxi">(remembered?.type??"proxmox");
  const [connection, setConnection] = useState(remembered?.connection??{
    address: "",
    verify_ssl: true,
  });
  const [token, setToken] = useState("");
  const [preview,setPreview]=useState<SourcePreview|null>(remembered?.preview??null);
  const [review,setReview]=useState(false);
  const [draft,setDraft]=useState<Placement>(remembered?.draft??{source_instance:'',name:'',interval:600,references:{},host_types:{}});
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false); const [started,setStarted]=useState(0);
  const [error, setError] = useState("");
  const [connectionCode,setConnectionCode]=useState<keyof typeof connectionMessages|null>(null);
  const [created, setCreated] = useState<Source | null>(null);

  useEffect(()=>{remembered=created?null:{type,connection,draft,preview};},[type,connection,draft,preview,created]);
  const workspace = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!error && !token && !created) return;
    const target = workspace.current?.querySelector<HTMLElement>(
      error ? '[role="alert"]' : created ? "h1" : "h2",
    );
    if (target) {
      target.tabIndex = -1;
      target.focus();
    }
  }, [error, token, created]);
  async function changeConnection() {
    if (inFlight.current) return;
    inFlight.current=true; setStarted(Date.now());
    setBusy(true);
    setError(""); setConnectionCode(null);
    try {
      await cancelOnboarding(token);
      setToken("");
    } catch {
      setError(
        "Could not invalidate the previous test. Retry before changing connection values.",
      );
    } finally {
      inFlight.current=false; setBusy(false);
    }
  }

  async function test(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (inFlight.current) return;
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
      setToken(result.onboarding_token);setPreview(result.preview);setReview(false);
      setDraft(d=>({...d,source_instance:d.source_instance||result.suggested_source_instance,name:d.name||result.preview.name||connection.address,host_types:Object.fromEntries(Object.entries(d.host_types).filter(([id])=>result.preview.hosts.some(h=>h.id===id&&preview?.hosts.some(old=>old.id===id&&old.model===h.model&&old.manufacturer===h.manufacturer))))}));
    } catch (failure) {
      if(failure instanceof SourceConnectionError)setConnectionCode(failure.code);
      setError(
        failure instanceof SourceConnectionError ? connectionMessages[failure.code][language === 'ru' ? 1 : 0] :
        t("Connection test failed. Re-enter credentials to retry; nothing was registered.", "Проверка подключения не завершена. Введите данные повторно; источник не зарегистрирован."),
      );
    } finally {
      form.reset();
      inFlight.current=false; setBusy(false);
    }
  }

  async function register(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (inFlight.current) return;
    const data = new FormData(event.currentTarget);
    if (data.get("confirm") !== "on") return;
    inFlight.current=true; setStarted(Date.now());
    let selectionRejected=false;
    setBusy(true);
    setError(""); setConnectionCode(null);
    try {
      const refs=draft.references;const firstType=Object.values(draft.host_types)[0];
      const metadata={source_instance:draft.source_instance,name:draft.name,site_slug:refs.site.slug,
        cluster_name:refs.cluster.name,platform_slug:refs.platform.slug,device_role_slug:refs.device_role.slug,
        device_type_slug:firstType.slug,cluster_type_slug:refs.cluster_type.slug,references:refs,host_types:draft.host_types};
      const result = await registerSource({
        ...metadata,
        source_type: type,
        ...connection,
        onboarding_token: token,
        sync_interval_seconds: draft.interval,
        confirm_sync_disabled: true,
      });
      setCreated(result);
    } catch (failure) {
      if(failure instanceof CatalogFailure){selectionRejected=true;setReview(false);}
      setError(
        failure instanceof CatalogFailure?t('NetBox selection changed or could not be verified. Refresh the lists and review the site, cluster and host device types; nothing was registered.','Выбор NetBox изменился или не прошёл проверку. Обновите списки, проверьте площадку, кластер и типы устройств хостов; источник не зарегистрирован.'):
        failure instanceof SourceIdReservedError ? failure.message :
        "Registration failed or outcome is uncertain. Ask the operator before retrying.",
      );
    } finally {
      if(!selectionRejected)setToken("");
      inFlight.current=false; setBusy(false);
    }
  }

  if (created)
    return (
      <main className="add-source-workspace" ref={workspace}>
        <PageHeader
          title={tr("Source registered")}
          description={tr("Automatic sync is off. Review the source before planning a sync.")}
        />
        <section className="source-panel registration-result">
          <h2>{created.name}</h2>
          <dl className="source-facts">
            <div>
              <dt>{tr("Source ID")}{" "}</dt>
              <dd>
                <code>{created.source_instance}</code>
              </dd>
            </div>
            <div>
              <dt>{tr("Address")}{" "}</dt>
              <dd>{created.address}</dd>
            </div>
            <div>
              <dt>{tr("Source")}{" "}</dt>
              <dd>{tr("Enabled")}{" "}</dd>
            </div>
            <div>
              <dt>{tr("Automatic sync")}{" "}</dt>
              <dd>{tr("Off")}{" "}</dd>
            </div>
          </dl>
          <p className="muted">
            {tr("Credentials are protected. Connection was tested during registration, not continuously.")}{" "}</p>
          <div className="page-actions">
            <Link
              className="button primary"
              to={sourcePath(created.source_instance)}
            >
              {tr("Open source")}{" "}</Link>
            <Link to="/sources">{tr("View sources")}{" "}</Link>
          </div>
        </section>
      </main>
    );

  return (
    <main className="add-source-workspace" ref={workspace}>
      <PageHeader
        title={tr("Add source")}
        description={t('Connect → read host information → choose NetBox placement → register. No VM inventory scan or NetBox writes.','Подключение → сведения о хостах → размещение в NetBox → регистрация. Без обхода виртуальных машин и записи в NetBox.')}
      />
      {error && (
        <p role="alert" tabIndex={-1} className="source-error">
          {connectionCode?connectionMessages[connectionCode][language==='ru'?1:0]:tr(error)}
        </p>
      )}
      {connectionCode==='SOURCE_DESTINATION_DENIED'&&<DestinationPermission host={connection.address} done={()=>{setConnectionCode(null);setError(t('Destination allowed. Re-enter credentials and test the connection.','Назначение разрешено. Введите учётные данные и повторите проверку подключения.'));}}/>}
      {busy && <OperationFeedback operation={token?t('Registering source','Регистрация источника'):t('Checking connection and reading host information','Проверяем подключение и получаем сведения о хостах')} phase="sending" started={started}/>}
      {!token ? (
        <form onSubmit={test} className="source-form" autoComplete="off">
          <fieldset disabled={busy} aria-busy={busy}>
            <legend>{tr("Connection")}{" "}</legend>
            <div className="form-grid">
              <label>
                {tr("Source type")}{" "}<select
                  value={type}
                  onChange={(event) => {
                    const nextType = event.target.value as typeof type;
                    event.currentTarget.form?.reset();
                    setType(nextType);
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
            <h2>{t('Source credentials', 'Доступ к источнику')}</h2>
            <p className="muted">
              {t('Credentials apply only to this source and are cleared from the form after testing.', 'Данные доступа относятся только к этому источнику и удаляются из формы после проверки.')}
            </p>
            <div className="form-grid">
              <label>
                {type === "proxmox" ? tr("Token user (user@realm)") : tr("Username")}
                <input name="username" required aria-describedby="source-user-hint" />
                <small id="source-user-hint">{type === 'proxmox' ? t('User including realm, e.g. netbox-sync@pve.', 'Пользователь вместе с realm, например netbox-sync@pve.') : t('Local ESXi user, e.g. netbox-sync.', 'Локальный пользователь ESXi, например netbox-sync.')}</small>
              </label>
              {type === "proxmox" && (
                <label>
                  {tr("Token name (without user prefix)")}{" "}<input name="token_id" required aria-describedby="source-token-hint" />
                  <small id="source-token-hint">{t('Token name only, e.g. netbox-sync; not user@realm!token.', 'Только имя токена, например netbox-sync; не user@realm!token.')}</small>
                </label>
              )}
              <label>
                {type === "proxmox" ? tr("Token secret") : tr("Password")}
                <input
                  name="secret"
                  type="password"
                  required
                  aria-describedby="source-secret-hint"
                  autoComplete="new-password"
                />
                <small id="source-secret-hint">{type === 'proxmox' ? t('The value saved at token issuance; not the user password.', 'Значение, сохранённое при выдаче токена; не пароль пользователя.') : t('Separate password for this host’s account.', 'Отдельный пароль пользователя на этом хосте.')}</small>
              </label>
            </div>
            <SourceAccessHelp provider={type} language={language}/>
            <details className="source-access-help"><summary>{t('If access is blocked by policy','Если доступ запрещён политикой')}</summary><p>{t('The server checks every resolved address before authentication. A policy denial is not a password error. Existing deployment restrictions remain in force; Test Connection does not change them.', 'Сервер проверяет все полученные адреса до входа. Запрет политики не означает ошибку пароля. Действующие ограничения установки сохраняются; проверка подключения их не изменяет.')}</p><p>{t('For a denied public destination, use the separate permission action below the error. The server checks administrator permissions; host-managed limits may require a one-time transition by the host operator.', 'Для запрещённого публичного назначения используйте отдельное разрешение под сообщением об ошибке. Сервер проверяет права администратора; ограничения сервера могут требовать однократного перехода, выполняемого его оператором.')}</p></details>
            <button className="primary" disabled={busy}>
              {busy ? tr("Testing…") : tr("Test Connection")}
            </button>
          </fieldset>
        </form>
      ) : (
        <form onSubmit={register} className="source-form">
          <section className="source-panel">
            <h2 tabIndex={-1}>{tr("Review source details")}{" "}</h2>
            <p>
              {tr("Connection test succeeded. Credentials have been cleared from the form.")}{" "}</p>
            <p>
              {type === "proxmox" ? tr("Proxmox VE") : tr("VMware ESXi")} ·{" "}
              {connection.address} {tr("· TLS verification")}{" "}{" "}
              {connection.verify_ssl ? tr("on") : tr("off")}.
            </p>
            <button type="button" disabled={busy} onClick={changeConnection}>
              {tr("Change connection and re-test")}{" "}</button>
          </section>
          {preview&&!review&&<fieldset disabled={busy}><SourcePlacement preview={preview} draft={draft} setDraft={setDraft} language={language}/>
          {Object.keys(draft.references).length!==5||preview.hosts.some(h=>!draft.host_types[h.id])?<p role="status">{t('Choose all five placement objects and a device type for each host to continue.','Для продолжения выберите все пять объектов размещения и тип устройства для каждого хоста.')}</p>:null}
          <button type="button" className="primary" disabled={Object.keys(draft.references).length!==5||preview.hosts.some(h=>!draft.host_types[h.id])||!draft.name.trim()} onClick={event=>{if(event.currentTarget.form?.reportValidity())setReview(true);}}>{t('Review registration','Проверить регистрацию')}</button></fieldset>}
          {review&&<fieldset disabled={busy}><legend>{t('Confirm registration','Подтверждение регистрации')}</legend>
          <h2>{draft.name}</h2><dl className="source-facts">{Object.entries(draft.references).map(([kind,row])=><div key={kind}><dt>{({site:t('Site','Площадка'),cluster:t('Cluster','Кластер'),platform:t('Platform','Платформа'),device_role:t('Device role','Роль устройства'),cluster_type:t('Cluster type','Тип кластера')} as Record<string,string>)[kind]}</dt><dd>{row.name}</dd></div>)}</dl>
          {preview?.hosts.map(h=><p key={h.id}>{h.name||h.id} → {draft.host_types[h.id]?.manufacturer?.name} / {draft.host_types[h.id]?.name}</p>)}
          <p>{t('Only the source and protected credentials will be saved. NetBox infrastructure objects and automatic synchronization remain unchanged.','Сохранятся только источник и защищённые данные доступа. Инфраструктурные объекты NetBox и автоматическая синхронизация не изменяются.')}</p>
          <button type="button" onClick={()=>setReview(false)}>{t('Back to placement','Вернуться к размещению')}</button>
            <label className="checkbox-label">
              <input name="confirm" type="checkbox" required /> {tr("Register a new source with automatic sync OFF.")}{" "}</label>
            <button className="primary" disabled={busy}>
              {busy ? tr("Registering…") : tr("Register Source")}
            </button>
          </fieldset>}
        </form>
      )}
    </main>
  );
}
