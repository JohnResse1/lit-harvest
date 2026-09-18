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

export const api = {
  overview: () => request<Overview>("/api/overview"),
  papers: (limit = 100, offset = 0) => request<Paper[]>(`/api/papers?limit=${limit}&offset=${offset}`),
  paper: (id: string) => request<PaperDetail>(`/api/papers/${id}`),
  jobs: (limit = 100) => request<Job[]>(`/api/jobs?limit=${limit}`),
  failures: () => request<Failure[]>("/api/failures"),
  providers: () => request<Provider[]>("/api/providers"),
  quotas: () => request<Quota[]>("/api/providers/quotas"),
  importFile: (file: File, doiColumn: string) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ queued: number; duplicates: number; invalid: unknown[] }>(
      `/api/papers/import?doi_column=${encodeURIComponent(doiColumn)}`,
      { method: "POST", body: form },
    );
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
