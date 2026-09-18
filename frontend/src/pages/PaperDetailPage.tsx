import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useLanguage } from "../lib/LanguageContext";
import type { PaperDetail } from "../types/api";
import { StatusBadge } from "../components/StatusBadge";

export function PaperDetailPage({ paperId }: { paperId: string }) {
  const { t } = useLanguage();
  const [detail, setDetail] = useState<PaperDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.paper(paperId).then(setDetail).catch((reason: Error) => setError(reason.message));
  }, [paperId]);

  if (error) return <div className="error-panel">{error}</div>;
  if (!detail) return <div className="loading">{t("loadingPaper")}</div>;
  const { paper, acquisition, parsing, files } = detail;

  return (
    <div className="stack">
      <div className="page-heading">
        <div>
          <a className="back-link" href="/papers">{t("backToPapers")}</a>
          <p className="eyebrow">{paper.journal ?? t("unknownJournal")}</p>
          <h1>{paper.title ?? t("untitled")}</h1>
          <p className="mono">{paper.doi ?? t("noDoi")}</p>
        </div>
        <StatusBadge value={paper.stage} />
      </div>

      <div className="two-column">
        <section className="card detail-card">
          <h2>{t("bibliographic")}</h2>
          <dl>
            <dt>{t("publisher")}</dt><dd>{paper.publisher ?? "—"}</dd>
            <dt>{t("year")}</dt><dd>{paper.publication_year ?? "—"}</dd>
            <dt>{t("documentType")}</dt><dd>{paper.document_type ?? "—"}</dd>
            <dt>{t("discoverySource")}</dt><dd>{paper.discovery_source ?? "—"}</dd>
          </dl>
        </section>
        <section className="card detail-card">
          <h2>{t("identifiers")}</h2>
          <dl>
            {Object.entries(paper.identifiers).map(([key, value]) => (
              <div className="identifier-row" key={key}>
                <dt>{key}</dt><dd className="mono">{String(value ?? "—")}</dd>
              </div>
            ))}
          </dl>
        </section>
      </div>

      <section className="card">
        <h2>{t("acquisitionParsing")}</h2>
        <div className="detail-grid">
          <div><span>{t("provider")}</span><strong>{String(acquisition?.provider ?? "—")}</strong></div>
          <div><span>{t("service")}</span><strong>{String(acquisition?.service ?? "—")}</strong></div>
          <div><span>{t("format")}</span><strong>{String(acquisition?.format ?? "—")}</strong></div>
          <div><span>{t("httpStatus")}</span><strong>{String(acquisition?.http_status ?? "—")}</strong></div>
          <div><span>{t("sections")}</span><strong>{parsing.sections ?? 0}</strong></div>
          <div><span>{t("figures")}</span><strong>{parsing.figures ?? 0}</strong></div>
          <div><span>{t("tables")}</span><strong>{parsing.tables ?? 0}</strong></div>
          <div><span>{t("references")}</span><strong>{parsing.references ?? 0}</strong></div>
        </div>
        <div className="file-paths">
          <p><span>{t("raw")}</span><code>{files.raw ?? t("notDownloaded")}</code></p>
          <p><span>{t("normalized")}</span><code>{files.normalized ?? t("notParsed")}</code></p>
        </div>
      </section>
    </div>
  );
}
