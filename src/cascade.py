"""Tiered extraction router: Document Intelligence -> Content Understanding -> OCR.

This implements a common multi-layer strategy:

    Run DI first (lowest cost per page)
      -> evaluate extraction confidence
      -> if below threshold, escalate to Content Understanding
      -> if that still fails, fall back to generalized OCR (prebuilt-read)

The obvious follow-up question is whether CU makes this cascade unnecessary.
The router is deliberately instrumented so you can answer that empirically: run
`--strategy cascade` and `--strategy cu-only` over the same document set and
compare escalation rate, accuracy, and cost.
"""

from __future__ import annotations

import time
from pathlib import Path

import cu_extractor
import di_extractor
from models import CascadeResult, ExtractionResult

# Default critical fields (config.DEFAULT_CRITICAL_FIELDS). A miss on any of these
# is what actually causes a human touch, so the escalation decision keys off them
# rather than off a flat average. Override per workload via CRITICAL_FIELDS.
from config import DEFAULT_CRITICAL_FIELDS as CRITICAL_FIELDS  # noqa: E402


def evaluate(
    result: ExtractionResult, threshold: float, critical_fields: list[str] | None = None
) -> tuple[bool, str]:
    """Decide whether a result is good enough to accept.

    Returns (accepted, reason).
    """
    critical = list(critical_fields or CRITICAL_FIELDS)
    if not result.succeeded:
        return False, f"tier errored: {result.error}"

    missing = [f for f in critical if not result.fields.get(f) or not result.fields[f].is_present]
    if missing:
        return False, f"missing critical field(s): {', '.join(missing)}"

    scored = [
        result.fields[f].confidence
        for f in critical
        if result.fields.get(f) and result.fields[f].confidence is not None
    ]
    if scored:
        weakest = min(scored)
        if weakest < threshold:
            weak_name = next(
                f
                for f in critical
                if result.fields.get(f) and result.fields[f].confidence == weakest
            )
            return False, f"'{weak_name}' confidence {weakest:.2f} below threshold {threshold:.2f}"

    if not result.line_items:
        return False, "no line items extracted"

    return True, "all critical fields present and above threshold"


def ocr_fallback(document_path: Path, endpoint: str, key: str) -> ExtractionResult:
    """Last-resort tier: raw OCR via prebuilt-read.

    This returns text, not structured fields — it exists so the pipeline degrades
    to 'human reviews the text' instead of dropping the document entirely.
    """
    result = di_extractor.extract(document_path, endpoint, key, model_id="prebuilt-read")
    result.source = "ocr-fallback"
    for f in result.fields.values():
        f.source = "ocr-fallback"
    if result.raw_response:
        content = result.raw_response.get("content") or ""
        result.line_items = []
        result.fields = {
            k: v for k, v in result.fields.items()
        }
        # Surface the OCR text length so the report shows something actionable.
        result.model_or_analyzer = f"prebuilt-read ({len(content)} chars extracted)"
    return result


def run(document_path: str | Path, settings, strategy: str = "cascade") -> CascadeResult:
    """Execute the routing strategy over a single document.

    strategy:
      cascade  - DI, escalate to CU on low confidence, then OCR
      di-only  - DI only (baseline / typical current state)
      cu-only  - CU only (the 'does CU remove the need for a cascade?' test)
    """
    document_path = Path(document_path)
    outcome = CascadeResult(document=document_path.name)
    started = time.perf_counter()

    # --- Tier 1: Document Intelligence -----------------------------------
    if strategy in ("cascade", "di-only"):
        outcome.tiers_attempted.append("document-intelligence")
        di_result = di_extractor.extract(
            document_path, settings.di_endpoint, settings.di_key, settings.di_model_id
        )
        outcome.di_result = di_result

        accepted, reason = evaluate(di_result, settings.confidence_threshold, settings.critical_fields)
        if accepted or strategy == "di-only":
            outcome.result = di_result
            outcome.final_source = di_result.source
            outcome.escalation_reason = (
                "accepted at tier 1" if accepted else f"di-only mode; would have escalated ({reason})"
            )
            outcome.total_elapsed_seconds = time.perf_counter() - started
            return outcome

        outcome.escalation_reason = reason

    # --- Tier 2: Content Understanding ------------------------------------
    if strategy in ("cascade", "cu-only"):
        if not settings.cu_configured:
            outcome.total_elapsed_seconds = time.perf_counter() - started
            outcome.result = outcome.di_result
            outcome.final_source = outcome.di_result.source if outcome.di_result else "none"
            outcome.escalation_reason += " | CU not configured — escalation unavailable"
            return outcome

        outcome.tiers_attempted.append("content-understanding")
        cu_result = cu_extractor.extract(
            document_path,
            settings.cu_endpoint,
            settings.cu_key,
            settings.cu_analyzer_id,
            settings.cu_api_version,
        )
        outcome.cu_result = cu_result

        accepted, cu_reason = evaluate(cu_result, settings.confidence_threshold, settings.critical_fields)
        if accepted or strategy == "cu-only":
            outcome.result = cu_result
            outcome.final_source = cu_result.source
            if strategy == "cascade":
                outcome.escalation_reason = f"escalated to CU ({outcome.escalation_reason}) -> resolved"
            else:
                outcome.escalation_reason = cu_reason
            outcome.total_elapsed_seconds = time.perf_counter() - started
            return outcome

        outcome.escalation_reason += f" | CU also below bar: {cu_reason}"

    # --- Tier 3: OCR fallback ---------------------------------------------
    outcome.tiers_attempted.append("ocr-fallback")
    ocr_result = ocr_fallback(document_path, settings.di_endpoint, settings.di_key)
    outcome.result = ocr_result
    outcome.final_source = "ocr-fallback"
    outcome.escalation_reason += " | fell through to OCR — route to human review"
    outcome.total_elapsed_seconds = time.perf_counter() - started
    return outcome
