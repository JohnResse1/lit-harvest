import { useState } from "react";
import { api } from "../lib/api";
import { useLanguage } from "../lib/LanguageContext";

export function AcquisitionPanel({ onChanged }: { onChanged: () => void }) {
  const { t } = useLanguage();
  const [doi, setDoi] = useState("");
  const [query, setQuery] = useState('TITLE-ABS-KEY("solid-state battery")');
  const [maxResults, setMaxResults] = useState(100);
  const [downloadPdf, setDownloadPdf] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async (operation: () => Promise<unknown>, successKey: string) => {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await operation();
      setMessage(successKey);
      onChanged();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card acquisition-panel">
      <div className="card-heading">
        <h2>{t("acquireTitle")}</h2>
        {busy ? <span className="badge warn">{t("working")}</span> : null}
      </div>

      <div className="acquisition-grid">
        <div className="acquisition-block">
          <h3>{t("addDoi")}</h3>
          <input
            className="search-input full"
            value={doi}
            onChange={(event) => setDoi(event.target.value)}
            placeholder="10.1016/j.example.2026.100001"
          />
          <label className="checkbox">
            <input type="checkbox" checked={downloadPdf} onChange={(event) => setDownloadPdf(event.target.checked)} />
            {t("alsoPdf")}
          </label>
          <button
            className="button primary"
            disabled={busy || doi.trim().length === 0}
            onClick={() => run(() => api.addDoi(doi.trim(), downloadPdf), t("doiQueued"))}
          >
            {t("fetchNow")}
          </button>
        </div>

        <div className="acquisition-block">
          <h3>{t("searchTitle")}</h3>
          <input
            className="search-input full"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          <label className="field-row">
            <span>{t("maxResults")}</span>
            <input
              className="number-input"
              type="number"
              min={1}
              max={5000}
              value={maxResults}
              onChange={(event) => setMaxResults(Number(event.target.value))}
            />
          </label>
          <button
            className="button primary"
            disabled={busy || query.trim().length === 0}
            onClick={() => run(() => api.search(query.trim(), maxResults), t("searchDone"))}
          >
            {t("runSearch")}
          </button>
        </div>
      </div>

      {message ? <div className="notice">{message}</div> : null}
      {error ? <div className="error-panel">{error}</div> : null}
    </section>
  );
}
