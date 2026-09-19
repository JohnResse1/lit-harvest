# Document parsing

Literature Harvester turns raw publisher bytes into one shared `PaperDocument` model. Parsing is
**deterministic**: no LLM is involved, and the same bytes always produce the same document.

## Why deterministic first

Publisher payloads already carry structure — title, authors, abstract, sections, figures, tables,
references, identifiers, licences. Extracting those fields with a parser is exact, free, offline,
and reproducible. Reserving language models for genuine semantic questions (which measurement
belongs to which sample) keeps them cheap and auditable. See the future scientific-extraction
philosophy for that later layer; it is deliberately out of scope here.

## Parser inventory

| Parser | Formats | Covers | Version tag |
| --- | --- | --- | --- |
| `ElsevierXmlParser` | `xml` | ScienceDirect `FULL` (`<full-text-retrieval-response>`) | `elsevier-full-xml/1.0` |
| `JatsXmlParser` | `xml` | JATS / NLM — Europe PMC, PMC, many publishers | `jats-xml/1.0` |
| `HtmlFullTextParser` | `html` | Publisher and repository HTML with citation meta tags | `html-fulltext/1.0` |
| `PdfTextParser` | `pdf` | Embedded PDF text layer (**not OCR**) | `pdf-text-layer/1.0` |

JATS is the highest-leverage parser: one implementation covers every archive and publisher that
exposes NLM JATS, which is the dominant machine-readable full-text format in open-access
publishing.

## How a parser is selected

`ParserRegistry.select(content, format=..., provider=...)`:

1. If a provider hint is given and its parser accepts the content, use it.
2. Otherwise use the first parser whose `formats` contains the format and whose `sniff` returns true.
3. If none match, raise `UnsupportedFormatError`.

`sniff` must be cheap and pure — it inspects a bounded prefix or a parsed root tag, never the whole
document's semantics. Structure beats the HTTP content type, because servers frequently mislabel
scholarly payloads: a JATS article begins with an NLM `<!DOCTYPE article ...>` and must be read as
XML even though the markup superficially resembles HTML.

## Adding a parser

1. Create a module under `src/lit_harvest/parsers/` exposing `name`, `version`,
   `formats`, `sniff(content, *, format)`, and `parse(content, context)`.
2. Return a `PaperDocument` with `provenance.parser_version` set.
3. Register it in `build_default_registry()` — pass `provider=` only when the parser should be
   preferred for that provider.
4. Add a synthetic fixture and tests. **Do not commit real copyrighted full text**; keep fixtures
   minimal and hand-written.

## PDF policy

PDF files are read for their existing text layer only. The tool never rasterizes pages and never runs
OCR. When a PDF has no usable text layer it is recorded with a `needs_ocr` attachment so a later,
separate OCR stage can find it — a silent empty document would be worse.

Licence note: prefer permissively licensed libraries. `pypdf` (BSD-3-Clause) is used here;
PyMuPDF and MinerU are AGPL and are intentionally avoided in this MIT-licensed project.

## Format survey

Before prioritizing parser work, find out what your sources actually return:

```bash
lit-harvest formats
```

This prints successful downloads grouped by provider, service, and format.
