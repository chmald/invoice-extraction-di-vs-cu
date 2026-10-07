"""DI -> CU migration helper.

Answers a question that comes up in almost every Document Intelligence
conversation: *can a Document Intelligence implementation move to Content
Understanding without a rewrite?*

Short answer this tool demonstrates: the **field contract** migrates mechanically,
but the **calling code** does not. Specifically:

  Migrates cleanly (automatable, this module does it):
    - field names and types
    - the downstream JSON/Excel/XML contract your ERP consumes
    - line-item table structure

  Does NOT migrate (requires real work):
    - the client library: DI uses the `azure-ai-documentintelligence` SDK;
      CU uses `azure-ai-contentunderstanding` (or REST: set defaults, create
      analyzer, analyzeBinary + Operation-Location polling)
    - the response envelope: `documents[0].fields` vs `result.contents[0].fields`
    - confidence semantics: DI returns confidence on every located field; CU
      returns confidence and grounding only when `estimateFieldSourceAndConfidence`
      is enabled, and its scores are calibrated differently
    - a prebuilt model has no schema to author; a CU custom analyzer requires you
      to write a field schema in natural language, and quality tracks how good
      those descriptions are

Note: Microsoft's guidance is that existing Document Intelligence workloads do
not need to migrate — DI APIs, endpoints, SDKs, and billing are unchanged. This
tool is for teams *choosing* to move a workload, not a forced migration.

Run this to generate a starter CU analyzer schema from the DI prebuilt-invoice
field set, then hand-tune the descriptions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# DI prebuilt-invoice field -> (CU type, starter description)
DI_TO_CU: dict[str, tuple[str, str]] = {
    "VendorName": ("string", "Legal name of the supplier/vendor issuing this document (the party being paid)."),
    "VendorAddress": ("string", "Full postal address of the vendor."),
    "CustomerName": ("string", "Legal name of the buying entity (the party that pays)."),
    "CustomerAddress": ("string", "Full postal address of the buying entity."),
    "BillingAddress": ("string", "Address the invoice is billed to, when different from the customer address."),
    "PurchaseOrder": ("string", "Purchase order number referenced by this document, identifier only."),
    "InvoiceId": ("string", "Unique invoice number assigned by the vendor."),
    "InvoiceDate": ("string", "Issue date normalized to ISO 8601 (YYYY-MM-DD)."),
    "DueDate": ("string", "Payment due date normalized to ISO 8601 (YYYY-MM-DD)."),
    "SubTotal": ("number", "Total of line items before tax, as a plain number."),
    "TotalTax": ("number", "Total tax amount, as a plain number."),
    "InvoiceTotal": ("number", "Final amount payable including tax, as a plain number."),
    "AmountDue": ("number", "Outstanding amount still payable, as a plain number."),
    "ServiceAddress": ("string", "Address where the service was delivered."),
    "RemittanceAddress": ("string", "Address payment should be remitted to."),
    "PreviousUnpaidBalance": ("number", "Prior unpaid balance carried onto this document."),
}

DI_LINE_ITEM_TO_CU: dict[str, tuple[str, str]] = {
    "Description": ("string", "Description of the item or service on this row."),
    "ProductCode": ("string", "Vendor SKU or part number for this row."),
    "Quantity": ("number", "Quantity billed on this row."),
    "Unit": ("string", "Unit of measure for this row (EA, PCS, KG, HR)."),
    "UnitPrice": ("number", "Price per unit on this row, plain number."),
    "Amount": ("number", "Extended line total for this row, plain number."),
    "Date": ("string", "Date associated with this row, ISO 8601."),
    "Tax": ("number", "Tax applied to this row, plain number."),
}

# Things you gain by moving to CU that have no DI prebuilt equivalent.
CU_ONLY_ADDITIONS: dict[str, dict[str, Any]] = {
    "CurrencyCode": {
        "type": "string",
        "method": "generate",
        "description": "ISO 4217 currency code, inferred from symbol, formatting convention, or vendor country.",
    },
    "DocumentLanguage": {
        "type": "string",
        "method": "generate",
        "description": "Primary document language as an ISO 639-1 code.",
    },
    "DocumentKind": {
        "type": "string",
        "method": "classify",
        "description": "What this document actually is, independent of layout.",
        "enum": ["PurchaseOrder", "Invoice", "CreditMemo", "Quote", "PackingSlip", "Statement", "Other"],
    },
    "RiskSummary": {
        "type": "string",
        "method": "generate",
        "description": "One or two sentences flagging anything AP should check before posting: totals that do not reconcile, missing PO reference, due date before invoice date, or an unusually large amount.",
    },
}

# What breaks / needs hand-work during migration.
MIGRATION_NOTES = [
    ("Client library", "REWRITE", "DI uses the azure-ai-documentintelligence SDK with a poller. CU uses the azure-ai-contentunderstanding SDK (GA against 2025-11-01) or REST: set resource defaults, create an analyzer, then analyzeBinary + Operation-Location polling. The call pattern does not carry over."),
    ("Response parsing", "REWRITE", "DI: analyzeResult.documents[0].fields. CU: result.contents[0].fields. Value unwrapping differs (valueCurrency/valueAddress objects in DI vs. flatter valueString/valueNumber in CU)."),
    ("Field names/types", "AUTOMATIC", "Canonical names carry over 1:1. This tool emits the mapped schema."),
    ("Downstream ERP contract", "AUTOMATIC", "If you normalize both services into one internal shape (as this demo does), the Excel/XML your ERP ingests does not change at all."),
    ("Confidence handling", "REDESIGN", "DI returns per-field confidence on everything it locates. CU returns confidence and grounding (for extract, generate, and classify fields) only when estimateFieldSourceAndConfidence is enabled, and its scores are calibrated differently. Threshold logic tuned for DI will not transfer unchanged — re-baseline it."),
    ("Model selection", "REDESIGN", "DI: pick a prebuilt model, no schema authoring. CU: start from a prebuilt analyzer (e.g. prebuilt-invoice) or author a custom field schema in natural language; output quality tracks description quality. CU custom analyzers also need completion + embedding model deployments mapped in the resource defaults."),
    ("Region/availability", "VERIFY", "CU is GA but its regional footprint is narrower than DI's. Confirm your target region supports it before committing."),
    ("Cost model", "VERIFY", "Pricing differs: CU charges for content extraction plus contextualization, and generative model tokens are billed on your Foundry model deployment. Re-baseline cost against your real monthly volume and expected escalation rate."),
    ("Version choice", "DECIDE", "2025-11-01 is the GA API and the right target for production migration. 2026-06-01-preview adds agentic mode, synchronous Read/Layout, signature detection, and classification enhancements — evaluate it only if you need those capabilities."),
]


def build_cu_schema(
    analyzer_name: str = "MigratedFromPrebuiltInvoice",
    include_cu_only: bool = True,
    completion_model: str = "gpt-5.2",
    embedding_model: str = "text-embedding-3-large",
) -> dict[str, Any]:
    """Generate a GA (2025-11-01) CU analyzer definition from the DI prebuilt-invoice field set."""
    fields: dict[str, Any] = {}

    for di_name, (cu_type, desc) in DI_TO_CU.items():
        fields[di_name] = {"type": cu_type, "method": "extract", "description": desc}

    line_item_props = {
        name: {"type": t, "description": d}
        for name, (t, d) in DI_LINE_ITEM_TO_CU.items()
    }
    fields["LineItems"] = {
        "type": "array",
        "method": "generate",
        "description": "Every billed line item, including rows on continuation pages.",
        "items": {"type": "object", "properties": line_item_props},
    }

    if include_cu_only:
        fields.update(CU_ONLY_ADDITIONS)

    return {
        "description": "Analyzer generated from the Document Intelligence prebuilt-invoice field set. "
                       "Descriptions are starter text — tune them against real documents before production use.",
        "baseAnalyzerId": "prebuilt-document",
        "models": {"completion": completion_model, "embedding": embedding_model},
        "config": {
            "returnDetails": True,
            "enableOcr": True,
            "enableLayout": True,
            "estimateFieldSourceAndConfidence": True,
        },
        "fieldSchema": {
            "name": analyzer_name,
            "description": "Migrated purchase order / invoice schema. Documents may arrive in any language "
                           "and in unfamiliar layouts; infer values from labels and context, not fixed positions.",
            "fields": fields,
        },
    }


def migration_report() -> str:
    """Markdown table summarizing what migrates and what does not."""
    lines = [
        "## DI -> CU migration assessment",
        "",
        f"Field-level mapping: **{len(DI_TO_CU)}** document fields and "
        f"**{len(DI_LINE_ITEM_TO_CU)}** line-item fields map 1:1. "
        f"**{len(CU_ONLY_ADDITIONS)}** new capabilities are available only on CU.",
        "",
        "| Area | Migration effort | Detail |",
        "|---|---|---|",
    ]
    for area, effort, detail in MIGRATION_NOTES:
        lines.append(f"| {area} | **{effort}** | {detail} |")
    lines += [
        "",
        "**Verdict:** not plug-and-play. The data contract is portable, the integration layer is not. "
        "Budget the work in the client/parsing layer and in authoring + tuning the field schema — "
        "not in reshaping what your ERP consumes.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Generate a CU analyzer schema from the DI prebuilt-invoice field set.")
    parser.add_argument("--out", default="analyzers/migrated-from-di.json", help="Output path for the generated schema")
    parser.add_argument("--no-cu-extras", action="store_true", help="Omit CU-only fields (strict 1:1 port)")
    parser.add_argument("--report-only", action="store_true", help="Print the migration assessment without writing a file")
    args = parser.parse_args()

    print(migration_report())

    if args.report_only:
        return

    schema = build_cu_schema(include_cu_only=not args.no_cu_extras)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")
    print(f"Wrote generated analyzer schema -> {out_path}")


if __name__ == "__main__":
    main()
