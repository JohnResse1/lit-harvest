# Local API

Run with:

```bash
lit-harvest ui
```

Interactive schema: `http://127.0.0.1:8765/docs`

## Endpoints

```text
GET  /api/health
GET  /api/instance
GET  /api/overview
GET  /api/doctor?network=false
GET  /api/worker
POST /api/worker/tick

GET  /api/papers?limit=&offset=&stage=
POST /api/papers/import?doi_column=doi&run_now=true&download_pdf=false
POST /api/papers/doi
GET  /api/papers/export?format=csv|json|jsonl&download=true
GET  /api/papers/import/sample.csv
GET  /api/papers/{paper_id}
GET  /api/papers/{paper_id}/download/xml|pdf|normalized
POST /api/papers/download/zip

POST /api/search
GET  /api/search?query=&max_results=
GET  /api/search/sessions
GET  /api/search/sessions/{session_id}
POST /api/search/sessions/{session_id}/select
POST /api/search/sessions/{session_id}/download

GET  /api/settings/storage
GET  /api/settings/storage/validate?path=
POST /api/settings/storage
POST /api/settings/storage/reset

GET  /api/providers
GET  /api/providers/quotas

GET  /api/jobs?limit=&offset=&status=&task_type=
POST /api/jobs/{job_id}/retry
POST /api/jobs/{job_id}/cancel
GET  /api/failures
POST /api/failures/retry-transient

POST /api/queue/pause
POST /api/queue/resume

GET  /api/events          # Server-Sent Events
```text
GET  /api/health
GET  /api/overview
GET  /api/doctor?network=false

GET  /api/papers?limit=&offset=&stage=
POST /api/papers/import
POST /api/papers/doi
GET  /api/papers/export?format=csv|json|jsonl
GET  /api/papers/{paper_id}

GET  /api/providers
GET  /api/providers/quotas

GET  /api/jobs?limit=&offset=&status=&task_type=
POST /api/jobs/{job_id}/retry
POST /api/jobs/{job_id}/cancel
GET  /api/failures
POST /api/failures/retry-transient

POST /api/queue/pause
POST /api/queue/resume

GET  /api/events
```

`/api/events` is a Server-Sent Events stream. The frontend subscribes to it for automatic updates.

## UI routes

```text
/             Overview
/papers       Paper lifecycle and filtering
/papers/:id   Acquisition, parsing, identifiers, local paths
/providers    Provider → service → credential quota monitoring
/failures     Failure center and queue controls
```
