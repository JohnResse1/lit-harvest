"""Deterministic provider raw-document normalization service."""

from __future__ import annotations

from typing import Any

from lit_harvest.models import Attachment, PaperDocument, PaperStage
from lit_harvest.providers.elsevier.parser import ElsevierFullXMLParser
from lit_harvest.storage.database import Database
from lit_harvest.storage.files import DocumentStorage


class NormalizationService:
    def __init__(self, database: Database, storage: DocumentStorage):
        self.database = database
        self.storage = storage
        self.elsevier_xml = ElsevierFullXMLParser()

    def normalize(
        self,
        *,
        content: bytes,
        doi: str,
        paper_id: str,
        source_path: str | None = None,
        credential_label: str | None = None,
        http_status: int | None = None,
        pdf_path: str | None = None,
    ) -> dict[str, Any]:
        document: PaperDocument = self.elsevier_xml.parse(
            content,
            source_path=source_path,
            credential_label=credential_label,
            http_status=http_status,
        )
        if pdf_path:
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
