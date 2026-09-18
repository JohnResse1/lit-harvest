import { useEffect, useState } from "react";
import { api, type StorageInfo, type StorageValidation } from "../lib/api";
import { useLanguage } from "../lib/LanguageContext";

export function StoragePage() {
  const { t } = useLanguage();
  const [info, setInfo] = useState<StorageInfo | null>(null);
  const [target, setTarget] = useState("");
  const [validation, setValidation] = useState<StorageValidation | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () => api.storage().then(setInfo).catch((reason: Error) => setError(reason.message));
  useEffect(() => {
    load();
  }, []);

  const check = async (path: string) => {
    setTarget(path);
    setValidation(null);
    if (!path.trim()) return;
    try {
      setValidation(await api.validateStorage(path.trim()));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  };

  const apply = async (overwrite: boolean) => {
    if (!target.trim()) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const result = await api.changeStorage(target.trim(), true, overwrite);
      setMessage(`${result.message} (${result.migrated_papers} ${t("papersMigrated")})`);
      setValidation(null);
      setTarget("");
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  if (!info) return <div className="loading">{t("loadingStorage")}</div>;

  return (
    <div className="stack">
      <div className="page-heading">
        <div>
          <p className="eyebrow">{t("storageEyebrow")}</p>
          <h1>{t("storageTitle")}</h1>
        </div>
        <button className="button" onClick={() => { void load(); }}>{t("refresh")}</button>
      </div>

      <section className="card">
        <h2>{t("currentStorage")}</h2>
        <div className="detail-grid storage-grid">
          <div><span>{t("storageRoot")}</span><strong className="mono small-mono">{info.root}</strong></div>
          <div><span>{t("storagePapers")}</span><strong className="mono small-mono">{info.papers}</strong></div>
          <div><span>{t("storageDatabase")}</span><strong className="mono small-mono">{info.database}</strong></div>
          <div><span>{t("storageDefault")}</span><strong className="mono small-mono">{info.default_root}</strong></div>
          <div><span>{t("paperFolders")}</span><strong>{info.paper_directories}</strong></div>
          <div><span>{t("writable")}</span><strong>{info.writable ? t("yes") : t("no")}</strong></div>
        </div>
        {info.is_default ? <p className="empty">{t("usingDefault")}</p> : null}
      </section>

      <section className="card">
        <h2>{t("changeStorage")}</h2>
        <p className="hint">{t("changeStorageHint")}</p>
        <input
          className="search-input full"
          value={target}
          onChange={(event) => void check(event.target.value)}
          placeholder="/Users/you/lit-harvest-data"
        />
        {validation ? (
          <div className={validation.ok ? "notice" : "error-panel"}>
            {validation.message}
            {validation.ok && !validation.empty ? <span> {t("targetNotEmpty")}</span> : null}
          </div>
        ) : null}
        <div className="actions">
          <button
            className="button primary"
            disabled={busy || !validation?.ok}
            onClick={() => void apply(false)}
          >
            {t("applyAndMigrate")}
          </button>
          {validation?.ok && !validation.empty ? (
            <button className="button danger" disabled={busy} onClick={() => void apply(true)}>
              {t("applyOverwrite")}
            </button>
          ) : null}
          {!info.is_default ? (
            <button
              className="button"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  const result = await api.resetStorage();
                  setMessage(result.message);
                  await load();
                } catch (reason) {
                  setError(reason instanceof Error ? reason.message : String(reason));
                } finally {
                  setBusy(false);
                }
              }}
            >
              {t("resetToDefault")}
            </button>
          ) : null}
        </div>
        {message ? <div className="notice">{message}</div> : null}
        {error ? <div className="error-panel">{error}</div> : null}
      </section>
    </div>
  );
}
