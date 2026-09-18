# Architecture

Literature Harvester is a local-first acquisition and normalization layer. v0.1 deliberately stops
before scientific LLM extraction and knowledge graphs.

```text
CLI / React UI
      │
      ▼
Service layer
  ├── PaperService
  ├── AcquisitionService
  ├── NormalizationService
  ├── DashboardService
  └── MaintenanceService
      │
      ├── Scheduler → SQLite job queue
      ├── Resolver → provider registry
      └── Providers → Elsevier (Scopus STANDARD, ScienceDirect FULL)
                           │
                           ├── CredentialManager
                           └── QuotaManager
      │
      ▼
Raw storage → deterministic parser → PaperDocument
```

## Boundaries

- CLI and FastAPI both call `ServiceContainer`; there is no separate acquisition implementation.
- Providers expose search, metadata/full-text retrieval, health, and quota behavior behind a protocol.
- Secrets stay in environment variables. SQLite stores only credential metadata and `secret_ref`.
- Raw publisher responses are immutable inputs under `data/papers/<safe-doi>/raw/`.
- Normalized documents are deterministic JSON under `data/papers/<safe-doi>/normalized/paper.json`.
- Quota state is provider/service/credential scoped. Shared institution/account/provider/unknown
  quotas block credential rotation as a circumvention strategy.
- Long-running work is represented by persistent jobs with retry and quota states.
- The future scientific extraction API consumes `PaperDocument`, never publisher XML.
