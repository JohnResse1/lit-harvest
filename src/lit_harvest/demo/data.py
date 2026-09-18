"""Built-in sample papers used by `lit-harvest demo`."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class DemoPaper:
    doi: str
    title: str
    journal: str
    year: int
    authors: list[str]
    abstract: str
    keywords: list[str]
    document_type: str = "Article"
    publisher: str = "Demo Publisher"
    sections: list[tuple[str, list[str]]] = field(default_factory=list)
    references: list[tuple[str, str, str, str]] = field(default_factory=list)


DEMO_PAPERS: list[DemoPaper] = [
    DemoPaper(
        doi="10.1016/j.demo.2026.100001",
        title="Solid-State Electrolyte Interfaces: A Practical Review",
        journal="Journal of Demonstration Materials",
        year=2026,
        authors=["Li Zhang", "Ming Wang", "Anna Kowalski"],
        abstract=(
            "Solid-state batteries promise higher energy density and improved safety, but the "
            "electrolyte-electrode interface remains the dominant source of resistance and "
            "degradation. This demonstration article surveys interfacial engineering strategies, "
            "including interlayer coatings, composite electrolytes, and stack-pressure control."
        ),
        keywords=["solid-state battery", "interface", "electrolyte", "ionic conductivity"],
        sections=[
            (
                "1. Introduction",
                [
                    "Solid-state batteries replace the flammable liquid electrolyte with a solid "
                    "ion conductor, which improves safety and enables lithium-metal anodes.",
                    "The critical challenge is the solid-solid interface, where poor contact and "
                    "interfacial reactions raise impedance and limit rate capability.",
                ],
            ),
            (
                "2. Interfacial Engineering",
                [
                    "Thin oxide interlayers such as LiNbO3 reduce interfacial resistance between "
                    "the cathode and a sulfide electrolyte.",
                    "Stack pressure is a practical control variable: insufficient pressure creates "
                    "voids, while excessive pressure can fracture the ceramic separator.",
                ],
            ),
            (
                "3. Measurement",
                [
                    "Electrochemical impedance spectroscopy (EIS) is the standard technique for "
                    "separating bulk and interfacial contributions to total resistance.",
                    "The measured ionic conductivity of the demonstration garnet sample was "
                    "1.2 mS/cm at 25 degrees Celsius.",
                ],
            ),
        ],
        references=[
            (
                "10.1016/j.demo.2024.100010",
                "Interlayer coatings for sulfide electrolytes",
                "Journal of Demonstration Materials",
                "2024",
            ),
            (
                "10.1016/j.demo.2025.100011",
                "Stack pressure effects in solid-state cells",
                "Demo Energy Letters",
                "2025",
            ),
            (
                "10.1002/demo.202300012",
                "EIS analysis of garnet electrolytes",
                "Demo Electrochemistry",
                "2023",
            ),
        ],
    ),
    DemoPaper(
        doi="10.1016/j.demo.2026.100002",
        title="Machine-Assisted Extraction of Synthesis Conditions from Materials Literature",
        journal="Demonstration Methods in Materials Informatics",
        year=2026,
        authors=["Yutong Duan", "Runjia Yu"],
        abstract=(
            "Materials synthesis is reported in prose that varies widely between journals. This "
            "demonstration study describes a rule-based pipeline that identifies synthesis "
            "temperature, holding time, and atmosphere from structured method sections, and "
            "compares its output with a manually curated reference set."
        ),
        keywords=["materials informatics", "synthesis", "text mining", "provenance"],
        document_type="Review",
        sections=[
            (
                "1. Motivation",
                [
                    "Synthesis parameters determine the final phase and microstructure, yet they "
                    "are buried in unstructured text and are rarely machine-readable.",
                    "A reliable acquisition layer is a prerequisite: extraction quality cannot "
                    "exceed the quality of the source document that is stored locally.",
                ],
            ),
            (
                "2. Pipeline",
                [
                    "The pipeline normalizes the full-text XML into a common document model, then "
                    "applies deterministic rules to the methods sections.",
                    "Every extracted value carries provenance: the source section, paragraph, and "
                    "character offsets are retained for audit.",
                ],
            ),
        ],
        references=[
            (
                "10.1016/j.demo.2025.100020",
                "Benchmarking materials text mining",
                "Demo Methods",
                "2025",
            ),
        ],
    ),
    DemoPaper(
        doi="10.1016/j.demo.2026.100003",
        title="Sodium-Ion Cathodes: A Short Demonstration Record",
        journal="Demonstration Energy Letters",
        year=2025,
        authors=["Wei Chen"],
        abstract=(
            "This short record demonstrates a normalized, provider-independent document: it "
            "contains identifiers, bibliographic metadata, an abstract, keywords, structured "
            "sections, and references, all stored as JSON alongside the original raw source."
        ),
        keywords=["sodium-ion", "cathode", "energy storage"],
        document_type="Short Communication",
        sections=[
            (
                "1. Results",
                [
                    "The demonstration cathode retained 82 percent of its initial capacity after "
                    "100 cycles at 1C.",
                ],
            ),
        ],
        references=[],
    ),
]
