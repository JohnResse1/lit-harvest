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
  ├── NormalizationService → ParserRegistry
  ├── DashboardService
  └── MaintenanceService
      │
      ├── Scheduler → SQLite job queue
      ├── Resolver → provider registry
      └── Providers → capability-based registry (see table below)
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
supports_oa_lookup  locate a free (open access) copy for a DOI
supports_tdm_links  enumerate publisher-registered text-mining routes
requires_credential false for key-free sources, so the UI never asks for a key
```

The **Resolver** ranks candidate sources for a DOI. It reasons only about capability and document
quality, never about a specific publisher:

```text
publisher structured XML (100)  >  structured HTML (80)  >  PDF (60)
```

Current shape:

| Provider | search | fulltext | pdf | metadata | oa lookup | TDM | key | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Elsevier | yes | yes | yes | yes | – | – | 1 | Scopus Search `STANDARD` + ScienceDirect `FULL` |
| OpenAlex | yes | – | – | yes | yes | – | none | cross-publisher, CC0 metadata |
| Springer Nature | yes | – | – | yes | yes | – | 2 | Meta API + OpenAccess API |
| Crossref | yes | – | – | yes | – | yes | none | DOI metadata + publisher TDM routes |
| Unpaywall | – | – | – | – | yes | – | none | authoritative OA locations |
| Europe PMC | yes | yes | – | yes | yes | – | none | key-free OA **JATS full text** |

**Credential-free providers** (`requires_credential = false`) are never prompted for a key in the
dashboard. Unpaywall stays inert until a `contact_email` is configured, as its API terms require.

A credential may declare a `services` allowlist. This exists because some providers issue a separate
key per API (Springer Meta vs OpenAlex-style OpenAccess); the pool then pairs each service with the
correct key instead of using them interchangeably.

Adding a provider means implementing the protocol and registering a factory in
`ServiceContainer._build_providers`. The resolver, acquisition service, scheduler, and API do not
change.

## Document parsing

Normalization is format-driven, not provider-hardcoded. `NormalizationService` delegates to a
`ParserRegistry` that selects a deterministic parser from the payload's format plus a cheap content
sniff, so a new source format is a parser change and not a workflow change:

```text
raw bytes + format + provider hint
   ↓
ParserRegistry.select()
   ↓
Elsevier FULL XML | JATS XML | HTML | PDF text layer
   ↓
PaperDocument (with provenance.parser_version)
```

Selection order favors a provider-specific parser when it matches the content, then falls back to
any parser whose `sniff` accepts it. A payload no parser claims raises `UnsupportedFormatError`,
which acquisition treats as a **soft** failure: the raw file is kept and the paper is left
un-normalized rather than mis-parsed.

**PDF handling is text-layer extraction only, never OCR.** An image-only PDF yields little text and
is flagged with an `needs_ocr` attachment instead of a silently empty document. OCR is out of scope
for this version and reserved for a later, separate stage.

See [PARSING.md](PARSING.md) for the full parser inventory and how to add one.

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
