import type { Failure, Job, Overview, Paper, PaperDetail, Provider, Quota } from "../types/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: init?.body instanceof FormData ? undefined : { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

export interface WorkerStatus {
  alive: boolean;
  running: boolean;
  ticks: number;
  paused: boolean;
  last_result: Record<string, unknown> | null;
}

export interface SearchOutcome {
  query: string;
  discovered: number;
  stored: number;
  pages: number;
  total_results: number | null;
}

export const api = {
  overview: () => request<Overview>("/api/overview"),
  worker: () => request<WorkerStatus>("/api/worker"),
  search: (query: string, maxResults: number, startYear?: number, endYear?: number) =>
    request<SearchOutcome>("/api/search", {
      method: "POST",
      body: JSON.stringify({
        query,
        max_results: maxResults,
        start_year: startYear || null,
        end_year: endYear || null,
      }),
    }),
  addDoi: (doi: string, downloadPdf = false) =>
    request<Record<string, unknown>>("/api/papers/doi", {
      method: "POST",
      body: JSON.stringify({ doi, download_pdf: downloadPdf }),
    }),
  downloadUrl: (paperId: string, kind: "xml" | "pdf" | "normalized") =>
    `/api/papers/${paperId}/download/${kind}`,
  exportUrl: (format: "csv" | "json" | "jsonl") =>
    `/api/papers/export?format=${format}&download=true`,
  papers: (limit = 100, offset = 0) => request<Paper[]>(`/api/papers?limit=${limit}&offset=${offset}`),
  paper: (id: string) => request<PaperDetail>(`/api/papers/${id}`),
  jobs: (limit = 100) => request<Job[]>(`/api/jobs?limit=${limit}`),
  failures: () => request<Failure[]>("/api/failures"),
  providers: () => request<Provider[]>("/api/providers"),
  quotas: () => request<Quota[]>("/api/providers/quotas"),
  importFile: (file: File, doiColumn: string, runNow = false, downloadPdf = false) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ queued: number; duplicates: number; invalid: unknown[] }>(
      `/api/papers/import?doi_column=${encodeURIComponent(doiColumn)}` +
        `&run_now=${runNow}&download_pdf=${downloadPdf}`,
      { method: "POST", body: form },
    );
  },
  batchZip: async (paperIds: string[] | null, includePdf: boolean) => {
    const response = await fetch("/api/papers/download/zip", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paper_ids: paperIds, include_pdf: includePdf, include_normalized: true }),
    });
    if (!response.ok) throw new Error(await response.text());
    return response.blob();
  },
  pause: (reason?: string) =>
    request<{ paused: boolean }>("/api/queue/pause", {
      method: "POST",
      body: JSON.stringify({ reason: reason ?? null }),
    }),
  resume: () => request<{ paused: boolean }>("/api/queue/resume", { method: "POST" }),
  retryJob: (jobId: string) => request(`/api/jobs/${jobId}/retry`, { method: "POST" }),
  cancelJob: (jobId: string) => request(`/api/jobs/${jobId}/cancel`, { method: "POST" }),
  retryTransient: () => request<{ retried: number }>("/api/failures/retry-transient", { method: "POST" }),
};

export function subscribeToUpdates(onUpdate: () => void): () => void {
  const source = new EventSource("/api/events");
  source.addEventListener("message", onUpdate);
  return () => source.close();
}
