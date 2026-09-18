# Literature Harvester

[English](README.md) | [简体中文](README-ZH.md)

Local-first academic literature discovery, acquisition, raw preservation, and deterministic
normalization. v0.1 implements the acquisition and structured-corpus foundation and deliberately
stops before LLM extraction and knowledge graphs.

## What It Does

Literature Harvester lets one researcher:

1. Search literature with Elsevier Scopus Search STANDARD.
2. Import DOI lists from CSV, TSV, TXT, JSON, and JSONL.
3. Resolve and retrieve legally accessible publisher full text.
4. Preserve raw publisher responses without loss.
5. Normalize Elsevier ScienceDirect FULL XML into a provider-independent `PaperDocument`.
6. Track credentials, quotas, retries, failures, and resumable jobs.
7. Inspect the corpus through a CLI and a local web dashboard.

The system is provider-aware internally but provider-agnostic to the user. Acquisition and
normalization are intentionally decoupled from later scientific understanding.

## Features

- Scopus Search STANDARD discovery with cursor pagination
- ScienceDirect FULL XML retrieval
- Optional publisher PDF download, preserved as a separate raw attachment
- Provider abstraction, credential metadata, health, and quota monitoring
- Quota-aware SQLite job queue with retry and resume states
- DOI import from CSV, TSV, TXT, JSON, and JSONL
- Deterministic Elsevier FULL XML to `PaperDocument` normalization
- Typer CLI and React/FastAPI local dashboard
- Server-Sent Events (SSE) for live dashboard updates
- Provider → service → credential quota visibility
- Failure center with pause, resume, retry, and cancel controls
- Project-local secret storage without exporting API keys

PDF OCR is not performed; PDFs are preserved as raw attachments for entitlement-respecting use.

Not implemented in v0.1: LLM extraction, materials NER, relation extraction, knowledge graphs,
Neo4j, vector databases, research-gap discovery, hypothesis generation, OCR, scraping, cloud
deployment, authentication, and UI secret editing.

## Requirements

- Python 3.11+
- An Elsevier API key with the access your institution or account is authorized to use
- Node.js only when rebuilding the frontend from source

The packaged UI is prebuilt, so normal users do not need Node.js.

## Quick Start

### 1. Enter the project

```bash
cd /path/to/lit-harvest
```

### 2. Install

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
cp config.example.yaml config.yaml
```

### 3. Store your Elsevier credential

The recommended workflow keeps the secret inside this project:

```bash
.venv/bin/lit-harvest auth set elsevier university_primary
```

The command prompts with hidden input:

```text
API key for elsevier/university_primary:
```

The secret is stored at:

```text
<project>/.lit-harvest/secrets.json
```

The file is created with permission `0600`, and `.lit-harvest/` is ignored by Git.

The secret is not written to:

- `config.yaml`
- SQLite
- logs
- API responses
- browser state

`config.yaml` contains only a reference:

```yaml
providers:
  elsevier:
    credentials:
      - name: university_primary
        secret_ref: file:elsevier:university_primary
```

### 4. Verify

```bash
.venv/bin/lit-harvest auth list
.venv/bin/lit-harvest doctor
.venv/bin/lit-harvest doctor --network
```

If no credential is configured, `doctor` exits nonzero by design.

## Common Workflows

### Search for a topic

```bash
.venv/bin/lit-harvest search \
  --query 'TITLE-ABS-KEY("solid-state battery")' \
  --max-results 100
```

Optional year limiting and export:

```bash
.venv/bin/lit-harvest search \
  --query 'TITLE-ABS-KEY("solid-state electrolyte")' \
  --max-results 500 \
  --start-year 2020 \
  --end-year 2026 \
  --export papers.jsonl
```

### Fetch one DOI

```bash
.venv/bin/lit-harvest fetch 10.1016/j.mtcomm.2026.115551
```

### Download the publisher PDF as well

```bash
.venv/bin/lit-harvest fetch 10.1016/j.mtcomm.2026.115551 --pdf
```

PDFs are supplementary raw attachments. FULL XML remains the canonical normalization source. If PDF
download is unavailable or not entitled, XML retrieval still succeeds and the JSON result contains a
`pdf_error` field.

To enable PDFs for every fetch, set:

```yaml
providers:
  elsevier:
    download_pdf: true
```

### Import a DOI file

```bash
.venv/bin/lit-harvest fetch papers.csv --doi-column doi
```

Supported formats:

```text
.csv
.tsv
.txt
.json
.jsonl
```

DOI variants are normalized and deduplicated:

```text
10.1016/j.xxx
https://doi.org/10.1016/j.xxx
http://dx.doi.org/10.1016/j.xxx
doi:10.1016/j.xxx
DOI: 10.1016/j.xxx
```

Invalid values are reported without terminating the batch.

### Parse downloaded raw XML

```bash
.venv/bin/lit-harvest parse
```

This re-normalizes downloaded raw files without downloading the article again.

### Launch the local dashboard

```bash
.venv/bin/lit-harvest ui
```

Default address:

```text
http://127.0.0.1:8765
```

API documentation:

```text
http://127.0.0.1:8765/docs
```

## CLI Reference

```text
lit-harvest version
lit-harvest auth set [provider] [name] [--secret-ref REF] [--config PATH]
lit-harvest auth list [--config PATH]
lit-harvest auth test [provider] [name] [--config PATH]
lit-harvest auth remove [provider] [name] [--secret-ref REF] [--config PATH]
lit-harvest doctor [--network] [--json] [--config PATH]

