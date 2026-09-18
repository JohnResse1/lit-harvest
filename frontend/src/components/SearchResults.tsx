import { useState } from "react";
import { api, type MetadataColumn, type SearchCandidate, type SearchOutcome } from "../lib/api";
import { useLanguage } from "../lib/LanguageContext";

const OPTIONAL_COLUMNS: MetadataColumn[] = [
  "journal",
  "year",
  "authors",
  "affiliation",
  "document_type",
  "citation_count",
  "open_access",
  "issn",
  "volume",
  "issue",
  "pages",
  "cover_date",
  "scopus_id",
  "eid",
];

function cellValue(candidate: SearchCandidate, column: MetadataColumn): string {
  const raw = candidate[column];
  if (raw === null || raw === undefined || raw === "") return "—";
  if (typeof raw === "boolean") return raw ? "Open Access" : "—";
  return String(raw);
}

export function SearchResults({
  outcome,
  onDownloaded,
}: {
  outcome: SearchOutcome;
  onDownloaded: () => void;
}) {
  const { t } = useLanguage();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [visible, setVisible] = useState<Set<MetadataColumn>>(new Set(["journal", "year"]));
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [includePdf, setIncludePdf] = useState(false);

  const candidates = outcome.candidates;
  if (candidates.length === 0) {
    return (
      <section className="card">
        <h2>{t("searchResults")}</h2>
        <p className="empty">{t("noCandidates")}</p>
      </section>
    );
  }

  const toggle = (id: string) =>
    setSelected((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const toggleColumn = (column: MetadataColumn) =>
    setVisible((previous) => {
      const next = new Set(previous);
      if (next.has(column)) next.delete(column);
      else next.add(column);
      return next;
    });

  const allSelected = selected.size === candidates.length;

  const download = async () => {
    if (!outcome.session_id || selected.size === 0) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const ids = Array.from(selected);
      const result = await api.downloadSelected(outcome.session_id, ids, includePdf);
      setMessage(
        `${t("downloadFinished")}: ${result.succeeded} ${t("succeeded")}, ${result.failed} ${t("failed")}`,
      );
      onDownloaded();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card">
      <div className="card-heading">
        <h2>{t("searchResults")}</h2>
        <span className="badge neutral">
          {outcome.discovered} {t("candidates")}
        </span>
      </div>

      <details className="column-picker">
        <summary>{t("chooseColumns")}</summary>
        <div className="column-list">
          {OPTIONAL_COLUMNS.map((column) => (
            <label className="checkbox" key={column}>
              <input
                type="checkbox"
                checked={visible.has(column)}
                onChange={() => toggleColumn(column)}
              />
              {t(column)}
            </label>
          ))}
        </div>
      </details>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th className="narrow">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={(event) =>
                    setSelected(
                      event.target.checked ? new Set(candidates.map((c) => c.candidate_id)) : new Set(),
                    )
                  }
                />
              </th>
              <th>{t("title")}</th>
              <th>{t("doi")}</th>
              {OPTIONAL_COLUMNS.filter((column) => visible.has(column)).map((column) => (
                <th key={column}>{t(column)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {candidates.map((candidate) => (
              <tr key={candidate.candidate_id}>
                <td className="narrow">
                  <input
                    type="checkbox"
                    checked={selected.has(candidate.candidate_id)}
                    onChange={() => toggle(candidate.candidate_id)}
                  />
                </td>
                <td>{candidate.title ?? t("untitled")}</td>
                <td className="mono">{candidate.doi ?? "—"}</td>
                {OPTIONAL_COLUMNS.filter((column) => visible.has(column)).map((column) => (
                  <td key={column}>{cellValue(candidate, column)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="actions selection-actions">
        <span className="selection-count">
          {t("selected")}: {selected.size} / {candidates.length}
        </span>
        <label className="checkbox">
          <input type="checkbox" checked={includePdf} onChange={(event) => setIncludePdf(event.target.checked)} />
          {t("alsoPdf")}
        </label>
        <button className="button primary" disabled={busy || selected.size === 0} onClick={() => void download()}>
          {t("downloadSelected")}
        </button>
      </div>

      {message ? <div className="notice">{message}</div> : null}
      {error ? <div className="error-panel">{error}</div> : null}
    </section>
  );
}
