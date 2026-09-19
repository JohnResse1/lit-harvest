"""Parsing contracts shared by every document parser."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from lit_harvest.models import PaperDocument


class UnsupportedFormatError(Exception):
    """Raised when no parser can handle a payload.

    Acquisition treats this as a soft failure: the raw file stays on disk and
    the paper is left un-normalized rather than being silently mis-parsed.
    """


@dataclass(slots=True)
class ParseContext:
    """Everything a parser may need beyond the raw bytes."""

    format: str
    provider: str | None = None
    service: str | None = None
    source_path: str | None = None
    credential_label: str | None = None
    http_status: int | None = None


class DocumentParser(Protocol):
    """Turn raw bytes into a normalized ``PaperDocument``.

    ``sniff`` must be cheap and pure: it inspects a bounded prefix (or parsed
    root tag) to decide whether this parser is the right one for the payload.
    """

    name: str
    version: str
    #: Formats this parser can ever handle, e.g. ``("xml",)``.
    formats: tuple[str, ...]

    def sniff(self, content: bytes, *, format: str) -> bool: ...

    def parse(self, content: bytes, context: ParseContext) -> PaperDocument: ...
