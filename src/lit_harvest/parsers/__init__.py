"""Deterministic document parsers for provider-agnostic normalization.

Parsers turn raw publisher bytes (XML, HTML, PDF) into the shared
``PaperDocument`` model. They are deliberately deterministic: no LLM is
involved, and every parser is selected by format plus a cheap content sniff so
that a new source does not require touching the acquisition workflow.
"""

from lit_harvest.parsers.base import (
    DocumentParser,
    ParseContext,
    UnsupportedFormatError,
)
from lit_harvest.parsers.registry import ParserRegistry, build_default_registry

__all__ = [
    "DocumentParser",
    "ParseContext",
    "ParserRegistry",
    "UnsupportedFormatError",
    "build_default_registry",
]
