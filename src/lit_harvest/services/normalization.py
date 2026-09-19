"""Deterministic provider raw-document normalization service.

The service is now format-driven: it hands raw bytes to a parser registry and
lets the registry pick the right deterministic parser from the payload's format
and content. Adding a new source format (JATS, HTML, PDF, ...) is a parser
change, not a workflow change.
"""

from __future__ import annotations

from typing import Any

from lit_harvest.models import Attachment, PaperDocument, PaperStage
from lit_harvest.parsers import (
    ParserRegistry,
    UnsupportedFormatError,
    build_default_registry,
)
from lit_harvest.storage.database import Database
from lit_harvest.storage.files import DocumentStorage


class NormalizationService:
    def __init__(
        self,
        database: Database,
        storage: DocumentStorage,
        *,
        parsers: ParserRegistry | None = None,
    ):
        self.database = database
        self.storage = storage
        self.parsers = parsers or build_default_registry()

    def can_normalize(self, *, format: str, content: bytes = b"") -> bool:
        """Whether some parser can handle this format (optionally sniffed)."""
        if not content:
            return bool(self.parsers.candidates(format=format))
        try:
            self.parsers.select(content, format=format)
        except UnsupportedFormatError:
            return False
        return True

    def normalize(
        self,
        *,
        content: bytes,
        doi: str,
        paper_id: str,
        source_path: str | None = None,
        credential_label: str | None = None,
        http_status: int | None = None,
        provider: str | None = None,
        service: str | None = None,
        format: str = "xml",
        pdf_path: str | None = None,
    ) -> dict[str, Any]:
        document: PaperDocument = self.parsers.parse(
            content,
            format=format,
            provider=provider,
            service=service,
            source_path=source_path,
            credential_label=credential_label,
            http_status=http_status,
        )
        already_attached = any(
            item.kind == "pdf" and item.local_path == pdf_path
            for item in document.attachments
        )
        if pdf_path and not already_attached:
            document.attachments.append(
                Attachment(
                    name="Publisher PDF",
                    content_type="application/pdf",
                    local_path=pdf_path,
                    kind="pdf",
                )
            )
        path = self.storage.write_normalized(doi, document.model_dump(mode="json"))
        self.database.save_normalized_document(paper_id, document, path)
        self.storage.write_state(
            doi,
            {
                **self.storage.read_state(doi),
                "stage": "normalized",
                "normalized_path": str(path),
                "parser_version": document.provenance.parser_version,
            },
        )
        self.database.set_paper_stage(paper_id, PaperStage.NORMALIZED)
        return {"path": path, "document": document.model_dump(mode="json")}
