"""Deterministic PDF text-layer parser (not OCR).

Some legitimate sources only expose a PDF (for example a publisher PDF or an
open-access deposit). This parser extracts the text layer that is already
embedded in the file using ``pypdf``. It never rasterizes pages and never runs
OCR, so scanned image-only PDFs yield little or no text.

That limitation is deliberate and reported, not hidden: when no usable text
layer exists the document is still written, but it is marked
``needs_ocr`` so a later, separate OCR stage can pick it up.
"""

from __future__ import annotations

import contextlib
import io
import re
from datetime import UTC, datetime
from hashlib import sha256

from lit_harvest.models import (
    Attachment,
    DocumentIdentifiers,
    DocumentProvenance,
    PaperDocument,
    Paragraph,
    Section,
)
from lit_harvest.parsers.base import ParseContext

PARSER_VERSION = "pdf-text-layer/1.0"

#: Some PDFs need many bytes of text before it is worth treating as structured.
MIN_USABLE_CHARS = 200

_DOI = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")
_HEADING = re.compile(r"^\s*(\d+(?:\.\d+)*)\.?\s+([A-Z][^\n]{2,80})$")


def _normalize_block(text: str) -> str:
    lines = [line.strip() for line in text.splitlines()]
    return " ".join(line for line in lines if line)


class PdfTextParser:
    """Text-layer extraction only; never OCR."""

    name = "pdf_text_layer"
    version = PARSER_VERSION
    formats: tuple[str, ...] = ("pdf",)

    def sniff(self, content: bytes, *, format: str) -> bool:
        if format != "pdf":
            return False
        return content.startswith(b"%PDF")

    def parse(self, content: bytes, context: ParseContext) -> PaperDocument:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError

        try:
            reader = PdfReader(io.BytesIO(content))
            if reader.is_encrypted:
                # An empty password unlocks PDFs that are only owner-restricted.
                with contextlib.suppress(Exception):
                    # Reported via the empty text layer if this fails.
                    reader.decrypt("")
            pages = [page.extract_text() or "" for page in reader.pages]
        except (PdfReadError, ValueError, OSError):
            pages = []

        sections: list[Section] = []
        current = Section(title=None, paragraphs=[])
        # PDF text extraction emits line breaks, not blank-line paragraphs, so
        # headings are recognized line by line and runs of lines are grouped.
        buffer: list[str] = []

        def flush_buffer(page_number: int) -> None:
            if not buffer:
                return
            text = " ".join(buffer)
            buffer.clear()
            current.paragraphs.append(
                Paragraph(id=f"page{page_number}", text=text, type="pdf_text")
            )

        for page_number, raw in enumerate(pages, start=1):
            for line in raw.splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                if _HEADING.match(stripped):
                    flush_buffer(page_number)
                    if current.paragraphs or current.title:
                        sections.append(current)
                    current = Section(title=stripped, paragraphs=[])
                    continue
                buffer.append(stripped)
            flush_buffer(page_number)
        if current.paragraphs or current.title:
            sections.append(current)

        full_text = _normalize_block("\n\n".join(pages))
        text_length = len(full_text)
        usable = text_length >= MIN_USABLE_CHARS

        doi_match = _DOI.search(full_text)
        document = PaperDocument(
            identifiers=DocumentIdentifiers(
                doi=doi_match.group(0).rstrip(".,;)") if doi_match else None
            ),
            sections=sections if usable else [],
            provenance=DocumentProvenance(
                provider=context.provider or "pdf",
                service=context.service or "fulltext",
                format="pdf",
                source_path=context.source_path,
                parser_version=self.version,
                acquired_at=datetime.now(UTC),
                credential_label=context.credential_label,
                http_status=context.http_status,
                sha256=sha256(content).hexdigest(),
            ),
        )
        # Explicit, queryable signal instead of a silent empty document.
        document.attachments.append(
            Attachment(
                name="PDF source",
                local_path=context.source_path,
                content_type="application/pdf",
                kind="needs_ocr" if not usable else "pdf",
            )
        )
        return document
