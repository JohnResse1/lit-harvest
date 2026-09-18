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

## Provider model

Providers advertise capabilities, and the workflow asks the registry for them rather than naming a
publisher:

```text
supports_search     discovery (queries -> candidate papers)
supports_fulltext   retrieve structured full text for a DOI
supports_pdf        retrieve the publisher PDF
supports_metadata   enrich bibliographic metadata
```

The **Resolver** ranks candidate sources for a DOI. It reasons only about capability and document
quality, never about a specific publisher:

```text
publisher structured XML (100)  >  structured HTML (80)  >  PDF (60)
```

Current shape:

| Provider | search | fulltext | pdf | notes |
| --- | --- | --- | --- | --- |
| Elsevier | yes | yes | yes | Scopus Search `STANDARD` + ScienceDirect `FULL` |

Adding a provider means implementing the protocol and registering a factory in
`ServiceContainer._build_providers`. The resolver, acquisition service, scheduler, and API do not
change.

Configuration is dictionary-driven and accepts both shapes:

```yaml
# modern (multi-provider)
providers:
  entries:
    elsevier: {...}
    springer: {...}

# legacy (single provider) — still supported
providers:
  elsevier: {...}
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
