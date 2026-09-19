import { useEffect, useState } from "react";
import { api, type PoolCredential } from "../lib/api";
import { useLanguage } from "../lib/LanguageContext";
import { ProviderLogo } from "../components/ProviderLogo";
import { StatusBadge } from "../components/StatusBadge";

const PROVIDERS = ["elsevier", "openalex", "springer", "crossref", "arxiv", "pubmed", "unpaywall"];
const SCOPES = ["credential", "account", "institution", "provider", "unknown"];

export function CredentialsPage() {
  const { t } = useLanguage();
  const [entries, setEntries] = useState<PoolCredential[]>([]);
  const [form, setForm] = useState({
    provider: "elsevier",
    name: "",
    secret: "",
    institution: "",
    quota_scope: "institution",
    priority: 100,
    notes: "",
  });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = () =>
    api.credentials().then(setEntries).catch((reason: Error) => setError(reason.message));

  useEffect(() => {
    refresh();
  }, []);

  const submit = async () => {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await api.addCredential({
        provider: form.provider.trim(),
        name: form.name.trim(),
        secret: form.secret || undefined,
        institution: form.institution || null,
        quota_scope: form.quota_scope,
        priority: Number(form.priority) || 100,
        notes: form.notes || null,
      });
      setMessage(t("credentialSaved"));
      // The key is never echoed back, so clear it immediately after saving.
      setForm({ ...form, name: "", secret: "" });
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  const act = async (operation: () => Promise<unknown>, successKey: string) => {
    setError(null);
    setMessage(null);
    try {
      await operation();
      setMessage(successKey);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  };

  return (
    <div className="stack">
      <div className="page-heading">
        <div>
          <p className="eyebrow">{t("providerTrail")}</p>
          <h1>{t("apiPool")}</h1>
        </div>
        <button className="button" onClick={() => void refresh()}>{t("refresh")}</button>
      </div>
      <p className="hint">{t("apiPoolHint")}</p>

      <section className="card">
        <h2>{t("addCredential")}</h2>
        <div className="pool-form">
          <label className="field-row">
            <span>{t("providerLabel")}</span>
            <select value={form.provider} onChange={(e) => setForm({ ...form, provider: e.target.value })}>
              {PROVIDERS.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
          <label className="field-row">
            <span>{t("credentialName")}</span>
            <input className="text-input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="university_primary" />
          </label>
          <label className="field-row">
            <span>{t("apiKey")}</span>
            <input
              className="search-input"
              type="password"
              value={form.secret}
              onChange={(e) => setForm({ ...form, secret: e.target.value })}
              placeholder={t("apiKeyPlaceholder")}
              autoComplete="off"
            />
          </label>
          <label className="field-row">
            <span>{t("poolInstitution")}</span>
            <input className="text-input" value={form.institution} onChange={(e) => setForm({ ...form, institution: e.target.value })} />
          </label>
          <label className="field-row">
            <span>{t("quotaScope")}</span>
            <select value={form.quota_scope} onChange={(e) => setForm({ ...form, quota_scope: e.target.value })}>
              {SCOPES.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
          <label className="field-row">
            <span>{t("priority")}</span>
            <input className="number-input" type="number" value={form.priority} onChange={(e) => setForm({ ...form, priority: Number(e.target.value) })} />
          </label>
          <label className="field-row">
            <span>{t("notes")}</span>
            <input className="text-input" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          </label>
          <button className="button primary" disabled={busy || !form.name.trim()} onClick={() => void submit()}>
            {busy ? t("saving") : t("save")}
          </button>
        </div>
        {message ? <div className="notice">{message}</div> : null}
        {error ? <div className="error-panel">{error}</div> : null}
      </section>

      <section className="card">
        <div className="card-heading"><h2>{t("apiPool")}</h2></div>
        {entries.length === 0 ? (
          <p className="empty">{t("poolEmpty")}</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t("providerLabel")}</th>
                  <th>{t("credentialName")}</th>
                  <th>{t("poolInstitution")}</th>
                  <th>{t("quotaScope")}</th>
                  <th>{t("stage")}</th>
                  <th>{t("priority")}</th>
                  <th>{t("lastUsed")}</th>
                  <th>{t("actions")}</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry) => (
                  <tr key={entry.credential_id}>
                    <td className="provider-cell">
                      <ProviderLogo provider={entry.provider} size={28} />
                      <span>{entry.provider}</span>
                    </td>
                    <td>
                      <strong>{entry.label}</strong>
                      <div className="subtle">
                        {entry.secret_available ? t("secretStored") : t("secretMissing")}
                      </div>
                    </td>
                    <td>{entry.institution ?? "—"}</td>
                    <td>{entry.quota_scope}</td>
                    <td>
                      <StatusBadge value={entry.enabled ? entry.health : "disabled"} />
                    </td>
                    <td>{entry.priority}</td>
                    <td className="subtle">
                      {entry.last_used_at ? new Date(entry.last_used_at).toLocaleString() : t("never")}
                      <div>{entry.use_count} {t("uses")}</div>
                    </td>
                    <td className="actions">
                      <button
                        className="button small"
                        onClick={() => void act(() => api.toggleCredential(entry.credential_id, !entry.enabled), t("credentialSaved"))}
                      >
                        {entry.enabled ? t("disabled") : t("enabled")}
                      </button>
                      <button
                        className="button small danger"
                        onClick={() => {
                          const deleteSecret = window.confirm(t("deleteSecretToo"));
                          void act(() => api.deleteCredential(entry.credential_id, deleteSecret), t("credentialDeleted"));
                        }}
                      >
                        {t("deleteCredential")}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
