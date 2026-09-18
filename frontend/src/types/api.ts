export type Stage = "discovered" | "metadata_resolved" | "fulltext_resolved" | "downloaded" | "normalized" | "ready" | "failed";

export interface Paper {
  id: string;
  doi: string | null;
  title: string | null;
  journal: string | null;
  publication_year: number | null;
  publisher: string | null;
  document_type: string | null;
  discovery_source: string | null;
  stage: Stage;
  identifiers: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface Job {
  id: string;
  paper_id: string | null;
  task_type: string;
  provider: string | null;
  service: string | null;
  status: string;
  attempts: number;
  max_attempts: number;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface Failure {
  job_id: string;
  paper_id: string | null;
  task_type: string;
  provider: string | null;
  service: string | null;
  status: string;
  attempts: number;
  error_code: string | null;
  error_message: string | null;
  completed_at: string | null;
}

export interface Quota {
  id: string;
  provider: string;
  service: string;
  credential_id: string | null;
  limit: number | null;
  remaining: number | null;
  reset_at: string | null;
  observed_at: string;
  source: string;
  quota_scope: string;
  status: string;
  message: string | null;
}

export interface Provider {
  name: string;
  display_name: string;
  enabled: boolean;
  health_status: string;
  services: Array<{
    name: string;
    enabled: boolean;
    health_status: string;
    quotas: Quota[];
  }>;
  credentials: Array<{
    id: string;
    name: string;
    label: string;
    institution: string | null;
    quota_scope: string;
    health: string;
    enabled: boolean;
  }>;
}

export interface Overview {
  papers: {
    total: number;
    unique_doi: number;
    fulltext_retrieved: number;
    normalized: number;
    stages: Record<string, number>;
  };
  jobs: {
    total: number;
    by_status: Record<string, number>;
    queued: number;
    running: number;
    failed: number;
  };
  pipeline: Array<{ stage: string; count: number }>;
  quota: {
    states: Quota[];
    runways: Array<{
      provider: string;
      service: string;
      queued_jobs: number;
      remaining: number | null;
      sufficient: boolean;
      shortfall: number;
    }>;
  };
  failures: Failure[];
  recent_papers: Paper[];
  queue: { paused: boolean; reason: string | null };
  generated_at: string;
}

export interface PaperDetail {
  paper: Paper;
  downloads: Array<Record<string, unknown>>;
  acquisition: Record<string, unknown> | null;
  parsing: Record<string, number>;
  files: { raw: string | null; normalized: string | null };
  normalized: Record<string, unknown> | null;
}
