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
  testConnection,
} from "../api/onboarding";
import { SourceAccessHelp } from "../components/SourceAccessHelp";
import type { Source } from "../api/sources";

import { Link } from "react-router-dom";
import { PageHeader } from "../ui/primitives";
import { sourcePath } from "../ui/routes";
const fieldLabels = {
  source_instance: "Source ID",
  name: "Display name",
  site_slug: "Site slug",
  cluster_name: "Cluster name",
  platform_slug: "Platform slug",
  device_role_slug: "Device role slug",
  device_type_slug: "Device type slug",
  cluster_type_slug: "Cluster type slug",
};
const fields = [
  "source_instance",
  "name",
  "site_slug",
  "cluster_name",
  "platform_slug",
  "device_role_slug",
  "device_type_slug",
  "cluster_type_slug",
] as const;

export function AddSourcePage() {
  const [language] = useLanguage();
  const t = (en: string, ru: string) => language === "ru" ? ru : en;
  const [type, setType] = useState<"proxmox" | "esxi">("proxmox");
  const [connection, setConnection] = useState({
    address: "",
    verify_ssl: true,
  });
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false); const [started,setStarted]=useState(0);
  const [error, setError] = useState("");
  const [connectionCode,setConnectionCode]=useState<keyof typeof connectionMessages|null>(null);
  const [created, setCreated] = useState<Source | null>(null);

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
      const tokenValue = await testConnection({
        source_type: type,
        ...connection,
        username: String(data.get("username")),
        secret: String(data.get("secret")),
        ...(type === "proxmox"
          ? { token_id: String(data.get("token_id")) }
          : {}),
      });
      setToken(tokenValue);
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
    setBusy(true);
    setError(""); setConnectionCode(null);
    try {
      const metadata = Object.fromEntries(
        fields.map((field) => [field, String(data.get(field))]),
      ) as Record<(typeof fields)[number], string>;
      const result = await registerSource({
        ...metadata,
        source_type: type,
        ...connection,
        onboarding_token: token,
        sync_interval_seconds: Number(data.get("interval")),
        confirm_sync_disabled: true,
      });
      setCreated(result);
    } catch (failure) {
      setError(
        failure instanceof SourceIdReservedError ? failure.message :
        "Registration failed or outcome is uncertain. Ask the operator before retrying.",
      );
    } finally {
      setToken("");
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

  const metadataField = (field: (typeof fields)[number]) => (
    <label key={field}>
      {tr(fieldLabels[field])}
      <input
        name={field}
        required
        maxLength={1024}
        pattern={
          field === "source_instance" ? "[a-z0-9][a-z0-9._-]{1,62}" : undefined
        }
      />
    </label>
  );
  return (
    <main className="add-source-workspace" ref={workspace}>
      <PageHeader
        title={tr("Add source")}
        description={tr("Test connection, review source details, then register. No discovery or synchronization will run.")}
      />
      {error && (
        <p role="alert" tabIndex={-1} className="source-error">
          {connectionCode?connectionMessages[connectionCode][language==='ru'?1:0]:tr(error)}
        </p>
      )}
      {busy && <OperationFeedback operation={token?t('Registering source','Регистрация источника'):t('Testing source connection','Проверка подключения источника')} phase="sending" started={started}/>}
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
            <details className="source-access-help"><summary>{t('If access is blocked by policy','Если доступ запрещён политикой')}</summary><p>{t('The server checks every resolved address before authentication. A policy denial is not a password error. Existing deployment restrictions remain in force; Test Connection does not change them.', 'Сервер проверяет все полученные адреса до входа. Запрет политики не означает ошибку пароля. Действующие ограничения установки сохраняются; проверка подключения их не изменяет.')}</p><p>{t('Ask the deployment operator to review a denied source. Online policy management requires server-side administrator authorization, which is not implemented yet. Completing onboarding does not grant that permission.', 'При запрете источника обратитесь к оператору установки. Управление политикой через панель требует серверной проверки прав администратора, которая пока не реализована. Завершение настройки не даёт этого разрешения.')}</p></details>
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
          <fieldset disabled={busy} aria-busy={busy}>
            <legend>{tr("Identity")}{" "}</legend>
            <div className="form-grid">
              {fields.slice(0, 2).map(metadataField)}
            </div>
          </fieldset>
          <fieldset disabled={busy} aria-busy={busy}>
            <legend>{tr("NetBox target")}{" "}</legend>
            <div className="form-grid">
              {fields.slice(2, 4).map(metadataField)}
            </div>
          </fieldset>
          <fieldset disabled={busy} aria-busy={busy}>
            <legend>{tr("Provider mapping")}{" "}</legend>
            <div className="form-grid">
              {fields.slice(4).map(metadataField)}
            </div>
          </fieldset>
          <fieldset disabled={busy} aria-busy={busy}>
            <legend>{tr("Automatic sync")}{" "}</legend>
            <label>
              {tr("Configured interval (seconds)")}{" "}<input
                name="interval"
                type="number"
                min={1}
                max={2147483647}
                step={1}
                defaultValue={600}
                required
              />
            </label>
            <p className="muted">
              {tr("This stores the frequency only. Automatic sync stays off until you enable it in Schedule.")}{" "}</p>
            <label className="checkbox-label">
              <input name="confirm" type="checkbox" required /> {tr("Register a new source with automatic sync OFF.")}{" "}</label>
            <button className="primary" disabled={busy}>
              {busy ? tr("Registering…") : tr("Register Source")}
            </button>
          </fieldset>
        </form>
      )}
    </main>
  );
}
