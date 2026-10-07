"""Azure Content Understanding extractor (custom analyzer, REST).

Content Understanding is GA as of api-version 2025-11-01. The 2026-06-01-preview
API adds agentic mode, synchronous Read/Layout operations, signature detection,
document metadata, and classification enhancements.

This module talks to the REST surface directly so every call is visible in the
code (the GA Python SDK, `azure-ai-contentunderstanding`, wraps the same
operations and is the better choice for production). Four operations matter:

  PATCH {endpoint}/contentunderstanding/defaults?api-version=...           -> map model names to deployments
  PUT   {endpoint}/contentunderstanding/analyzers/{id}?api-version=...     -> create analyzer
  POST  {endpoint}/contentunderstanding/analyzers/{id}:analyzeBinary?...   -> analyze raw file bytes
  GET   {endpoint}/contentunderstanding/analyzerResults/{id}?...           -> poll (via Operation-Location)

In the GA API, `:analyze` accepts only a JSON body with an `inputs` array of
URLs; local bytes go to `:analyzeBinary`. Analyzer creation and analysis are
long-running: they return 201/202 plus an `Operation-Location` header that must
be polled until status is Succeeded or Failed.

Key behavioral difference vs. Document Intelligence, and the reason this demo
exists: CU is schema-driven and LLM-backed. You hand it a *field schema in
natural language* rather than picking a fixed prebuilt model, so it binds fields
by meaning rather than by learned layout position — which is what makes it
resilient to vendor template changes.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from models import ExtractedField, ExtractionResult

POLL_INTERVAL_SECONDS = 2
POLL_TIMEOUT_SECONDS = 180

# Canonical field set -> CU analyzer field names. Kept identical to the DI canonical
# names on purpose so the comparison report lines up row-for-row.
CU_FIELD_NAMES = [
    "VendorName",
    "VendorAddress",
    "CustomerName",
    "CustomerAddress",
    "BillingAddress",
    "PurchaseOrder",
    "InvoiceId",
    "InvoiceDate",
    "DueDate",
    "SubTotal",
    "TotalTax",
    "InvoiceTotal",
    "CurrencyCode",
]

# Fields the analyzer schema marks as `generate` rather than `extract` — i.e. values
# the model reasons about instead of copying verbatim. DI has no equivalent.
CU_INFERRED_FIELDS = {"CurrencyCode", "DocumentLanguage", "DocumentKind", "RiskSummary"}


def _headers(key: str) -> dict[str, str]:
    return {"Ocp-Apim-Subscription-Key": key}


def _unwrap(field_obj: Any) -> Any:
    """Normalize a CU field object into a plain Python value."""
    if not isinstance(field_obj, dict):
        return field_obj

    for key in (
        "valueString", "valueNumber", "valueInteger", "valueDate",
        "valueTime", "valueBoolean",
    ):
        if field_obj.get(key) is not None:
            return field_obj[key]

    if field_obj.get("valueObject") is not None:
        return {k: _unwrap(v) for k, v in field_obj["valueObject"].items()}

    if field_obj.get("valueArray") is not None:
        return [_unwrap(v) for v in field_obj["valueArray"]]

    return field_obj.get("content")


def _poll(session: Any, operation_url: str, key: str) -> dict[str, Any]:
    """Poll an Operation-Location until terminal state."""
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    while True:
        resp = session.get(operation_url, headers=_headers(key), timeout=60)
        resp.raise_for_status()
        payload = resp.json()
        status = (payload.get("status") or "").lower()

        if status in ("succeeded", "failed", "canceled", "cancelled"):
            if status != "succeeded":
                detail = payload.get("error") or payload
                raise RuntimeError(f"Content Understanding operation {status}: {json.dumps(detail)[:500]}")
            return payload

        if time.monotonic() > deadline:
            raise TimeoutError(f"Content Understanding operation timed out after {POLL_TIMEOUT_SECONDS}s")

        time.sleep(POLL_INTERVAL_SECONDS)


def ensure_defaults(
    endpoint: str,
    key: str,
    api_version: str,
    model_deployments: dict[str, str],
    session: Any = None,
) -> str:
    """Map generative model names to deployments at the resource level.

    GA custom analyzers reference model *names* (e.g. `gpt-5.2`); this one-time
    `PATCH contentunderstanding/defaults` tells the resource which deployment
    serves each name. Idempotent.
    """
    import requests

    base = endpoint.rstrip("/")
    url = f"{base}/contentunderstanding/defaults?api-version={api_version}"
    session = session or requests.Session()
    resp = session.patch(
        url,
        headers={**_headers(key), "Content-Type": "application/json"},
        json={"modelDeployments": model_deployments},
        timeout=60,
    )
    if resp.status_code not in (200, 201, 204):
        raise RuntimeError(f"Setting CU defaults failed ({resp.status_code}): {resp.text[:500]}")
    pairs = ", ".join(f"{m} -> {d}" for m, d in model_deployments.items())
    return f"Content Understanding defaults set: {pairs}."


def build_analyzer_definition(schema: dict[str, Any], models: dict[str, str] | None = None) -> dict[str, Any]:
    """Return the analyzer body to PUT, with the GA `models` block applied."""
    body = dict(schema)
    if models:
        body["models"] = {**body.get("models", {}), **models}
    return body


def ensure_analyzer(
    endpoint: str,
    key: str,
    analyzer_id: str,
    schema_path: str | Path,
    api_version: str,
    recreate: bool = False,
    models: dict[str, str] | None = None,
    session: Any = None,
) -> tuple[bool, str]:
    """Create the custom analyzer if it does not already exist.

    Returns (created, message). Idempotent unless `recreate=True`.
    """
    import requests

    base = endpoint.rstrip("/")
    url = f"{base}/contentunderstanding/analyzers/{analyzer_id}?api-version={api_version}"
    session = session or requests.Session()

    existing = session.get(url, headers=_headers(key), timeout=60)
    if existing.status_code == 200 and not recreate:
        return False, f"Analyzer '{analyzer_id}' already exists — reusing it."

    if existing.status_code == 200 and recreate:
        session.delete(url, headers=_headers(key), timeout=60)

    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    resp = session.put(
        url,
        headers={**_headers(key), "Content-Type": "application/json"},
        json=build_analyzer_definition(schema, models),
        timeout=60,
    )
    if resp.status_code not in (200, 201, 202):
        raise RuntimeError(f"Analyzer creation failed ({resp.status_code}): {resp.text[:500]}")

    op_url = resp.headers.get("Operation-Location")
    if op_url:
        _poll(session, op_url, key)

    return True, f"Analyzer '{analyzer_id}' created from {Path(schema_path).name}."


def extract(
    document_path: str | Path,
    endpoint: str,
    key: str,
    analyzer_id: str,
    api_version: str,
    session: Any = None,
) -> ExtractionResult:
    """Run one document through a Content Understanding analyzer."""
    document_path = Path(document_path)
    result = ExtractionResult(
        source="content-understanding",
        document=document_path.name,
        model_or_analyzer=analyzer_id,
    )

    try:
        import requests
    except ImportError as exc:  # pragma: no cover
        result.error = f"requests not installed: {exc}"
        return result

    started = time.perf_counter()
    try:
        base = endpoint.rstrip("/")
        url = f"{base}/contentunderstanding/analyzers/{analyzer_id}:analyzeBinary?api-version={api_version}"
        session = session or requests.Session()

        resp = session.post(
            url,
            headers={**_headers(key), "Content-Type": "application/octet-stream"},
            data=document_path.read_bytes(),
            timeout=120,
        )
        if resp.status_code not in (200, 202):
            raise RuntimeError(f"Analyze call failed ({resp.status_code}): {resp.text[:500]}")

        op_url = resp.headers.get("Operation-Location")
        payload = _poll(session, op_url, key) if op_url else resp.json()

        result.elapsed_seconds = time.perf_counter() - started
        result.raw_response = payload

        contents = (payload.get("result") or {}).get("contents") or []
        if not contents:
            result.error = "Content Understanding returned no contents."
            for name in CU_FIELD_NAMES:
                result.fields[name] = ExtractedField(
                    name=name, value=None, confidence=None, source=result.source
                )
            return result

        cu_fields = contents[0].get("fields") or {}

        for name in CU_FIELD_NAMES:
            raw_field = cu_fields.get(name)
            result.fields[name] = ExtractedField(
                name=name,
                value=_unwrap(raw_field),
                confidence=(raw_field or {}).get("confidence") if isinstance(raw_field, dict) else None,
                source=result.source,
                is_inferred=name in CU_INFERRED_FIELDS,
                raw=raw_field if isinstance(raw_field, dict) else None,
            )

        # CU-only enrichment fields — these have no DI equivalent and are the
        # clearest demonstration of the capability gap.
        for bonus in ("DocumentLanguage", "DocumentKind", "RiskSummary"):
            raw_field = cu_fields.get(bonus)
            if raw_field is not None:
                result.fields[bonus] = ExtractedField(
                    name=bonus,
                    value=_unwrap(raw_field),
                    confidence=raw_field.get("confidence") if isinstance(raw_field, dict) else None,
                    source=result.source,
                    is_inferred=True,
                    raw=raw_field if isinstance(raw_field, dict) else None,
                )

        line_items = cu_fields.get("LineItems") or {}
        for entry in line_items.get("valueArray", []) or []:
            obj = entry.get("valueObject") or {}
            row = {k: _unwrap(v) for k, v in obj.items()}
            if isinstance(entry, dict) and entry.get("confidence") is not None:
                row["_confidence"] = entry["confidence"]
            if row:
                result.line_items.append(row)

    except Exception as exc:  # noqa: BLE001
        result.elapsed_seconds = time.perf_counter() - started
        result.error = f"{type(exc).__name__}: {exc}"

    return result
