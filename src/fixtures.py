"""Offline simulation fixtures.

Lets you rehearse and present the comparison with zero credentials and zero
Azure calls, using response shapes that mirror what each service actually
returns.

The three scenarios model the failure mode seen most often in accounts-payable
workloads:
**layout and template variation across vendors**, not language or country. The
distinction matters — the remedy for "this document is in another language" is
different from the remedy for "this vendor moved their totals block."

  known-layout       A vendor template the prebuilt model handles well.
                     DI and CU both do fine; DI is cheaper and faster.

  layout-drift       The SAME vendor, same language, same currency — but they
                     nudged their template. A relabeled header, a totals block
                     moved to a sidebar, one extra column. DI degrades on the
                     fields tied to the changed regions. This is the most
                     important scenario: the problem isn't exotic documents,
                     it's ordinary template churn.

  new-vendor-layout  A structurally different vendor template — multi-column
                     header, values without adjacent labels, line items grouped
                     under section sub-headers. DI largely fails to bind fields.

Everything here is clearly marked as simulated wherever it surfaces. Replace
with a real run as soon as credentials and sample documents exist.
"""

from __future__ import annotations

from models import ExtractedField, ExtractionResult

SIMULATED_BANNER = "SIMULATED — no Azure services were called"


def _mk(
    source: str,
    document: str,
    model: str,
    fields: dict[str, tuple],
    line_items: list[dict],
    elapsed: float,
) -> ExtractionResult:
    res = ExtractionResult(
        source=source,
        document=document,
        model_or_analyzer=model,
        elapsed_seconds=elapsed,
    )
    for name, spec in fields.items():
        value, conf = spec[0], spec[1]
        inferred = spec[2] if len(spec) > 2 else False
        res.fields[name] = ExtractedField(
            name=name, value=value, confidence=conf, source=source, is_inferred=inferred
        )
    res.line_items = line_items
    return res


# ===========================================================================
# Scenario 1 — known, trained vendor template. DI is the right tool.
# ===========================================================================

def known_layout_di() -> ExtractionResult:
    return _mk(
        "document-intelligence",
        "PO-vendor-A-standard-template.pdf",
        "prebuilt-invoice",
        {
            "VendorName": ("Contoso Industrial Supply", 0.972),
            "VendorAddress": ({"streetAddress": "123 Supply Ave", "city": "Springfield", "state": "OH", "postalCode": "45501"}, 0.951),
            "CustomerName": ("Northwind Manufacturing", 0.968),
            "CustomerAddress": ({"streetAddress": "456 Assembly Rd", "city": "Riverton", "state": "PA", "postalCode": "19000"}, 0.944),
            "BillingAddress": (None, None),
            "PurchaseOrder": ("PO-4419827", 0.981),
            "InvoiceId": ("INV-2026-114872", 0.979),
            "InvoiceDate": ("2026-07-28", 0.966),
            "DueDate": ("2026-08-27", 0.958),
            "SubTotal": ({"amount": 18450.00, "currencyCode": "USD"}, 0.974),
            "TotalTax": ({"amount": 1291.50, "currencyCode": "USD"}, 0.969),
            "InvoiceTotal": ({"amount": 19741.50, "currencyCode": "USD"}, 0.983),
            "CurrencyCode": ("USD", 0.983),  # from InvoiceTotal.valueCurrency
        },
        [
            {"Description": "Precision pressure transducer, 0-500 psi", "ProductCode": "CT-5500", "Quantity": 24, "Unit": "EA", "UnitPrice": 512.50, "Amount": 12300.00, "_confidence": 0.961},
            {"Description": "Calibration service, NIST traceable", "ProductCode": "SVC-CAL", "Quantity": 24, "Unit": "EA", "UnitPrice": 145.00, "Amount": 3480.00, "_confidence": 0.948},
            {"Description": "Expedited freight", "ProductCode": "FRT-EXP", "Quantity": 1, "Unit": "EA", "UnitPrice": 2670.00, "Amount": 2670.00, "_confidence": 0.933},
        ],
        elapsed=2.9,
    )


