import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useLanguage } from "../lib/LanguageContext";
import type { Failure } from "../types/api";
import { StatusBadge } from "../components/StatusBadge";

export function FailuresPage() {
  const { t } = useLanguage();
  const [failures, setFailures] = useState<Failure[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = () => api.failures().then(setFailures).catch((reason: Error) => setError(reason.message));
  useEffect(() => { refresh(); }, []);

  const act = async (operation: () => Promise<unknown>, label: string) => {
    setMessage(null);
    setError(null);
    try {
      await operation();
      setMessage(label);
      refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  };

  return (
    <div className="stack">
      <div className="page-heading">
        <div><p className="eyebrow">{t("failureCenter")}</p><h1>{t("failuresControls")}</h1></div>
        <button className="button primary" onClick={() => act(api.retryTransient, t("transientQueued"))}>
          {t("retryTransient")}
        </button>
      </div>
      {message ? <div className="notice">{message}</div> : null}
      {error ? <div className="error-panel">{error}</div> : null}
      <section className="card">
        <div className="table-wrap">
          <table>
            <thead><tr><th>{t("stage")}</th><th>{t("task")}</th><th>{t("providerService")}</th><th>{t("error")}</th><th>{t("attempts")}</th><th>{t("actions")}</th></tr></thead>
            <tbody>
              {failures.map((failure) => (
                <tr key={failure.job_id}>
                  <td><StatusBadge value={failure.status} /></td>
                  <td>{failure.task_type.replaceAll("_", " ")}</td>
                  <td>{failure.provider ?? "—"} / {failure.service ?? "—"}</td>
                  <td><code>{failure.error_code ?? t("unknownError")}</code><p>{failure.error_message}</p></td>
                  <td>{failure.attempts}</td>
                  <td className="actions">
                    <button className="button small" onClick={() => act(() => api.retryJob(failure.job_id), t("jobQueued"))}>{t("retry")}</button>
                    <button className="button small danger" onClick={() => act(() => api.cancelJob(failure.job_id), t("jobCancelled"))}>{t("cancel")}</button>
                  </td>
                </tr>
              ))}
              {failures.length === 0 ? <tr><td colSpan={6} className="empty">{t("noFailures")}</td></tr> : null}
            </tbody>
          </table>
        </div>
      </section>
      <section className="card control-card">
        <div><h2>{t("queueControl")}</h2><p>{t("queueControlDetail")}</p></div>
        <div className="actions">
          <button className="button" onClick={() => act(() => api.pause(t("pausedFromDashboard")), t("queuePaused"))}>{t("pauseQueue")}</button>
          <button className="button primary" onClick={() => act(api.resume, t("queueResumed"))}>{t("resumeQueue")}</button>
        </div>
      </section>
    </div>
  );
}
