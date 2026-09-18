"""SQLite persistence for literature harvesting state."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    delete,
    event,
    func,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)

from lit_harvest.models.document import PaperDocument
from lit_harvest.models.enums import (
    HealthStatus,
    JobStatus,
    PaperStage,
    QuotaScope,
    QuotaSource,
    QuotaStatus,
    TaskType,
)
from lit_harvest.models.job import Job, JobCreate
from lit_harvest.models.paper import Paper, PaperCreate, PaperIdentifiers
from lit_harvest.models.quota import QuotaState, QuotaUpdate


def utc_now() -> datetime:
    return datetime.now(UTC)


def aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def new_id() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class PaperRow(Base):
    __tablename__ = "papers"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    doi: Mapped[str | None] = mapped_column(String(512), unique=True, nullable=True, index=True)
    title: Mapped[str | None] = mapped_column(Text)
    journal: Mapped[str | None] = mapped_column(Text)
    publication_year: Mapped[int | None] = mapped_column(Integer)
    publisher: Mapped[str | None] = mapped_column(String(256))
    document_type: Mapped[str | None] = mapped_column(String(128))
    discovery_source: Mapped[str | None] = mapped_column(String(128))
    stage: Mapped[str] = mapped_column(String(64), default=PaperStage.DISCOVERED.value, index=True)
    extra_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    identifiers: Mapped[list[PaperIdentifierRow]] = relationship(
        back_populates="paper", cascade="all, delete-orphan", lazy="selectin"
    )


class PaperIdentifierRow(Base):
    __tablename__ = "paper_identifiers"
    __table_args__ = (UniqueConstraint("scheme", "value", name="uq_identifier_value"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), index=True)
    scheme: Mapped[str] = mapped_column(String(64), index=True)
    value: Mapped[str] = mapped_column(String(512), index=True)

    paper: Mapped[PaperRow] = relationship(back_populates="identifiers")


class JobRow(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    paper_id: Mapped[str | None] = mapped_column(
        ForeignKey("papers.id", ondelete="SET NULL"), index=True
    )
    task_type: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str | None] = mapped_column(String(64), index=True)
    service: Mapped[str | None] = mapped_column(String(64), index=True)
    credential_id: Mapped[str | None] = mapped_column(String(32), index=True)
    priority: Mapped[int] = mapped_column(Integer, default=100, index=True)
    status: Mapped[str] = mapped_column(String(64), default=JobStatus.PENDING.value, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")


class DownloadRow(Base):
    __tablename__ = "downloads"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    paper_id: Mapped[str | None] = mapped_column(
        ForeignKey("papers.id", ondelete="SET NULL"), index=True
    )
    provider: Mapped[str] = mapped_column(String(64), index=True)
    service: Mapped[str] = mapped_column(String(64), index=True)
    credential_id: Mapped[str | None] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(64), index=True)
    http_status: Mapped[int | None] = mapped_column(Integer)
    format: Mapped[str] = mapped_column(String(64))
    raw_path: Mapped[str | None] = mapped_column(Text)
    checksum: Mapped[str | None] = mapped_column(String(64))
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)


class ProviderRow(Base):
    __tablename__ = "providers"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(128))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    health_status: Mapped[str] = mapped_column(String(32), default=HealthStatus.UNKNOWN.value)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    message: Mapped[str | None] = mapped_column(Text)
    services: Mapped[list[ProviderServiceRow]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )


class ProviderServiceRow(Base):
    __tablename__ = "provider_services"
    __table_args__ = (UniqueConstraint("provider", "name", name="uq_provider_service"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(
        ForeignKey("providers.name", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    health_status: Mapped[str] = mapped_column(String(32), default=HealthStatus.UNKNOWN.value)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    message: Mapped[str | None] = mapped_column(Text)


class CredentialRow(Base):
    __tablename__ = "credentials"
    __table_args__ = (UniqueConstraint("provider", "name", name="uq_provider_credential"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(128))
    auth_type: Mapped[str] = mapped_column(String(32), default="api_key")
    secret_ref: Mapped[str] = mapped_column(String(256))
    account_label: Mapped[str | None] = mapped_column(String(128))
    institution: Mapped[str | None] = mapped_column(String(128))
    quota_scope: Mapped[str] = mapped_column(String(32), default=QuotaScope.UNKNOWN.value)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    health_status: Mapped[str] = mapped_column(String(32), default=HealthStatus.UNKNOWN.value)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QuotaStateRow(Base):
    __tablename__ = "quota_states"
    __table_args__ = (
        UniqueConstraint("provider", "service", "credential_id", name="uq_quota_scope"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    service: Mapped[str] = mapped_column(String(64), index=True)
    credential_id: Mapped[str | None] = mapped_column(String(32), index=True)
    limit: Mapped[int | None] = mapped_column(Integer)
    remaining: Mapped[int | None] = mapped_column(Integer)
    reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    source: Mapped[str] = mapped_column(String(32), default=QuotaSource.UNKNOWN.value)
    quota_scope: Mapped[str] = mapped_column(String(32), default=QuotaScope.UNKNOWN.value)
    status: Mapped[str] = mapped_column(String(32), default=QuotaStatus.UNKNOWN.value)
    message: Mapped[str | None] = mapped_column(Text)


class ProviderEventRow(Base):
    __tablename__ = "provider_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    service: Mapped[str | None] = mapped_column(String(64), index=True)
    credential_id: Mapped[str | None] = mapped_column(String(32), index=True)
    paper_id: Mapped[str | None] = mapped_column(String(32), index=True)
    job_id: Mapped[str | None] = mapped_column(String(32), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    level: Mapped[str] = mapped_column(String(16), default="info")
    http_status: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    retry_attempt: Mapped[int | None] = mapped_column(Integer)
    message: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True
    )


def _json_load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


class Database:
    """Thin repository layer around a SQLAlchemy SQLite engine."""

    def __init__(self, url: str):
        connect_args: dict[str, Any] = {}
        if url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        self.engine: Engine = create_engine(url, connect_args=connect_args, future=True)
        if url.startswith("sqlite"):
            event.listen(self.engine, "connect", self._configure_sqlite)
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False, future=True)

    @staticmethod
    def _configure_sqlite(dbapi_connection: Any, _connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    def initialize(self) -> None:
        if self.engine.url.database and self.engine.url.database != ":memory:":
            Path(self.engine.url.database).expanduser().parent.mkdir(parents=True, exist_ok=True)
        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    def healthcheck(self) -> tuple[bool, str]:
        try:
            with self.session() as session:
                session.execute(select(func.count()).select_from(PaperRow))
        except Exception as exc:  # pragma: no cover - defensive health path
            return False, str(exc)
        return True, str(self.engine.url)

    # Papers

    def create_paper(self, value: PaperCreate) -> Paper:
        with self.session() as session:
            return self._create_paper(session, value)

    def _create_paper(self, session: Session, value: PaperCreate) -> Paper:
        identifiers = value.identifiers
        if value.doi and not identifiers.doi:
            identifiers = identifiers.model_copy(update={"doi": value.doi})
        normalized_doi = value.doi
        if identifiers.doi:
            from lit_harvest.storage.files import normalize_doi

            normalized_doi = normalize_doi(identifiers.doi)
        row = PaperRow(
            doi=normalized_doi,
            title=value.title,
            journal=value.journal,
            publication_year=value.publication_year,
            publisher=value.publisher,
            document_type=value.document_type,
            discovery_source=value.discovery_source,
            extra_json=json.dumps(value.extra, default=str),
        )
        session.add(row)
        session.flush()
        for scheme, identifier in identifiers.as_pairs():
            normalized = normalize_doi(identifier) if scheme == "doi" else identifier.strip()
            exists = session.scalar(
                select(PaperIdentifierRow).where(
                    PaperIdentifierRow.scheme == scheme, PaperIdentifierRow.value == normalized
                )
            )
            if exists:
                continue
            session.add(PaperIdentifierRow(paper_id=row.id, scheme=scheme, value=normalized))
        session.flush()
        return self._paper_from_row(row)

    def upsert_paper(self, value: PaperCreate) -> Paper:
        existing = self.get_paper_by_doi(value.doi) if value.doi else None
        if existing is None:
            return self.create_paper(value)
        return self.update_paper_metadata(existing.id, value)

    def get_paper(self, paper_id: str) -> Paper | None:
        with self.session() as session:
            row = session.get(PaperRow, paper_id)
            return self._paper_from_row(row) if row else None

    def get_paper_by_doi(self, doi: str) -> Paper | None:
        from lit_harvest.storage.files import normalize_doi

        normalized = normalize_doi(doi)
        with self.session() as session:
            row = session.scalar(select(PaperRow).where(PaperRow.doi == normalized))
            return self._paper_from_row(row) if row else None

    def get_paper_by_identifier(self, scheme: str, value: str) -> Paper | None:
        with self.session() as session:
            identifier = session.scalar(
                select(PaperIdentifierRow).where(
                    PaperIdentifierRow.scheme == scheme, PaperIdentifierRow.value == value
                )
            )
            if not identifier:
                return None
            row = session.get(PaperRow, identifier.paper_id)
            return self._paper_from_row(row) if row else None

    def update_paper_metadata(self, paper_id: str, value: PaperCreate) -> Paper:
        with self.session() as session:
            row = session.get(PaperRow, paper_id)
            if row is None:
                raise KeyError(f"Paper not found: {paper_id}")
            normalized_doi = row.doi
            identifiers = value.identifiers
            if value.doi:
                from lit_harvest.storage.files import normalize_doi

                normalized_doi = normalize_doi(value.doi)
                identifiers = identifiers.model_copy(update={"doi": normalized_doi})
            row.doi = normalized_doi
            for field in (
                "title",
                "journal",
                "publication_year",
                "publisher",
                "document_type",
                "discovery_source",
            ):
                incoming = getattr(value, field)
                if incoming is not None:
                    setattr(row, field, incoming)
            if value.extra:
                existing_extra = _json_load(row.extra_json, {})
                existing_extra.update(value.extra)
                row.extra_json = json.dumps(existing_extra, default=str)
            row.updated_at = utc_now()
            for scheme, identifier in identifiers.as_pairs():
                normalized = normalize_doi(identifier) if scheme == "doi" else identifier.strip()
                exists = session.scalar(
                    select(PaperIdentifierRow).where(
                        PaperIdentifierRow.scheme == scheme, PaperIdentifierRow.value == normalized
                    )
                )
                if not exists:
                    session.add(
                        PaperIdentifierRow(paper_id=row.id, scheme=scheme, value=normalized)
                    )
            session.flush()
            return self._paper_from_row(row)

    def set_paper_stage(self, paper_id: str, stage: PaperStage) -> None:
        with self.session() as session:
            row = session.get(PaperRow, paper_id)
            if row is None:
                raise KeyError(f"Paper not found: {paper_id}")
            row.stage = stage.value
            row.updated_at = utc_now()

    def list_papers(
        self, *, limit: int = 100, offset: int = 0, stage: PaperStage | None = None
    ) -> list[Paper]:
        statement = (
            select(PaperRow).order_by(PaperRow.created_at.desc()).offset(offset).limit(limit)
        )
        if stage:
            statement = statement.where(PaperRow.stage == stage.value)
        with self.session() as session:
            return [self._paper_from_row(row) for row in session.scalars(statement).all()]

    def count_papers(self, stage: PaperStage | None = None) -> int:
        statement = select(func.count()).select_from(PaperRow)
        if stage:
            statement = statement.where(PaperRow.stage == stage.value)
        with self.session() as session:
            return int(session.scalar(statement) or 0)

    def _paper_from_row(self, row: PaperRow) -> Paper:
        identifiers = PaperIdentifiers()
        for item in row.identifiers:
            if item.scheme in {
                "doi",
                "scopus_id",
                "eid",
                "pii",
                "pmid",
                "openalex_id",
                "semantic_scholar_id",
            }:
                setattr(identifiers, item.scheme, item.value)
            elif item.scheme.startswith("publisher:"):
                identifiers.publisher_specific[item.scheme.split(":", 1)[1]] = item.value
        if row.doi and not identifiers.doi:
            identifiers.doi = row.doi
        return Paper(
            id=row.id,
            doi=row.doi,
            title=row.title,
            journal=row.journal,
            publication_year=row.publication_year,
            publisher=row.publisher,
            document_type=row.document_type,
            discovery_source=row.discovery_source,
            identifiers=identifiers,
            extra=_json_load(row.extra_json, {}),
            stage=row.stage,
            created_at=aware(row.created_at) or utc_now(),
            updated_at=aware(row.updated_at) or utc_now(),
        )

    # Jobs

    def create_job(self, value: JobCreate, *, deduplicate: bool = True) -> Job:
        with self.session() as session:
            if deduplicate:
                active = (
                    JobStatus.PENDING.value,
                    JobStatus.RUNNING.value,
                    JobStatus.RETRY.value,
                    JobStatus.WAITING_FOR_QUOTA.value,
                )
                existing = session.scalar(
                    select(JobRow).where(
                        JobRow.task_type == value.task_type.value,
                        JobRow.paper_id == value.paper_id,
                        JobRow.provider == value.provider,
                        JobRow.service == value.service,
                        JobRow.status.in_(active),
                    )
                )
                if existing:
                    return self._job_from_row(existing)
            row = JobRow(
                paper_id=value.paper_id,
                task_type=value.task_type.value,
                provider=value.provider,
                service=value.service,
                credential_id=value.credential_id,
                priority=value.priority,
                max_attempts=value.max_attempts,
                payload_json=json.dumps(value.payload, default=str),
            )
            session.add(row)
            session.flush()
            return self._job_from_row(row)

    def get_job(self, job_id: str) -> Job | None:
        with self.session() as session:
            row = session.get(JobRow, job_id)
            return self._job_from_row(row) if row else None

    def claim_next_job(self, *, task_types: Sequence[TaskType] | None = None) -> Job | None:
        now = utc_now()
        with self.session() as session:
            statement = (
                select(JobRow)
                .where(
                    JobRow.status.in_((JobStatus.PENDING.value, JobStatus.RETRY.value)),
                    (JobRow.next_retry_at.is_(None)) | (JobRow.next_retry_at <= now),
                )
                .order_by(JobRow.priority.asc(), JobRow.created_at.asc())
                .limit(1)
            )
            if task_types:
                statement = statement.where(
                    JobRow.task_type.in_([item.value for item in task_types])
                )
            row = session.scalar(statement)
            if row is None:
                return None
            row.status = JobStatus.RUNNING.value
            row.started_at = now
            row.attempts += 1
            session.flush()
            return self._job_from_row(row)

    def update_job_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
        next_retry_at: datetime | None = None,
        credential_id: str | None = None,
    ) -> Job:
        with self.session() as session:
            row = session.get(JobRow, job_id)
            if row is None:
                raise KeyError(f"Job not found: {job_id}")
            row.status = status.value
            row.error_code = error_code
            row.error_message = error_message
            row.next_retry_at = next_retry_at
            if credential_id is not None:
                row.credential_id = credential_id
            if status in {
                JobStatus.SUCCESS,
                JobStatus.CANCELLED,
                JobStatus.FAILED,
                JobStatus.NOT_ENTITLED,
                JobStatus.NOT_FOUND,
                JobStatus.BLOCKED,
            }:
                row.completed_at = utc_now()
            session.flush()
            return self._job_from_row(row)

    def list_jobs(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        status: JobStatus | None = None,
        task_type: TaskType | None = None,
    ) -> list[Job]:
        statement = select(JobRow).order_by(JobRow.created_at.desc()).offset(offset).limit(limit)
        if status:
            statement = statement.where(JobRow.status == status.value)
        if task_type:
            statement = statement.where(JobRow.task_type == task_type.value)
        with self.session() as session:
            return [self._job_from_row(row) for row in session.scalars(statement).all()]

    def list_retryable_jobs(self, *, limit: int = 500) -> list[Job]:
        with self.session() as session:
            statement = (
                select(JobRow)
                .where(JobRow.status == JobStatus.RETRY.value)
                .order_by(JobRow.next_retry_at.asc())
                .limit(limit)
            )
            return [self._job_from_row(row) for row in session.scalars(statement).all()]

    def count_jobs(self, status: JobStatus | None = None) -> int:
        statement = select(func.count()).select_from(JobRow)
        if status:
            statement = statement.where(JobRow.status == status.value)
        with self.session() as session:
            return int(session.scalar(statement) or 0)

    def job_counts(self) -> dict[str, int]:
        with self.session() as session:
            rows = session.execute(
                select(JobRow.status, func.count()).group_by(JobRow.status)
            ).all()
        return {str(status): int(count) for status, count in rows}

    def _job_from_row(self, row: JobRow) -> Job:
        return Job(
            id=row.id,
            paper_id=row.paper_id,
            task_type=TaskType(row.task_type),
            provider=row.provider,
            service=row.service,
            credential_id=row.credential_id,
            priority=row.priority,
            status=JobStatus(row.status),
            attempts=row.attempts,
            max_attempts=row.max_attempts,
            created_at=aware(row.created_at) or utc_now(),
            started_at=aware(row.started_at),
            completed_at=aware(row.completed_at),
            next_retry_at=aware(row.next_retry_at),
            error_code=row.error_code,
            error_message=row.error_message,
            payload=_json_load(row.payload_json, {}),
        )

    # Downloads and documents

    def record_download(
        self,
        *,
        paper_id: str | None,
        provider: str,
        service: str,
        credential_id: str | None,
        status: str,
        format: str,
        raw_path: str | None,
        checksum: str | None,
        http_status: int | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> str:
        with self.session() as session:
            row = DownloadRow(
                paper_id=paper_id,
                provider=provider,
                service=service,
                credential_id=credential_id,
                status=status,
                format=format,
                raw_path=raw_path,
                checksum=checksum,
                http_status=http_status,
                error_code=error_code,
                error_message=error_message,
            )
            session.add(row)
            session.flush()
            return row.id

    def latest_download(self, paper_id: str) -> dict[str, Any] | None:
        with self.session() as session:
            row = session.scalar(
                select(DownloadRow)
                .where(DownloadRow.paper_id == paper_id)
                .order_by(DownloadRow.acquired_at.desc())
                .limit(1)
            )
            if row is None:
                return None
            return self._download_dict(row)

    def list_downloads(self, paper_id: str) -> list[dict[str, Any]]:
        with self.session() as session:
            rows = session.scalars(
                select(DownloadRow)
                .where(DownloadRow.paper_id == paper_id)
                .order_by(DownloadRow.acquired_at.asc())
            ).all()
            return [self._download_dict(row) for row in rows]

    @staticmethod
    def _download_dict(row: DownloadRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "paper_id": row.paper_id,
            "provider": row.provider,
            "service": row.service,
            "credential_id": row.credential_id,
            "status": row.status,
            "http_status": row.http_status,
            "format": row.format,
            "raw_path": row.raw_path,
            "checksum": row.checksum,
            "acquired_at": aware(row.acquired_at),
            "error_code": row.error_code,
            "error_message": row.error_message,
        }

    def save_normalized_document(self, paper_id: str, document: PaperDocument, path: Path) -> None:
        payload = document.model_dump(mode="json")
        stage = PaperStage.NORMALIZED
        if path.exists():
            stage = PaperStage.READY
        self.set_paper_stage(paper_id, stage)
        self.add_paper_extra(
            paper_id,
            {
                "normalized": payload,
                "normalized_path": str(path),
                "counts": document.counts(),
            },
        )

    def add_paper_extra(self, paper_id: str, extra: dict[str, Any]) -> None:
        with self.session() as session:
            row = session.get(PaperRow, paper_id)
            if row is None:
                raise KeyError(f"Paper not found: {paper_id}")
            existing = _json_load(row.extra_json, {})
            existing.update(extra)
            row.extra_json = json.dumps(existing, default=str)
            row.updated_at = utc_now()

    # Providers and credentials

    def sync_provider(
        self,
        name: str,
        display_name: str,
        services: Sequence[tuple[str, bool]],
        *,
        enabled: bool = True,
    ) -> None:
        with self.session() as session:
            provider = session.get(ProviderRow, name)
            if provider is None:
                provider = ProviderRow(name=name, display_name=display_name, enabled=enabled)
                session.add(provider)
                session.flush()
            provider.display_name = display_name
            provider.enabled = enabled
            existing = {service.name: service for service in provider.services}
            for service_name, service_enabled in services:
                if service_name not in existing:
                    session.add(
                        ProviderServiceRow(
                            provider=name, name=service_name, enabled=service_enabled
                        )
                    )
                else:
                    existing[service_name].enabled = service_enabled

    def set_provider_health(
        self,
        provider: str,
        status: HealthStatus,
        *,
        service: str | None = None,
        message: str | None = None,
    ) -> None:
        with self.session() as session:
            if service:
                service_row = session.scalar(
                    select(ProviderServiceRow).where(
                        ProviderServiceRow.provider == provider,
                        ProviderServiceRow.name == service,
                    )
                )
                if service_row is None:
                    raise KeyError(f"Provider/service not found: {provider}/{service}")
                service_row.health_status = status.value
                service_row.last_checked_at = utc_now()
                service_row.message = message
                return
            provider_row = session.get(ProviderRow, provider)
            if provider_row is None:
                raise KeyError(f"Provider/service not found: {provider}/{service}")
            provider_row.health_status = status.value
            provider_row.last_checked_at = utc_now()
            provider_row.message = message

    def list_providers(self) -> list[dict[str, Any]]:
        with self.session() as session:
            providers = session.scalars(select(ProviderRow).order_by(ProviderRow.name)).all()
            result: list[dict[str, Any]] = []
            for provider in providers:
                result.append(
                    {
                        "name": provider.name,
                        "display_name": provider.display_name,
                        "enabled": provider.enabled,
                        "health_status": provider.health_status,
                        "last_checked_at": aware(provider.last_checked_at),
                        "message": provider.message,
                        "services": [
                            {
                                "name": service.name,
                                "enabled": service.enabled,
                                "health_status": service.health_status,
                                "last_checked_at": aware(service.last_checked_at),
                                "message": service.message,
                            }
                            for service in provider.services
                        ],
                    }
                )
            return result

    def upsert_credential(
        self,
        *,
        provider: str,
        name: str,
        secret_ref: str,
        auth_type: str = "api_key",
        account_label: str | None = None,
        institution: str | None = None,
        quota_scope: str = "unknown",
        enabled: bool = True,
    ) -> str:
        with self.session() as session:
            row = session.scalar(
                select(CredentialRow).where(
                    CredentialRow.provider == provider, CredentialRow.name == name
                )
            )
            if row is None:
                row = CredentialRow(
                    provider=provider,
                    name=name,
                    secret_ref=secret_ref,
                    auth_type=auth_type,
                )
                session.add(row)
                session.flush()
            previous_ref = row.secret_ref
            row.secret_ref = secret_ref
            row.account_label = account_label
            row.institution = institution
            row.quota_scope = quota_scope
            row.enabled = enabled
            # A changed secret or a newly configured credential must be eligible again.
            if previous_ref != secret_ref or row.health_status == HealthStatus.UNHEALTHY.value:
                row.health_status = HealthStatus.UNKNOWN.value
                row.last_checked_at = None
            return row.id

    def set_credential_health(
        self, credential_id: str, status: HealthStatus, message: str | None = None
    ) -> None:
        with self.session() as session:
            row = session.get(CredentialRow, credential_id)
            if row is None:
                raise KeyError(f"Credential not found: {credential_id}")
            row.health_status = status.value
            row.last_checked_at = utc_now()
            if message:
                self._record_event(
                    session,
                    provider=row.provider,
                    credential_id=row.id,
                    event_type="credential_health",
                    level="warning" if status != HealthStatus.HEALTHY else "info",
                    message=message,
                )

    def list_credentials(self, provider: str | None = None) -> list[dict[str, Any]]:
        with self.session() as session:
            statement = select(CredentialRow).order_by(CredentialRow.name)
            if provider:
                statement = statement.where(CredentialRow.provider == provider)
            rows = session.scalars(statement).all()
            return [
                {
                    "id": row.id,
                    "provider": row.provider,
                    "name": row.name,
                    "auth_type": row.auth_type,
                    "secret_ref": row.secret_ref,
                    "account_label": row.account_label,
                    "institution": row.institution,
                    "quota_scope": row.quota_scope,
                    "enabled": row.enabled,
                    "health_status": row.health_status,
                    "last_checked_at": aware(row.last_checked_at),
                }
                for row in rows
            ]

    def get_credential(self, credential_id: str) -> dict[str, Any] | None:
        matches = [item for item in self.list_credentials() if item["id"] == credential_id]
        return matches[0] if matches else None

    # Quotas

    def upsert_quota(self, update: QuotaUpdate) -> QuotaState:
        with self.session() as session:
            row = session.scalar(
                select(QuotaStateRow).where(
                    QuotaStateRow.provider == update.provider,
                    QuotaStateRow.service == update.service,
                    QuotaStateRow.credential_id == update.credential_id,
                )
            )
            if row is None:
                row = QuotaStateRow(
                    provider=update.provider,
                    service=update.service,
                    credential_id=update.credential_id,
                )
                session.add(row)
            row.limit = update.limit
            row.remaining = update.remaining
            row.reset_at = update.reset_at
            row.observed_at = utc_now()
            row.source = update.source.value
            row.quota_scope = update.quota_scope.value
            row.status = (update.status or self.derive_quota_status(update)).value
            row.message = update.message
            session.flush()
            return self._quota_from_row(row)

    def derive_quota_status(self, update: QuotaUpdate) -> QuotaStatus:
        if update.status:
            return update.status
        if update.remaining is None:
            return QuotaStatus.UNKNOWN
        if update.remaining <= 0:
            return QuotaStatus.EXHAUSTED
        if update.limit and update.limit > 0:
            ratio = update.remaining / update.limit
            if ratio <= 0.10:
                return QuotaStatus.LOW
            if ratio <= 0.30:
                return QuotaStatus.WARNING
        return QuotaStatus.HEALTHY

    def get_quota(
        self, provider: str, service: str, credential_id: str | None = None
    ) -> QuotaState | None:
        with self.session() as session:
            row = session.scalar(
                select(QuotaStateRow).where(
                    QuotaStateRow.provider == provider,
                    QuotaStateRow.service == service,
                    QuotaStateRow.credential_id == credential_id,
                )
            )
            return self._quota_from_row(row) if row else None

    def list_quotas(self) -> list[QuotaState]:
        with self.session() as session:
            rows = session.scalars(
                select(QuotaStateRow).order_by(
                    QuotaStateRow.provider, QuotaStateRow.service, QuotaStateRow.credential_id
                )
            ).all()
            return [self._quota_from_row(row) for row in rows]

    @staticmethod
    def _quota_from_row(row: QuotaStateRow) -> QuotaState:
        return QuotaState(
            id=row.id,
            provider=row.provider,
            service=row.service,
            credential_id=row.credential_id,
            limit=row.limit,
            remaining=row.remaining,
            reset_at=aware(row.reset_at),
            observed_at=aware(row.observed_at) or utc_now(),
            source=QuotaSource(row.source),
            quota_scope=QuotaScope(row.quota_scope),
            status=QuotaStatus(row.status),
            message=row.message,
        )

    # Events

    def record_event(
        self,
        *,
        provider: str,
        event_type: str,
        service: str | None = None,
        credential_id: str | None = None,
        paper_id: str | None = None,
        job_id: str | None = None,
        level: str = "info",
        http_status: int | None = None,
        duration_ms: int | None = None,
        retry_attempt: int | None = None,
        message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        with self.session() as session:
            return self._record_event(
                session,
                provider=provider,
                service=service,
                credential_id=credential_id,
                paper_id=paper_id,
                job_id=job_id,
                event_type=event_type,
                level=level,
                http_status=http_status,
                duration_ms=duration_ms,
                retry_attempt=retry_attempt,
                message=message,
                metadata=metadata,
            )

    @staticmethod
    def _record_event(session: Session, **kwargs: Any) -> str:
        metadata = kwargs.pop("metadata", None) or {}
        row = ProviderEventRow(metadata_json=json.dumps(metadata, default=str), **kwargs)
        session.add(row)
        session.flush()
        return row.id

    def list_events(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.session() as session:
            rows = session.scalars(
                select(ProviderEventRow).order_by(ProviderEventRow.created_at.desc()).limit(limit)
            ).all()
            return [
                {
                    "id": row.id,
                    "provider": row.provider,
                    "service": row.service,
                    "credential_id": row.credential_id,
                    "paper_id": row.paper_id,
                    "job_id": row.job_id,
                    "event_type": row.event_type,
                    "level": row.level,
                    "http_status": row.http_status,
                    "duration_ms": row.duration_ms,
                    "retry_attempt": row.retry_attempt,
                    "message": row.message,
                    "metadata": _json_load(row.metadata_json, {}),
                    "created_at": aware(row.created_at),
                }
                for row in rows
            ]

    def list_failures(self, *, limit: int = 100) -> list[dict[str, Any]]:
        permanent = (
            JobStatus.FAILED.value,
            JobStatus.NOT_ENTITLED.value,
            JobStatus.NOT_FOUND.value,
            JobStatus.BLOCKED.value,
        )
        with self.session() as session:
            rows = session.scalars(
                select(JobRow)
                .where(JobRow.status.in_(permanent))
                .order_by(JobRow.completed_at.desc())
                .limit(limit)
            ).all()
            return [
                {
                    "job_id": row.id,
                    "paper_id": row.paper_id,
                    "task_type": row.task_type,
                    "provider": row.provider,
                    "service": row.service,
                    "status": row.status,
                    "attempts": row.attempts,
                    "error_code": row.error_code,
                    "error_message": row.error_message,
                    "completed_at": aware(row.completed_at),
                }
                for row in rows
            ]

    def clear_all(self) -> None:
        """Test helper that preserves an initialized schema."""
        with self.session() as session:
            for table in reversed(Base.metadata.sorted_tables):
                session.execute(delete(table))