def known_layout_cu() -> ExtractionResult:
    return _mk(
        "content-understanding",
        "PO-vendor-A-standard-template.pdf",
        "po-analyzer",
        {
            "VendorName": ("Contoso Industrial Supply", 0.95),
            "VendorAddress": ("123 Supply Ave, Springfield, OH 45501", 0.93),
            "CustomerName": ("Northwind Manufacturing", 0.95),
            "CustomerAddress": ("456 Assembly Rd, Riverton, PA 19000", 0.92),
            "BillingAddress": (None, None),
            "PurchaseOrder": ("PO-4419827", 0.96),
            "InvoiceId": ("INV-2026-114872", 0.96),
            "InvoiceDate": ("2026-07-28", 0.94),
            "DueDate": ("2026-08-27", 0.93),
            "SubTotal": (18450.00, 0.95),
            "TotalTax": (1291.50, 0.94),
            "InvoiceTotal": (19741.50, 0.96),
            "CurrencyCode": ("USD", 0.91, True),
            "DocumentKind": ("Invoice", 0.97, True),
            "RiskSummary": ("No anomalies detected. Line items reconcile to the subtotal and the due date is 30 days after the invoice date.", 0.86, True),
        },
        [
            {"Description": "Precision pressure transducer, 0-500 psi", "ProductCode": "CT-5500", "Quantity": 24, "Unit": "EA", "UnitPrice": 512.50, "Amount": 12300.00},
            {"Description": "Calibration service, NIST traceable", "ProductCode": "SVC-CAL", "Quantity": 24, "Unit": "EA", "UnitPrice": 145.00, "Amount": 3480.00},
            {"Description": "Expedited freight", "ProductCode": "FRT-EXP", "Quantity": 1, "Unit": "EA", "UnitPrice": 2670.00, "Amount": 2670.00},
        ],
        elapsed=6.4,
    )


# ===========================================================================
# Scenario 2 — SAME vendor, slightly revised template. The critical scenario.
#
# Nothing exotic changed: same company, same language, same currency, same
# products. The vendor relabeled "Invoice #" to "Document Ref.", moved the
# totals block from beneath the table into a right-hand sidebar, and added a
# "Tax Code" column. DI's field binding is layout-sensitive, so the fields tied
# to the moved or renamed regions degrade or bind to the wrong span — while
# the untouched regions keep extracting perfectly.
#
# The partial nature is what makes this dangerous: it does not look like a
# failure, it looks like a success with a few gaps.
# ===========================================================================

def layout_drift_di() -> ExtractionResult:
    return _mk(
        "document-intelligence",
        "PO-vendor-A-revised-template.pdf",
        "prebuilt-invoice",
        {
            # Untouched regions still extract fine.
            "VendorName": ("Contoso Industrial Supply", 0.943),
            "VendorAddress": ({"streetAddress": "123 Supply Ave", "city": "Springfield", "state": "OH", "postalCode": "45501"}, 0.921),
            "CustomerName": ("Northwind Manufacturing", 0.907),
            "CustomerAddress": (None, None),
            "BillingAddress": (None, None),
            # "PO Number" became "Ref. / Order" — label no longer matches.
            "PurchaseOrder": (None, None),
            # "Invoice #" became "Document Ref." — binds to the label, not the value.
            "InvoiceId": ("Document Ref.", 0.34),
            "InvoiceDate": ("2026-08-11", 0.887),
            "DueDate": (None, None),
            # Totals moved to a sidebar — the table-relative anchors are gone.
            "SubTotal": (None, None),
            "TotalTax": (None, None),
            "InvoiceTotal": ({"amount": 1476.30, "currencyCode": "USD"}, 0.42),  # grabbed the tax line
            "CurrencyCode": ("USD", 0.42),  # from InvoiceTotal.valueCurrency
        },
        [
            # A new "Tax Code" column shifted the table; amounts land in the wrong column.
            {"Description": "Precision pressure transducer, 0-500 psi", "ProductCode": "CT-5500", "Quantity": 24, "Unit": "EA", "UnitPrice": 512.50, "Amount": 0.07, "_confidence": 0.38},
            {"Description": "Calibration service, NIST traceable", "ProductCode": "SVC-CAL", "Quantity": 30, "Unit": "EA", "UnitPrice": 145.00, "Amount": 0.07, "_confidence": 0.36},
            {"Description": "Expedited freight", "ProductCode": "FRT-EXP", "Quantity": 1, "Unit": "EA", "Amount": 0.00, "_confidence": 0.31},
        ],
        elapsed=3.0,
    )


