"""Normalized result types shared by both extractors.

The whole point of the demo is an apples-to-apples comparison, so both the
Document Intelligence path and the Content Understanding path project their
service-specific payloads into these same shapes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExtractedField:
    """A single extracted field, service-agnostic."""

    name: str
    value: Any
    confidence: float | None
    source: str  # "document-intelligence" | "content-understanding" | "ocr-fallback"
    # CU can return a value the model reasoned about rather than copied verbatim.
    # DI only ever returns spans it physically located on the page.
    is_inferred: bool = False
    raw: dict[str, Any] | None = None

    @property
    def is_present(self) -> bool:
        return self.value not in (None, "", [], {})


@dataclass
class ExtractionResult:
    """Normalized output from one service for one document."""

    source: str
    document: str
    fields: dict[str, ExtractedField] = field(default_factory=dict)
    line_items: list[dict[str, Any]] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    model_or_analyzer: str = ""
    error: str | None = None
    raw_response: dict[str, Any] | None = None

    # ---- derived metrics -------------------------------------------------

    @property
    def succeeded(self) -> bool:
        return self.error is None

    @property
    def populated_fields(self) -> list[str]:
        return [n for n, f in self.fields.items() if f.is_present]

    @property
    def coverage(self) -> float:
        """Fraction of expected fields that came back with any value at all."""
        if not self.fields:
            return 0.0
        return len(self.populated_fields) / len(self.fields)

    @property
    def mean_confidence(self) -> float:
        """Mean confidence across populated fields that reported a confidence.

        Note: CU does not return per-field confidence for every field type, so a
        low value here for CU may mean 'not reported' rather than 'uncertain'.
        Use `confidence_reported_ratio` to tell the difference.
        """
        vals = [f.confidence for f in self.fields.values() if f.is_present and f.confidence is not None]
        return sum(vals) / len(vals) if vals else 0.0

    @property
    def confidence_reported_ratio(self) -> float:
        populated = [f for f in self.fields.values() if f.is_present]
        if not populated:
            return 0.0
        return len([f for f in populated if f.confidence is not None]) / len(populated)

    @property
    def low_confidence_fields(self) -> list[str]:
        return [
            n
            for n, f in self.fields.items()
            if f.is_present and f.confidence is not None and f.confidence < 0.5
        ]


@dataclass
class CascadeResult:
    """Outcome of the tiered DI -> CU -> OCR router."""

    document: str
    tiers_attempted: list[str] = field(default_factory=list)
    final_source: str = ""
    escalation_reason: str = ""
    result: ExtractionResult | None = None
    di_result: ExtractionResult | None = None
    cu_result: ExtractionResult | None = None
    total_elapsed_seconds: float = 0.0
