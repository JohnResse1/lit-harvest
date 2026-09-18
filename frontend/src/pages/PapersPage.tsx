import { useEffect, useState } from "react";
import { AcquisitionPanel } from "../components/AcquisitionPanel";
import { api } from "../lib/api";
import { useLanguage } from "../lib/LanguageContext";
import type { Paper } from "../types/api";
import { StatusBadge } from "../components/StatusBadge";

const stages = ["discovered", "metadata_resolved", "fulltext_resolved", "downloaded", "normalized", "ready"];

export function PapersPage() {
  const { t } = useLanguage();
  const [papers, setPapers] = useState<Paper[]>([]);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [includePdf, setIncludePdf] = useState(true);

  const refresh = () => {
    api.papers().then(setPapers).catch((reason: Error) => setError(reason.message));
  };

  useEffect(() => {
    refresh();
  }, []);

  const downloadZip = async () => {
    const blob = await api.batchZip(null, includePdf);
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "lit-harvest-papers.zip";
    link.click();
    URL.revokeObjectURL(url);
  };

  const filtered = papers.filter((paper) => {
    const haystack = `${paper.title ?? ""} ${paper.doi ?? ""} ${paper.journal ?? ""}`.toLowerCase();
    return haystack.includes(query.toLowerCase());
  });

  return (
    <div className="stack">
      <div className="page-heading">
        <div><p className="eyebrow">{t("literatureLifecycle")}</p><h1>{t("navPapers")}</h1></div>
        <input className="search-input" value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("filterPlaceholder")} />
      </div>
      <AcquisitionPanel onChanged={refresh} />
      <div className="toolbar">
        <label className="checkbox">
          <input type="checkbox" checked={includePdf} onChange={(event) => setIncludePdf(event.target.checked)} />
          {t("includePdfZip")}
        </label>
        <button className="button" onClick={downloadZip}>{t("batchDownload")}</button>
        <a className="button" href={api.exportUrl("csv")}>{t("exportCsv")}</a>
      </div>
      <div className="stage-legend">
        {stages.map((stage, index) => (
          <div className="stage-item" key={stage}>
            <StatusBadge value={stage} />
            {index < stages.length - 1 ? <span className="stage-arrow">→</span> : null}
          </div>
        ))}
      </div>
      {error ? <div className="error-panel">{error}</div> : null}
      <section className="card">
        <div className="table-wrap">
          <table>
            <thead><tr><th>{t("title")}</th><th>{t("doi")}</th><th>{t("journal")}</th><th>{t("year")}</th><th>{t("publisher")}</th><th>{t("stage")}</th></tr></thead>
            <tbody>
              {filtered.map((paper) => (
                <tr key={paper.id}>
                  <td><a href={`/papers/${paper.id}`}>{paper.title ?? t("untitled")}</a></td>
                  <td className="mono">{paper.doi ?? "—"}</td>
                  <td>{paper.journal ?? "—"}</td>
                  <td>{paper.publication_year ?? "—"}</td>
                  <td>{paper.publisher ?? "—"}</td>
                  <td><StatusBadge value={paper.stage} /></td>
                </tr>
              ))}
              {filtered.length === 0 ? <tr><td colSpan={6} className="empty">{t("noMatchingPapers")}</td></tr> : null}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
