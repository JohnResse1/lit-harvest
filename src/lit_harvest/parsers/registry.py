"""Parser selection: format plus content sniffing, never guesswork."""

from __future__ import annotations

from collections.abc import Sequence

from lit_harvest.models import PaperDocument
from lit_harvest.parsers.base import (
    DocumentParser,
    ParseContext,
    UnsupportedFormatError,
)


class ParserRegistry:
    """Chooses the best deterministic parser for one payload.

    Selection order:

    1. a parser explicitly preferred for this provider and format;
    2. the first registered parser whose ``formats`` contains the format and
       whose ``sniff`` accepts the content.
    """

    def __init__(self, parsers: Sequence[DocumentParser] | None = None):
        self._parsers: list[DocumentParser] = list(parsers or [])
        self._preferred: dict[tuple[str, str], DocumentParser] = {}

    def register(self, parser: DocumentParser, *, provider: str | None = None) -> None:
        self._parsers.append(parser)
        if provider:
            for fmt in parser.formats:
                self._preferred[(provider, fmt)] = parser

    def parsers(self) -> Sequence[DocumentParser]:
        return list(self._parsers)

    def candidates(self, *, format: str) -> list[DocumentParser]:
        return [parser for parser in self._parsers if format in parser.formats]

    def select(
        self,
        content: bytes,
        *,
        format: str,
        provider: str | None = None,
    ) -> DocumentParser:
        if provider:
            preferred = self._preferred.get((provider, format))
            if preferred is not None and preferred.sniff(content, format=format):
                return preferred
        for parser in self._parsers:
            if format not in parser.formats:
                continue
            if parser.sniff(content, format=format):
                return parser
        raise UnsupportedFormatError(
            f"No parser handles format {format!r}"
            + (f" from provider {provider!r}" if provider else "")
            + "."
        )

    def parse(
        self,
        content: bytes,
        *,
        format: str,
        provider: str | None = None,
        service: str | None = None,
        source_path: str | None = None,
        credential_label: str | None = None,
        http_status: int | None = None,
    ) -> PaperDocument:
        parser = self.select(content, format=format, provider=provider)
        context = ParseContext(
            format=format,
            provider=provider,
            service=service,
            source_path=source_path,
            credential_label=credential_label,
            http_status=http_status,
        )
        return parser.parse(content, context)


def build_default_registry() -> ParserRegistry:
    """Registry with every parser shipped in this build."""
    from lit_harvest.parsers.elsevier_xml import ElsevierXmlParser
    from lit_harvest.parsers.html import HtmlFullTextParser
    from lit_harvest.parsers.jats import JatsXmlParser
    from lit_harvest.parsers.pdf import PdfTextParser

    registry = ParserRegistry()
    registry.register(ElsevierXmlParser(), provider="elsevier")
    registry.register(JatsXmlParser())
    registry.register(HtmlFullTextParser())
    registry.register(PdfTextParser())
    return registry
