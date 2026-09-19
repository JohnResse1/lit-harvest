"""Adapter exposing the existing ScienceDirect FULL XML parser as a plugin."""

from __future__ import annotations

from lit_harvest.models import PaperDocument
from lit_harvest.parsers.base import ParseContext
from lit_harvest.providers.elsevier.parser import (
    PARSER_VERSION,
    ElsevierFullXMLParser,
)


class ElsevierXmlParser:
    """ScienceDirect ``<full-text-retrieval-response>`` documents."""

    name = "elsevier_full_xml"
    version = PARSER_VERSION
    formats: tuple[str, ...] = ("xml",)

    # Distinctive root element of the ScienceDirect FULL payload.
    ROOT_TAGS = (
        b"full-text-retrieval-response",
        b"full-text-retrieval-response",
    )

    def __init__(self) -> None:
        self._inner = ElsevierFullXMLParser()

    def sniff(self, content: bytes, *, format: str) -> bool:
        if format != "xml":
            return False
        head = content.lstrip()[:4000].lower()
        return any(tag in head for tag in self.ROOT_TAGS)

    def parse(self, content: bytes, context: ParseContext) -> PaperDocument:
        return self._inner.parse(
            content,
            source_path=context.source_path,
            credential_label=context.credential_label,
            http_status=context.http_status,
        )