def layout_drift_cu() -> ExtractionResult:
    """CU binds by meaning, so a relabeled header and a moved totals block do
    not break it — "Document Ref." is still recognizably an invoice number."""
    return _mk(
        "content-understanding",
        "PO-vendor-A-revised-template.pdf",
        "po-analyzer",
        {
            "VendorName": ("Contoso Industrial Supply", 0.95),
            "VendorAddress": ("123 Supply Ave, Springfield, OH 45501", 0.93),
            "CustomerName": ("Northwind Manufacturing", 0.94),
            "CustomerAddress": ("456 Assembly Rd, Riverton, PA 19000", 0.91),
            "BillingAddress": (None, None),
            "PurchaseOrder": ("PO-4482013", 0.92),
            "InvoiceId": ("INV-2026-118440", 0.94),
            "InvoiceDate": ("2026-08-11", 0.93),
            "DueDate": ("2026-09-10", 0.90),
            "SubTotal": (21090.00, 0.93),
            "TotalTax": (1476.30, 0.92),
            "InvoiceTotal": (22566.30, 0.95),
            "CurrencyCode": ("USD", 0.90, True),
            "DocumentKind": ("Invoice", 0.96, True),
            "RiskSummary": ("Line items reconcile to the subtotal and tax. Note this vendor's template differs from their previous submissions — the invoice number appears under a 'Document Ref.' label and totals are presented in a sidebar rather than beneath the line-item table.", 0.84, True),
        },
        [
            {"Description": "Precision pressure transducer, 0-500 psi", "ProductCode": "CT-5500", "Quantity": 24, "Unit": "EA", "UnitPrice": 512.50, "Amount": 12300.00},
            {"Description": "Calibration service, NIST traceable", "ProductCode": "SVC-CAL", "Quantity": 30, "Unit": "EA", "UnitPrice": 145.00, "Amount": 4350.00},
            {"Description": "Expedited freight", "ProductCode": "FRT-EXP", "Quantity": 1, "Unit": "EA", "UnitPrice": 4440.00, "Amount": 4440.00},
        ],
        elapsed=7.0,
    )


# ===========================================================================
# Scenario 3 — structurally different vendor template.
#
# Multi-column header block, values without adjacent labels, line items grouped
# under section sub-headers rather than a single flat table.
# ===========================================================================

def new_vendor_di() -> ExtractionResult:
    return _mk(
        "document-intelligence",
        "PO-vendor-B-unfamiliar-structure.pdf",
        "prebuilt-invoice",
        {
            "VendorName": ("ORDER CONFIRMATION", 0.29),   # picked up a banner heading
            "VendorAddress": (None, None),
            "CustomerName": (None, None),
            "CustomerAddress": (None, None),
            "BillingAddress": (None, None),
            "PurchaseOrder": (None, None),
            "InvoiceId": ("88-4471", 0.44),
            "InvoiceDate": (None, None),
            "DueDate": (None, None),
            "SubTotal": (None, None),
            "TotalTax": (None, None),
            "InvoiceTotal": ({"amount": 9420.75, "currencyCode": None}, 0.41),
            "CurrencyCode": (None, None),
        },
        [
            {"Description": "Pos. 1", "Quantity": 12, "Amount": 4200.00, "_confidence": 0.27},
        ],
        elapsed=3.1,
    )


def new_vendor_cu() -> ExtractionResult:
    return _mk(
        "content-understanding",
        "PO-vendor-B-unfamiliar-structure.pdf",
        "po-analyzer",
        {
            "VendorName": ("Fabrikam Components Ltd.", 0.91),
            "VendorAddress": ("Unit 7, Example Industrial Park, Anytown AB1 2CD", 0.88),
            "CustomerName": ("Northwind Manufacturing", 0.90),
            "CustomerAddress": ("456 Assembly Rd, Riverton, PA 19000", 0.87),
            "BillingAddress": (None, None),
            "PurchaseOrder": ("BST-2026-00913", 0.86),
            "InvoiceId": ("88-4471", 0.93),
            "InvoiceDate": ("2026-08-05", 0.89),
            "DueDate": ("2026-09-04", 0.84),
            "SubTotal": (7916.60, 0.88),
            "TotalTax": (1504.15, 0.87),
            "InvoiceTotal": (9420.75, 0.92),
            "CurrencyCode": ("GBP", 0.89, True),
            "DocumentKind": ("Invoice", 0.95, True),
            "RiskSummary": ("Line items reconcile to the subtotal and tax. No purchase order was printed in the header; the reference BST-2026-00913 was taken from the body text and should be confirmed before posting.", 0.82, True),
        },
        [
            {"Description": "Pressure sensor assembly, 0-40 bar", "ProductCode": "MPT-4012", "Quantity": 12, "Unit": "EA", "UnitPrice": 486.30, "Amount": 5835.60},
            {"Description": "Calibration certificate", "ProductCode": "KAL-D", "Quantity": 12, "Unit": "EA", "UnitPrice": 118.00, "Amount": 1416.00},
            {"Description": "Carriage", "ProductCode": "VER-01", "Quantity": 1, "Unit": "EA", "UnitPrice": 665.00, "Amount": 665.00},
        ],
        elapsed=7.2,
    )


SCENARIOS = {
    "known-layout": {
        "label": "Known vendor template — DI performs well, and costs less",
        "di": known_layout_di,
        "cu": known_layout_cu,
    },
    "layout-drift": {
        "label": "SAME vendor, slightly revised template — DI degrades on the changed regions only",
        "di": layout_drift_di,
        "cu": layout_drift_cu,
    },
    "new-vendor-layout": {
        "label": "Structurally different vendor template — DI largely fails to bind fields",
        "di": new_vendor_di,
        "cu": new_vendor_cu,
    },
}
