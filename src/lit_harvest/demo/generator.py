"""Generate a complete, offline demo corpus (no API key required)."""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape
from pathlib import Path

from lit_harvest.demo.data import DEMO_PAPERS, DemoPaper
from lit_harvest.models import (
    DownloadStatus,
    JobCreate,
    JobStatus,
    PaperCreate,
    PaperIdentifiers,
    PaperStage,
    QuotaScope,
    QuotaSource,
    QuotaStatus,
    QuotaUpdate,
    TaskType,
)
from lit_harvest.services.container import ServiceContainer


@dataclass(slots=True)
class DemoResult:
    created_papers: int
    skipped_papers: int
    created_jobs: int
    files: list[str]
    data_dir: str
    database: str


def _raw_xml(paper: DemoPaper) -> bytes:
    """Build a ScienceDirect-shaped FULL XML so the real parser can read it."""
    authors = "\n".join(
        "    <author>"
        f"<ce:given-name>{escape(author.split()[0])}</ce:given-name>"
        f"<ce:surname>{escape(' '.join(author.split()[1:]))}</ce:surname>"
        "</author>"
        for author in paper.authors
    )
    keywords = "\n".join(f"    <keyword>{escape(word)}</keyword>" for word in paper.keywords)
    sections = "\n".join(
        f"""  <section id="sec{index}">
    <title>{escape(title)}</title>
    {"".join(f"<para>{escape(para)}</para>" for para in paragraphs)}
  </section>"""
        for index, (title, paragraphs) in enumerate(paper.sections, start=1)
    )
    references = "\n".join(
        f"""    <reference id="ref{index}">
      <doi>{escape(doi)}</doi>
      <title>{escape(ref_title)}</title>
      <journal>{escape(journal)}</journal>
      <year>{escape(year)}</year>
    </reference>"""
        for index, (doi, ref_title, journal, year) in enumerate(paper.references, start=1)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<full-text-retrieval-response
  xmlns:ce="http://www.elsevier.com/xml/ani/common"
  xmlns:xocs="http://www.elsevier.com/xml/xocs/dtd"
  xmlns:dc="http://purl.org/dc/elements/1.1/"
  xmlns:prism="http://prismstandard.org/namespaces/basic/2.0/">
  <coredata>
    <dc:identifier>doi:{escape(paper.doi)}</dc:identifier>
    <dc:title>{escape(paper.title)}</dc:title>
    <prism:publicationName>{escape(paper.journal)}</prism:publicationName>
    <prism:coverDate>{paper.year}-01-01</prism:coverDate>
    <prism:doi>{escape(paper.doi)}</prism:doi>
    <openaccess>1</openaccess>
  </coredata>
  <xocs:meta>
    <xocs:document-type>{escape(paper.document_type)}</xocs:document-type>
    <xocs:date-received>{paper.year}-01-02</xocs:date-received>
  </xocs:meta>
  <abstract>
    <ce:abstract-sec><ce:simple-para>{escape(paper.abstract)}</ce:simple-para></ce:abstract-sec>
  </abstract>
  <authors>
{authors}
  </authors>
  <keywords>
{keywords}
  </keywords>
  <body>
{sections}
  </body>
  <bibliography>
{references}
  </bibliography>
</full-text-retrieval-response>
""".encode()


def generate_demo_data(container: ServiceContainer) -> DemoResult:
    """Populate the current instance with a small, fully offline corpus."""
    created_papers = 0
    skipped_papers = 0
    created_jobs = 0
    files: list[str] = []

    for paper in DEMO_PAPERS:
        existing = container.database.get_paper_by_doi(paper.doi)
        if existing is not None and existing.extra.get("demo"):
            skipped_papers += 1
            continue

        record = existing or container.database.create_paper(
            PaperCreate(
                doi=paper.doi,
                title=paper.title,
                journal=paper.journal,
                publication_year=paper.year,
                publisher=paper.publisher,
                document_type=paper.document_type,
                discovery_source="demo",
                identifiers=PaperIdentifiers(doi=paper.doi),
                extra={"demo": True},
            )
        )
        if existing is None:
            created_papers += 1

        # Raw source, exactly as a real download would be stored.
        xml = _raw_xml(paper)
        raw_path = container.storage.write_raw(paper.doi, "elsevier_xml.xml", xml)
        files.append(str(raw_path))
        container.database.record_download(
            paper_id=record.id,
            provider="elsevier",
            service="article_retrieval",
            credential_id=None,
            status=DownloadStatus.SUCCESS.value,
            format="xml",
            raw_path=str(raw_path),
            checksum=hashlib.sha256(xml).hexdigest(),
            http_status=200,
        )

        # Normalized output through the real parser, not a stub.
        container.normalization.normalize(
            content=xml,
            doi=paper.doi,
            paper_id=record.id,
            source_path=str(raw_path),
            credential_label="demo",
            http_status=200,
        )
        container.storage.write_state(
            paper.doi,
            {
                "stage": PaperStage.NORMALIZED.value,
                "doi": paper.doi,
                "raw_path": str(raw_path),
                "provider": "elsevier",
                "service": "article_retrieval",
                "credential_label": "demo",
                "http_status": 200,
                "demo": True,
                "updated_at": datetime.now(UTC).isoformat(),
            },
        )
        container.database.set_paper_stage(record.id, PaperStage.READY)

        job = container.database.create_job(
            JobCreate(
                task_type=TaskType.FETCH_FULLTEXT,
                paper_id=record.id,
                provider="elsevier",
                service="article_retrieval",
                payload={"doi": paper.doi, "demo": True},
            )
        )
        container.database.update_job_status(job.id, JobStatus.SUCCESS)
        created_jobs += 1

    # A realistic quota snapshot so the Providers page is not empty.
    container.database.upsert_quota(
        QuotaUpdate(
            provider="elsevier",
            service="scopus_search",
            credential_id=None,
            limit=20_000,
            remaining=19_750,
            source=QuotaSource.LOCAL_ESTIMATE,
            quota_scope=QuotaScope.INSTITUTION,
            status=QuotaStatus.HEALTHY,
        )
    )
    container.database.upsert_quota(
        QuotaUpdate(
            provider="elsevier",
            service="article_retrieval",
            credential_id=None,
            limit=10_000,
            remaining=9_120,
            source=QuotaSource.LOCAL_ESTIMATE,
            quota_scope=QuotaScope.INSTITUTION,
            status=QuotaStatus.HEALTHY,
        )
    )

    return DemoResult(
        created_papers=created_papers,
        skipped_papers=skipped_papers,
        created_jobs=created_jobs,
        files=files,
        data_dir=str(container.config.storage.root),
        database=container.config.database.url,
    )


def clear_demo_data(container: ServiceContainer) -> int:
    """Remove only rows and files created by the demo generator."""
    removed = 0
    for paper in container.database.list_papers(limit=10_000):
        if not paper.extra.get("demo"):
            continue
        paper_dir: Path | None = None
        if paper.doi:
            paper_dir = container.storage.paper_dir(paper.doi)
            container.database.add_paper_extra(paper.id, {"normalized_path": None})
        if paper_dir and paper_dir.exists():
            shutil.rmtree(paper_dir, ignore_errors=True)
        container.database.delete_paper(paper.id)
        removed += 1
    return removed