lit-harvest search --query QUERY --max-results N [--start-year N] [--end-year N]
                   [--export PATH] [--config PATH]

lit-harvest fetch DOI|FILE [--doi-column COLUMN] [--pdf|--no-pdf] [--config PATH]
lit-harvest parse [--limit N] [--config PATH]
lit-harvest export PATH [--format csv|json|jsonl] [--config PATH]
lit-harvest jobs [--status STATUS] [--limit N] [--config PATH]
lit-harvest quota [--config PATH]
lit-harvest pause [--reason TEXT] [--config PATH]
lit-harvest resume [--config PATH]
lit-harvest retry --job-id ID | --transient [--config PATH]
lit-harvest ui [--host HOST] [--port PORT] [--config PATH]
```

## Configuration

Start from [`config.example.yaml`](config.example.yaml).

Example:

```yaml
storage:
  root: ./data

database:
  url: sqlite:///./data/lit_harvest.db

scheduler:
  retry:
    max_attempts: 4
    base_delay_seconds: 2

  rate_limit:
    respect_retry_after: true

  quota:
    warning_ratio: 0.30
    low_ratio: 0.10

server:
  host: 127.0.0.1
  port: 8765

providers:
  elsevier:
    enabled: true

    services:
      scopus_search:
        enabled: true

      article_retrieval:
        enabled: true

    credentials:
      - name: university_primary
        secret_ref: file:elsevier:university_primary
        institution: HIT
        quota_scope: institution
```

### Secret reference formats

```text
file:provider:name         recommended project-local 0600 secret file
keychain:service:account   optional macOS Keychain / OS keyring
env:NAME                   legacy CI/container compatibility
```

The legacy `api_key_env` field remains supported for existing deployments, but it is not the
recommended local workflow.

### Optional keychain mode

To use the operating system keyring instead of the project file:

```bash
export LIT_HARVEST_SECRET_BACKEND=keychain
.venv/bin/lit-harvest auth set elsevier university_primary \
  --secret-ref keychain:lit-harvest.elsevier:university_primary
```

## Credential and Quota Policy

Credential failover is intentionally conservative.

- Institution-scoped quota exhaustion blocks other credentials in the same institution.
- Account, provider, and unknown scopes also block credential rotation.
- Only independently authorized credentials may fail over.
- HTTP 429, timeouts, 500, 502, 503, and 504 retry with bounded backoff.
- HTTP 400, 401, 403, and 404 are not endlessly retried.
- The system never uses credential rotation to bypass provider or institutional quotas.

## Storage Layout

```text
data/
├── lit_harvest.db
├── exports/
└── papers/
    └── 10.1016_j.example/
        ├── raw/
        │   ├── elsevier_xml.xml
        │   └── elsevier_pdf.pdf        # optional
        ├── normalized/
        │   └── paper.json
        └── state.json
```

Project-local secrets are stored separately:

```text
.lit-harvest/
└── secrets.json
```

Raw publisher data is never discarded when parsing rules evolve.

## Local API

```text
GET  /api/health
GET  /api/overview
GET  /api/doctor

GET  /api/papers
POST /api/papers/import
POST /api/papers/doi
GET  /api/papers/export
GET  /api/papers/{paper_id}

GET  /api/providers
GET  /api/providers/quotas

GET  /api/jobs
POST /api/jobs/{job_id}/retry
POST /api/jobs/{job_id}/cancel
GET  /api/failures
POST /api/failures/retry-transient

POST /api/queue/pause
POST /api/queue/resume

GET  /api/events
```

## UI Pages

```text
/             Overview
/papers       Papers and lifecycle state
/papers/:id   Paper detail
/providers    Provider, service, credential, and quota view
/failures     Failure center and queue controls
```

## Development

Run tests and static checks:

```bash
.venv/bin/pytest
.venv/bin/ruff check src/lit_harvest tests
.venv/bin/mypy src/lit_harvest
```

Rebuild the frontend after changing React or TypeScript code:

```bash
./scripts/build_frontend.sh
```

The script uses the Codex-bundled Node runtime when `node` is not on `PATH`.

## Open Source / GitHub

The repository is ready for a private GitHub remote. Before the first push:

```bash
lit-harvest security scan
git check-ignore -v .lit-harvest/secrets.json config.yaml data/lit_harvest.db .env
git status --short
```

Then follow [docs/PUBLISHING.md](docs/PUBLISHING.md). The repository includes CI, `SECURITY.md`,
`CONTRIBUTING.md`, and `CODE_OF_CONDUCT.md`.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Data model](docs/DATA_MODEL.md)
- [Local API](docs/API.md)
- [Operations](docs/OPERATIONS.md)
- [简体中文 README](README-ZH.md)

## Scope

Implemented in v0.1:

- provider abstraction
- credential metadata and project-local secrets
- quota model and manager
- scheduler and resumable job queue
- SQLite operational state
- raw document storage
- DOI import
- Scopus Search STANDARD
- ScienceDirect FULL XML retrieval
- Optional publisher PDF download, preserved as a separate raw attachment
- deterministic Elsevier FULL XML normalization
- CLI
- FastAPI backend
- React dashboard
- SSE updates
- pause, resume, retry, and cancel controls

Deliberately excluded from v0.1:

- LLM extraction
- materials NER
- experimental relation extraction
- knowledge graphs
- Neo4j
- vector databases
- research-gap engine
- hypothesis generation
- PDF OCR
- browser scraping
- cloud deployment
- SaaS
- user login
- secret editing in the UI
- unrestricted key rotation
- broad multi-publisher integration

## License

[MIT](LICENSE)
