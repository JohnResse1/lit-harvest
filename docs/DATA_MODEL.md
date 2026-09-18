# Data Model

## Core entities

`Paper` is the scholarly registry record: DOI, title, journal, year, publisher, document type,
discovery source, lifecycle stage, and cross-provider identifiers.

`Job` is every unit of long-running work: task type, provider/service, credential, priority, status,
attempts, retry timing, and correlated failure fields.

`Provider` is the external service registry. It owns service health such as Scopus Search and
ScienceDirect Article Retrieval.

`Credential` records only metadata: label, auth type, environment secret reference, institution,
account, quota scope, and health. Secret values are never persisted.

`QuotaState` tracks provider → service → credential limits, remaining units, reset time, scope,
source (response header/local estimate/manual/unknown), and status.

`PaperDocument` is provider-independent normalized content: identifiers, bibliographic metadata,
dates, authors, affiliations, abstract, keywords, OA metadata, sections, figures, tables, equations,
references, attachments, and provenance.

## SQLite tables

```text
papers
paper_identifiers
jobs
downloads
providers
provider_services
credentials
quota_states
provider_events
```

No entity, relation, scientific-record, vector, or graph tables exist in v0.1.
