import { useEffect, useState } from "react";
import { api, subscribeToUpdates } from "../lib/api";
import { useLanguage } from "../lib/LanguageContext";
import type { Overview } from "../types/api";
import { Card } from "../components/Card";
import { StatusBadge } from "../components/StatusBadge";

export function OverviewPage() {
  const { t } = useLanguage();
  const [overview, setOverview] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = () => {
    api.overview().then(setOverview).catch((reason: Error) => setError(reason.message));
  };

  useEffect(() => {
    refresh();
    return subscribeToUpdates(refresh);
  }, []);

  if (error) return <div className="error-panel">{error}</div>;
  if (!overview) return <div className="loading">{t("loadingDashboard")}</div>;

  const { papers, jobs, quota, failures, pipeline } = overview;

  return (
    <div className="stack">
      <div className="page-heading">
        <div>
          <p className="eyebrow">{t("overviewEyebrow")}</p>
          <h1>{t("overviewTitle")}</h1>
        </div>
        <div className="queue-state">
          <StatusBadge value={overview.queue.paused ? "paused" : "running"} />
          <span>{overview.queue.reason ?? t("queueActive")}</span>
        </div>
      </div>

      <div className="metrics">
        <Card label={t("papersDiscovered")} value={papers.total} detail={`${papers.stages.discovered ?? 0} ${t("awaitingMetadata")}`} />
        <Card label={t("uniqueDoi")} value={papers.unique_doi} />
        <Card label={t("fullTextRetrieved")} value={papers.fulltext_retrieved} />
        <Card label={t("normalizedPapers")} value={papers.normalized} />
        <Card label={t("queuedJobs")} value={jobs.queued} />
        <Card label={t("runningJobs")} value={jobs.running} />
        <Card label={t("failedJobs")} value={jobs.failed} detail={`${failures.length} ${t("recentFailures")}`} />
      </div>

      <div className="two-column">
        <section className="card">
          <div className="card-heading"><h2>{t("pipelineProgress")}</h2></div>
          <div className="pipeline">
            {pipeline.map((item) => (
              <div className="pipeline-step" key={item.stage}>
                <span>{item.stage}</span>
                <strong>{item.count ?? 0}</strong>
              </div>
            ))}
          </div>
        </section>

        <section className="card">
          <div className="card-heading"><h2>{t("quotaRunway")}</h2></div>
          <div className="stack compact">
            {quota.runways.map((runway) => (
              <div className="runway" key={`${runway.provider}-${runway.service}`}>
                <div>
                  <strong>{runway.provider}</strong>
                  <span>{runway.service.replaceAll("_", " ")}</span>
                </div>
                <div className="runway-numbers">
                  <span>{runway.queued_jobs} {t("queued")}</span>
                  <span>{runway.remaining ?? t("unknown")} {t("remaining")}</span>
                </div>
                {!runway.sufficient ? (
                  <p className="warning-text">
                    {t("quotaInsufficient")} {runway.shortfall} {t("jobsPendingUntilReset")}
                  </p>
                ) : <StatusBadge value="sufficient" />}
              </div>
            ))}
          </div>
        </section>
      </div>

      <section className="card">
        <div className="card-heading">
          <h2>{t("recentPapers")}</h2>
          <a href="/papers">{t("viewAll")}</a>
        </div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>{t("title")}</th><th>{t("doi")}</th><th>{t("journal")}</th><th>{t("stage")}</th></tr></thead>
            <tbody>
              {overview.recent_papers.map((paper) => (
                <tr key={paper.id}>
                  <td><a href={`/papers/${paper.id}`}>{paper.title ?? t("untitled")}</a></td>
                  <td className="mono">{paper.doi ?? "—"}</td>
                  <td>{paper.journal ?? "—"}</td>
                  <td><StatusBadge value={paper.stage} /></td>
                </tr>
              ))}
              {overview.recent_papers.length === 0 ? (
                <tr><td colSpan={4} className="empty">{t("noPapers")}</td></tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
