"""Azure Document Intelligence extractor (prebuilt-invoice, v4.0 / 2024-11-30 GA).

Uses the GA `azure-ai-documentintelligence` SDK. DI returns per-field confidence
for every field it locates, which is the signal the cascade router keys off of.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from models import ExtractedField, ExtractionResult

# Canonical PO/invoice field set used across both services so the comparison is fair.
# Left side = our canonical name, right side = DI prebuilt-invoice field name
# (v4.0, api-version 2024-11-30).
DI_FIELD_MAP: dict[str, str] = {
    "VendorName": "VendorName",
    "VendorAddress": "VendorAddress",
    "CustomerName": "CustomerName",
    "CustomerAddress": "CustomerAddress",
    "BillingAddress": "BillingAddress",
    "PurchaseOrder": "PurchaseOrder",
    "InvoiceId": "InvoiceId",
    "InvoiceDate": "InvoiceDate",
    "DueDate": "DueDate",
    "SubTotal": "SubTotal",
    "TotalTax": "TotalTax",
    "InvoiceTotal": "InvoiceTotal",
}

# prebuilt-invoice has no top-level currency field. The ISO code rides on each
# currency-typed amount (valueCurrency.currencyCode), so the canonical
# `CurrencyCode` is read from the first amount that carries one.
CURRENCY_SOURCE_FIELDS = ["InvoiceTotal", "SubTotal", "AmountDue", "TotalTax"]

# Line-item sub-fields inside the DI `Items` array.
DI_LINE_ITEM_FIELDS = ["Description", "Quantity", "Unit", "UnitPrice", "ProductCode", "Amount"]


def _unwrap(field_obj: Any) -> Any:
    """Pull a plain Python value out of a DI field object/dict.

    DI returns a typed union (valueString / valueNumber / valueCurrency / valueDate /
    valueAddress / valueArray ...). We normalize to something JSON-serializable.
    """
    if field_obj is None:
        return None

    d = field_obj if isinstance(field_obj, dict) else getattr(field_obj, "__dict__", {}) or {}

    def g(key: str) -> Any:
        if isinstance(field_obj, dict):
            return field_obj.get(key)
        return getattr(field_obj, key, None)

    # Currency is an object: {amount, currencySymbol, currencyCode}
    cur = g("value_currency") or g("valueCurrency")
    if cur is not None:
        amount = cur.get("amount") if isinstance(cur, dict) else getattr(cur, "amount", None)
        code = (
            cur.get("currency_code") or cur.get("currencyCode")
            if isinstance(cur, dict)
            else getattr(cur, "currency_code", None)
        )
        return {"amount": amount, "currencyCode": code}

    # Address is an object with street/city/postalCode/countryRegion
    addr = g("value_address") or g("valueAddress")
    if addr is not None:
        if isinstance(addr, dict):
            return {k: v for k, v in addr.items() if v is not None}
        return {k: v for k, v in (getattr(addr, "__dict__", {}) or {}).items() if v is not None}

    for key in (
        "value_string", "valueString",
        "value_number", "valueNumber",
        "value_date", "valueDate",
        "value_integer", "valueInteger",
        "value_time", "valueTime",
        "value_phone_number", "valuePhoneNumber",
        "value_country_region", "valueCountryRegion",
    ):
        v = g(key)
        if v is not None:
            return str(v) if key.lower().endswith(("date", "time")) else v

    # Fall back to the raw OCR content DI matched.
    content = g("content")
    if content is not None:
        return content

    return d.get("content") if isinstance(d, dict) else None


def _confidence(field_obj: Any) -> float | None:
    if field_obj is None:
        return None
    if isinstance(field_obj, dict):
        return field_obj.get("confidence")
    return getattr(field_obj, "confidence", None)


def currency_code(doc_fields: dict[str, Any]) -> tuple[str | None, float | None]:
    """Return (ISO currency code, confidence) from the first amount that carries one."""
    for name in CURRENCY_SOURCE_FIELDS:
        value = _unwrap(doc_fields.get(name))
        if isinstance(value, dict) and value.get("currencyCode"):
            return value["currencyCode"], _confidence(doc_fields.get(name))
    return None, None


def extract(
    document_path: str | Path,
    endpoint: str,
    key: str,
    model_id: str = "prebuilt-invoice",
) -> ExtractionResult:
    """Run one document through Document Intelligence and normalize the output."""
    document_path = Path(document_path)
    result = ExtractionResult(
        source="document-intelligence",
        document=document_path.name,
        model_or_analyzer=model_id,
    )

    try:
        from azure.ai.documentintelligence import DocumentIntelligenceClient
        from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
        from azure.core.credentials import AzureKeyCredential
    except ImportError as exc:  # pragma: no cover - environment issue, not logic
        result.error = f"azure-ai-documentintelligence not installed: {exc}"
        return result

    started = time.perf_counter()
    try:
        client = DocumentIntelligenceClient(endpoint=endpoint, credential=AzureKeyCredential(key))
        data = document_path.read_bytes()

        try:
            poller = client.begin_analyze_document(
                model_id,
                AnalyzeDocumentRequest(bytes_source=data),
            )
        except TypeError:
            # Older/newer SDK signature: raw bytes body with explicit content type.
            poller = client.begin_analyze_document(
                model_id, body=data, content_type="application/octet-stream"
            )

        analyze_result = poller.result()
        result.elapsed_seconds = time.perf_counter() - started

        as_dict = (
            analyze_result.as_dict()
            if hasattr(analyze_result, "as_dict")
            else dict(analyze_result)
        )
        result.raw_response = as_dict

        documents = as_dict.get("documents") or []
        if not documents:
            result.error = "Document Intelligence returned no documents (model found no matching document type)."
            # Still register the expected fields as empty so coverage math is honest.
            for canonical in [*DI_FIELD_MAP, "CurrencyCode"]:
                result.fields[canonical] = ExtractedField(
                    name=canonical, value=None, confidence=None, source=result.source
                )
            return result

        doc_fields = documents[0].get("fields") or {}

        for canonical, di_name in DI_FIELD_MAP.items():
            raw_field = doc_fields.get(di_name)
            result.fields[canonical] = ExtractedField(
                name=canonical,
                value=_unwrap(raw_field),
                confidence=_confidence(raw_field),
                source=result.source,
                is_inferred=False,  # DI only ever returns spans it located on the page
                raw=raw_field if isinstance(raw_field, dict) else None,
            )

        code, code_conf = currency_code(doc_fields)
        result.fields["CurrencyCode"] = ExtractedField(
            name="CurrencyCode", value=code, confidence=code_conf, source=result.source
        )

        items_field = doc_fields.get("Items") or {}
        for entry in items_field.get("valueArray", []) or []:
            props = entry.get("valueObject") or {}
            row = {
                sub: _unwrap(props.get(sub))
                for sub in DI_LINE_ITEM_FIELDS
                if props.get(sub) is not None
            }
            confs = [
                _confidence(props.get(sub))
                for sub in DI_LINE_ITEM_FIELDS
                if _confidence(props.get(sub)) is not None
            ]
            if confs:
                row["_confidence"] = round(sum(confs) / len(confs), 4)
            if row:
                result.line_items.append(row)

    except Exception as exc:  # noqa: BLE001 - surface any service error to the report
        result.elapsed_seconds = time.perf_counter() - started
        result.error = f"{type(exc).__name__}: {exc}"

    return result
