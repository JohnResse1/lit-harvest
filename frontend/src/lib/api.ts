import type { Failure, Job, Overview, Paper, PaperDetail, Provider, Quota } from "../types/api";

/** Turn an API error body into a short, human-readable sentence. */
function extractErrorMessage(raw: string, status: number): string {
  if (raw) {
    try {
      const parsed: unknown = JSON.parse(raw);
      if (parsed && typeof parsed === "object" && "detail" in parsed) {
        const detail = (parsed as { detail: unknown }).detail;
        if (typeof detail === "string") return detail;
        if (detail && typeof detail === "object" && "message" in detail) {
          const message = (detail as { message: unknown }).message;
          if (typeof message === "string") return message;
        }
      }
    } catch {
      // Not JSON; fall through to a generic message below.
    }
  }
  return `Request failed (HTTP ${status}).`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: init?.body instanceof FormData ? undefined : { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    const raw = await response.text();
    throw new Error(extractErrorMessage(raw, response.status));
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

export interface ImportOutcome {
  queued: number;
  duplicates: number;
  invalid: Array<{ raw: string; row: number | null; reason: string }>;
  paper_ids: string[];
  run?: { attempted: number; succeeded: number; failed: number; waiting_for_quota: number };
  pdf_succeeded?: number;
  pdf_failed?: number;
}

export interface SearchCandidate {
  candidate_id: string;
  paper_id: string | null;
  doi: string | null;
  title: string | null;
  journal: string | null;
  year: number | null;
  authors: string | null;
  affiliation: string | null;
  document_type: string | null;
  citation_count: number | null;
  open_access: boolean | null;
  free_to_read: string | null;
  issn: string | null;
  volume: string | null;
  issue: string | null;
  pages: string | null;
  cover_date: string | null;
  scopus_id: string | null;
  eid: string | null;
  scopus_url: string | null;
  selected: boolean;
}

export interface SearchOutcome {
  query: string;
  discovered: number;
  stored: number;
  pages: number;
  total_results: number | null;
  session_id: string | null;
  candidates: SearchCandidate[];
}

export type MetadataColumn =
  | "journal" | "year" | "authors" | "affiliation" | "document_type"
  | "citation_count" | "open_access" | "issn" | "volume" | "issue"
  | "pages" | "cover_date" | "scopus_id" | "eid";

export interface StorageInfo {
  root: string;
  papers: string;
  database: string;
  default_root: string;
  is_default: boolean;
  exists: boolean;
  writable: boolean;
  paper_directories: number;
}

export interface StorageValidation {
  path: string;
  ok: boolean;
  message: string;
  exists: boolean;
  writable: boolean;
  empty: boolean;
}

export interface PoolCredential {
  credential_id: string;
  provider: string;
  name: string;
  label: string;
  secret_ref: string;
  institution: string | null;
  quota_scope: string;
  enabled: boolean;
  health: string;
  secret_available: boolean;
  priority: number;
  last_used_at: string | null;
  use_count: number;
  notes: string | null;
}

export interface CredentialInput {
  provider: string;
  name: string;
  secret?: string;
  institution?: string | null;
  account_label?: string | null;
  quota_scope?: string;
  priority?: number;
  notes?: string | null;
  enabled?: boolean;
}

export interface InstanceInfo {
  instance_id: string;
  user: string;
  hostname: string;
  project: string;
}

export const api = {
  overview: () => request<Overview>("/api/overview"),
  instance: () => request<InstanceInfo>("/api/instance"),
  credentials: (provider?: string) =>
    request<PoolCredential[]>(
      provider ? `/api/credentials?provider=${encodeURIComponent(provider)}` : "/api/credentials",
    ),
  addCredential: (input: CredentialInput) =>
    request<PoolCredential>("/api/credentials", {
      method: "POST",
      body: JSON.stringify(input),
    }),
  toggleCredential: (id: string, enabled: boolean) =>
    request<PoolCredential>(`/api/credentials/${id}/enabled`, {
      method: "POST",
      body: JSON.stringify({ enabled }),
    }),
  deleteCredential: (id: string, deleteSecret = false) =>
    request<{ credential_id: string; secret_deleted: boolean }>(
      `/api/credentials/${id}?delete_secret=${deleteSecret}`,
      { method: "DELETE" },
    ),
  credentialHealth: (provider: string) =>
    request<{ provider: string; credentials: Array<Record<string, unknown>> }>(
      `/api/credentials/${provider}/health`,
    ),
  selectionPreview: (provider: string, service = "article_retrieval") =>
    request<Record<string, unknown>>(
      `/api/credentials/${provider}/selection?service=${service}`,
    ),
  storage: () => request<StorageInfo>("/api/settings/storage"),
  validateStorage: (path: string) =>
    request<StorageValidation>(`/api/settings/storage/validate?path=${encodeURIComponent(path)}`),
  changeStorage: (path: string, migrate: boolean, overwrite: boolean) =>
    request<{ storage_root: string; migrated_papers: number; message: string }>(
      "/api/settings/storage",
      { method: "POST", body: JSON.stringify({ path, migrate, overwrite }) },
    ),
  resetStorage: () =>
    request<{ storage_root: string; message: string }>("/api/settings/storage/reset?migrate=true", {
      method: "POST",
    }),
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
  selectCandidates: (sessionId: string, candidateIds: string[]) =>
    request<{ session_id: string; selected_count: number }>(
      `/api/search/sessions/${sessionId}/select`,
      { method: "POST", body: JSON.stringify({ candidate_ids: candidateIds }) },
    ),
  downloadSelected: (sessionId: string, candidateIds: string[], downloadPdf: boolean) =>
    request<{ requested: number; succeeded: number; failed: number }>(
      `/api/search/sessions/${sessionId}/download`,
      {
        method: "POST",
        body: JSON.stringify({ candidate_ids: candidateIds, download_pdf: downloadPdf }),
      },
    ),
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
  importFile: (
    file: File,
    doiColumn = "doi",
    runNow = false,
    downloadPdf = false,
  ) => {
    const form = new FormData();
    form.append("file", file);
    return request<ImportOutcome>(
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
    if (!response.ok) {
      throw new Error(extractErrorMessage(await response.text(), response.status));
    }
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
