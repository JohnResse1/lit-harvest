# Local API

Run with:

```bash
lit-harvest ui
```

Interactive schema: `http://127.0.0.1:8765/docs`

The server binds `127.0.0.1` only. There is no authentication because it is not reachable from
other machines; non-loopback binds are refused unless explicitly overridden.

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
```

## Search review flow

`POST /api/search` only previews results — it never downloads full text.

1. `POST /api/search` returns `session_id` plus `candidates` with metadata.
2. Choose rows (in the dashboard) or send candidate ids to `.../select`.
3. `POST /api/search/sessions/{session_id}/download` fetches only the chosen candidates.

Candidate metadata fields: `title`, `doi`, `journal`, `year`, `authors`, `affiliation`,
`document_type`, `citation_count`, `open_access`, `free_to_read`, `issn`, `volume`, `issue`,
`pages`, `cover_date`, `scopus_id`, `eid`, `scopus_url`.

Note: Scopus Search `STANDARD` exposes only the first author (`dc:creator`), so `authors` holds a
single name rather than a full author list.

## Error handling

Provider failures are translated into short, readable messages. Raw publisher payloads (for example
Elsevier `<service-error>` XML) are never forwarded to the browser.

| HTTP | Meaning |
| --- | --- |
| `404` | DOI not found in ScienceDirect |
| `401` | API key rejected |
| `403` | Account not entitled to this content |
| `422` | Invalid input (bad DOI string, missing CSV column, invalid max_results) |
| `502` | Publisher or network failure |

## UI routes

```text
/             Overview
/papers       Papers, DOI entry, batch import, search review
/papers/:id   Paper detail
/providers    Provider → service → credential quota view
/failures     Failure center and queue controls
/storage      Storage directory settings
```
