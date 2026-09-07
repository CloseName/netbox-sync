import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import {
  cancelOnboarding,
  registerSource,
  SourceIdReservedError,
  testConnection,
} from "../api/onboarding";
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
  const [type, setType] = useState<"proxmox" | "esxi">("proxmox");
  const [connection, setConnection] = useState({
    address: "",
    verify_ssl: true,
  });
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
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
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await cancelOnboarding(token);
      setToken("");
    } catch {
      setError(
        "Could not invalidate the previous test. Retry before changing connection values.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function test(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    setBusy(true);
    setError("");
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
    } catch {
      setError(
        "Connection test failed. Re-enter credentials to retry; nothing was registered.",
      );
    } finally {
      form.reset();
      setBusy(false);
    }
  }

  async function register(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const data = new FormData(event.currentTarget);
    if (data.get("confirm") !== "on") return;
    setBusy(true);
    setError("");
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
      setBusy(false);
    }
  }

  if (created)
    return (
      <main className="add-source-workspace" ref={workspace}>
        <PageHeader
          title="Source registered"
          description="Automatic sync is off. Review the source before planning a sync."
        />
        <section className="source-panel registration-result">
          <h2>{created.name}</h2>
          <dl className="source-facts">
            <div>
              <dt>Source ID</dt>
              <dd>
                <code>{created.source_instance}</code>
              </dd>
            </div>
            <div>
              <dt>Address</dt>
              <dd>{created.address}</dd>
            </div>
            <div>
              <dt>Source</dt>
              <dd>Enabled</dd>
            </div>
            <div>
              <dt>Automatic sync</dt>
              <dd>Off</dd>
            </div>
          </dl>
          <p className="muted">
            Credentials are protected. Connection was tested during
            registration, not continuously.
          </p>
          <div className="page-actions">
            <Link
              className="button primary"
              to={sourcePath(created.source_instance)}
            >
              Open source
            </Link>
            <Link to="/sources">View sources</Link>
          </div>
        </section>
      </main>
    );

  const metadataField = (field: (typeof fields)[number]) => (
    <label key={field}>
      {fieldLabels[field]}
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
        title="Add source"
        description="Test connection, review source details, then register. No discovery or synchronization will run."
      />
      {error && (
        <p role="alert" tabIndex={-1} className="source-error">
          {error}
        </p>
      )}
      {busy && (
        <p role="status">
          {token ? "Registering source…" : "Checking connection…"}
        </p>
      )}
      {!token ? (
        <form onSubmit={test} className="source-form" autoComplete="off">
          <fieldset disabled={busy}>
            <legend>Connection</legend>
            <div className="form-grid">
              <label>
                Source type
                <select
                  value={type}
                  onChange={(event) => {
                    const nextType = event.target.value as typeof type;
                    event.currentTarget.form?.reset();
                    setType(nextType);
                  }}
                >
                  <option value="proxmox">Proxmox VE</option>
                  <option value="esxi">VMware ESXi</option>
                </select>
              </label>
              <label>
                Hostname or IPv4 address
                <input
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
              Verify TLS certificate
            </label>
            <h2>Source credentials</h2>
            <p className="muted">
              Credentials apply only to this source and are cleared from the
              form after testing.
            </p>
            <div className="form-grid">
              <label>
                {type === "proxmox" ? "Token user (user@realm)" : "Username"}
                <input name="username" required />
              </label>
              {type === "proxmox" && (
                <label>
                  Token name (without user prefix)
                  <input name="token_id" type="password" required />
                </label>
              )}
              <label>
                {type === "proxmox" ? "Token secret" : "Password"}
                <input
                  name="secret"
                  type="password"
                  required
                  autoComplete="new-password"
                />
              </label>
            </div>
            <button className="primary" disabled={busy}>
              {busy ? "Testing…" : "Test Connection"}
            </button>
          </fieldset>
        </form>
      ) : (
        <form onSubmit={register} className="source-form">
          <section className="source-panel">
            <h2 tabIndex={-1}>Review source details</h2>
            <p>
              Connection test succeeded. Credentials have been cleared from the
              form.
            </p>
            <p>
              {type === "proxmox" ? "Proxmox VE" : "VMware ESXi"} ·{" "}
              {connection.address} · TLS verification{" "}
              {connection.verify_ssl ? "on" : "off"}.
            </p>
            <button type="button" disabled={busy} onClick={changeConnection}>
              Change connection and re-test
            </button>
          </section>
          <fieldset disabled={busy}>
            <legend>Identity</legend>
            <div className="form-grid">
              {fields.slice(0, 2).map(metadataField)}
            </div>
          </fieldset>
          <fieldset disabled={busy}>
            <legend>NetBox target</legend>
            <div className="form-grid">
              {fields.slice(2, 4).map(metadataField)}
            </div>
          </fieldset>
          <fieldset disabled={busy}>
            <legend>Provider mapping</legend>
            <div className="form-grid">
              {fields.slice(4).map(metadataField)}
            </div>
          </fieldset>
          <fieldset disabled={busy}>
            <legend>Automatic sync</legend>
            <label>
              Configured interval (seconds)
              <input
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
              This stores the frequency only. Automatic sync stays off until you
              enable it in Schedule.
            </p>
            <label className="checkbox-label">
              <input name="confirm" type="checkbox" required /> Register a new
              source with automatic sync OFF.
            </label>
            <button className="primary" disabled={busy}>
              {busy ? "Registering…" : "Register Source"}
            </button>
          </fieldset>
        </form>
      )}
    </main>
  );
}
