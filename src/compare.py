"""Side-by-side comparison and scorecard rendering.

Produces the artifact you actually share with stakeholders: a per-field table of what
DI returned vs. what CU returned, with confidence, plus a rollup scorecard.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from models import CascadeResult, ExtractionResult

CHECK = "OK"
CROSS = "MISS"


def _fmt(value: Any, width: int = 42) -> str:
    if value in (None, "", [], {}):
        return "—"
    if isinstance(value, dict):
        if "amount" in value:
            amt = value.get("amount")
            code = value.get("currencyCode") or ""
            text = f"{amt} {code}".strip()
        else:
            text = ", ".join(f"{k}={v}" for k, v in value.items() if v is not None)
    elif isinstance(value, list):
        text = f"[{len(value)} items]"
    else:
        text = str(value)
    text = " ".join(text.split())
    text = text.replace("|", "\\|")  # never break the markdown table
    return text if len(text) <= width else text[: width - 1] + "…"


def _conf(field: Any) -> str:
    if field is None or not field.is_present:
        return "—"
    if field.confidence is None:
        return "n/r"  # not reported by the service
    return f"{field.confidence:.2f}"


def _normalize_for_compare(value: Any) -> str:
    """Reduce a value to a comparable form across both services.

    DI and CU wrap the same underlying value differently — DI returns
    `{"amount": 18450.0, "currencyCode": "USD"}` where CU returns `18450.0`, and
    DI returns a structured address object where CU returns a single string.
    Comparing the rendered text would report a difference that does not exist,
    so normalize before deciding whether the two services actually disagree.
    """
    if value in (None, "", [], {}):
        return ""

    if isinstance(value, dict):
        if "amount" in value:
            value = value["amount"]
        else:
            # Address-like object -> flatten to its comparable tokens.
            parts = [str(v) for v in value.values() if v not in (None, "")]
            value = " ".join(parts)

    if isinstance(value, (int, float)):
        return f"{float(value):.4f}".rstrip("0").rstrip(".")

    text = str(value).strip().lower()

    # Numeric strings ("18,450.00") should compare equal to the number 18450.0
    stripped = text.replace(",", "").replace("$", "").replace("€", "").replace("£", "")
    try:
        return f"{float(stripped):.4f}".rstrip("0").rstrip(".")
    except ValueError:
        pass

    # Collapse punctuation/whitespace so address formatting differences don't
    # register as disagreement on the underlying value.
    for ch in ",.;:\n\t":
        text = text.replace(ch, " ")
    return " ".join(text.split())


def _values_agree(a: Any, b: Any) -> bool:
    na, nb = _normalize_for_compare(a), _normalize_for_compare(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    # One side may carry extra context (e.g. DI address lacks the country that
    # CU appends). Treat containment as agreement rather than conflict.
    if len(na) > 8 and len(nb) > 8 and (na in nb or nb in na):
        return True
    return False


def field_comparison(di: ExtractionResult | None, cu: ExtractionResult | None) -> str:
    """Row-for-row field table across both services."""
    names: list[str] = []
    for res in (di, cu):
        if res:
            for n in res.fields:
                if n not in names:
                    names.append(n)

    lines = [
        "| Field | Document Intelligence | Conf | Content Understanding | Conf | Delta |",
        "|---|---|:--:|---|:--:|---|",
    ]

    for name in names:
        df = di.fields.get(name) if di else None
        cf = cu.fields.get(name) if cu else None

        d_present = bool(df and df.is_present)
        c_present = bool(cf and cf.is_present)

        if d_present and c_present:
            delta = "match" if _values_agree(df.value, cf.value) else "**differs**"
        elif c_present and not d_present:
            delta = "**CU only**" + (" _(inferred)_" if cf and cf.is_inferred else "")
        elif d_present and not c_present:
            delta = "**DI only**"
        else:
            delta = "both missed"

        lines.append(
            f"| `{name}` | {_fmt(df.value if df else None)} | {_conf(df)} "
            f"| {_fmt(cf.value if cf else None)} | {_conf(cf)} | {delta} |"
        )

    return "\n".join(lines)


def _line_item_sum(result: ExtractionResult | None) -> float | None:
    """Sum the extended amounts across line items, if present."""
    if not result or not result.line_items:
        return None
    total = 0.0
    found = False
    for row in result.line_items:
        amt = row.get("Amount")
        if isinstance(amt, dict):
            amt = amt.get("amount")
        if isinstance(amt, (int, float)):
            total += float(amt)
            found = True
    return round(total, 2) if found else None


def _numeric(value: Any) -> float | None:
    if isinstance(value, dict):
        value = value.get("amount")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", "").replace("$", "").strip())
        except ValueError:
            return None
    return None


def _reconciliation(result: ExtractionResult | None) -> str:
    """Do the line items actually add up to the stated totals?

    This is the check that catches silent corruption. A row-count comparison
    passes when a shifted column puts the right number of rows in place with
    the wrong amounts in them — reconciliation does not.
    """
    if not result:
        return "—"

    line_sum = _line_item_sum(result)
    if line_sum is None:
        return "no line-item amounts to reconcile"

    subtotal = _numeric(result.fields["SubTotal"].value) if result.fields.get("SubTotal") else None
    total = _numeric(result.fields["InvoiceTotal"].value) if result.fields.get("InvoiceTotal") else None

    target = subtotal if subtotal is not None else total
    label = "SubTotal" if subtotal is not None else "InvoiceTotal"

    if target is None:
        return f"line items sum to {line_sum:,.2f} — **no total to reconcile against**"

    if target == 0:
        return f"line items sum to {line_sum:,.2f}, {label} is 0 — **cannot reconcile**"

    delta_pct = abs(line_sum - target) / abs(target)
    if delta_pct <= 0.02:
        return f"line items sum to {line_sum:,.2f} vs {label} {target:,.2f} — **reconciles**"
    return (
        f"line items sum to {line_sum:,.2f} vs {label} {target:,.2f} — "
        f"**MISMATCH ({delta_pct:.0%} off)**"
    )


def line_item_comparison(di: ExtractionResult | None, cu: ExtractionResult | None) -> str:
    d_n = len(di.line_items) if di else 0
    c_n = len(cu.line_items) if cu else 0
    out = [
        "| Metric | Document Intelligence | Content Understanding |",
        "|---|---|---|",
        f"| Line items detected | {d_n} | {c_n} |",
    ]

    if d_n and c_n:
        agreement = (
            "same row count"
            if d_n == c_n
            else f"disagreement of {abs(d_n - c_n)} row(s) — verify against the source"
        )
        out.append(f"| Row-count agreement | {agreement} | |")

    # The check that catches what row counts miss.
    out.append(f"| Totals reconciliation | {_reconciliation(di)} | {_reconciliation(cu)} |")

    return "\n".join(out)


def scorecard(di: ExtractionResult | None, cu: ExtractionResult | None) -> str:
    rows = [
        "| Metric | Document Intelligence | Content Understanding |",
        "|---|:--:|:--:|",
    ]

    def pair(label: str, d: Any, c: Any) -> None:
        rows.append(f"| {label} | {d} | {c} |")

    pair(
        "Model / analyzer",
        f"`{di.model_or_analyzer}`" if di else "—",
        f"`{cu.model_or_analyzer}`" if cu else "—",
    )
    pair(
        "Succeeded",
        (CHECK if di.succeeded else CROSS) if di else "—",
        (CHECK if cu.succeeded else CROSS) if cu else "—",
    )
    pair(
        "Field coverage",
        f"{di.coverage:.0%} ({len(di.populated_fields)}/{len(di.fields)})" if di else "—",
        f"{cu.coverage:.0%} ({len(cu.populated_fields)}/{len(cu.fields)})" if cu else "—",
    )
    pair(
        "Mean confidence",
        f"{di.mean_confidence:.2f}" if di else "—",
        f"{cu.mean_confidence:.2f}" if cu and cu.mean_confidence else "n/r",
    )
    pair(
        "Confidence reported on",
        f"{di.confidence_reported_ratio:.0%} of fields" if di else "—",
        f"{cu.confidence_reported_ratio:.0%} of fields" if cu else "—",
    )
    pair(
        "Low-confidence fields (<0.50)",
        ", ".join(di.low_confidence_fields) or "none" if di else "—",
        ", ".join(cu.low_confidence_fields) or "none" if cu else "—",
    )
    pair(
        "Line items",
        len(di.line_items) if di else "—",
        len(cu.line_items) if cu else "—",
    )
    pair(
        "Latency",
        f"{di.elapsed_seconds:.1f}s" if di else "—",
        f"{cu.elapsed_seconds:.1f}s" if cu else "—",
    )
    pair(
        "Inferred (non-copied) values",
        "0 — DI only returns located spans",
        len([f for f in cu.fields.values() if f.is_inferred and f.is_present]) if cu else "—",
    )
    return "\n".join(rows)


def render_document_report(
    doc_name: str,
    di: ExtractionResult | None,
    cu: ExtractionResult | None,
    cascade: CascadeResult | None = None,
) -> str:
    parts = [f"### {doc_name}", ""]

    if di and di.error:
        parts += [f"> **DI error:** {di.error}", ""]
    if cu and cu.error:
        parts += [f"> **CU error:** {cu.error}", ""]

    parts += ["#### Scorecard", "", scorecard(di, cu), ""]
    parts += ["#### Field-by-field", "", field_comparison(di, cu), ""]
    parts += ["#### Line items", "", line_item_comparison(di, cu), ""]

    if cascade:
        parts += [
            "#### Cascade routing",
            "",
            f"- **Tiers attempted:** {' -> '.join(cascade.tiers_attempted)}",
            f"- **Resolved by:** `{cascade.final_source}`",
            f"- **Reason:** {cascade.escalation_reason}",
            f"- **Total latency:** {cascade.total_elapsed_seconds:.1f}s",
            "",
        ]

    return "\n".join(parts)


def render_summary(results: list[dict[str, Any]]) -> str:
    """Portfolio rollup across every document processed."""
    lines = [
        "## Rollup across all documents",
        "",
        "| Document | DI coverage | DI mean conf | CU coverage | Escalated? | Resolved by |",
        "|---|:--:|:--:|:--:|:--:|---|",
    ]
    escalations = 0
    for r in results:
        di: ExtractionResult | None = r.get("di")
        cu: ExtractionResult | None = r.get("cu")
        casc: CascadeResult | None = r.get("cascade")
        escalated = bool(casc and "content-understanding" in casc.tiers_attempted)
        if escalated:
            escalations += 1
        lines.append(
            f"| {r['document']} "
            f"| {f'{di.coverage:.0%}' if di else '—'} "
            f"| {f'{di.mean_confidence:.2f}' if di else '—'} "
            f"| {f'{cu.coverage:.0%}' if cu else '—'} "
            f"| {'yes' if escalated else 'no'} "
            f"| `{casc.final_source if casc else '—'}` |"
        )

    total = len(results) or 1
    lines += [
        "",
        f"**Escalation rate:** {escalations}/{len(results)} ({escalations / total:.0%}) of documents "
        f"needed Content Understanding after Document Intelligence fell below the confidence bar.",
        "",
    ]
    return "\n".join(lines)


def write_report(
    results: list[dict[str, Any]],
    out_dir: str | Path,
    strategy: str,
    threshold: float,
) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    path = out_dir / f"comparison-{stamp}.md"

    header = [
        "# Document Intelligence vs. Content Understanding — comparison run",
        "",
        f"- **Run:** {datetime.now().isoformat(timespec='seconds')}",
        f"- **Strategy:** `{strategy}`",
        f"- **Confidence threshold:** {threshold:.2f}",
        f"- **Documents:** {len(results)}",
        "",
        render_summary(results),
        "---",
        "",
        "## Per-document detail",
        "",
    ]

    body = [
        render_document_report(r["document"], r.get("di"), r.get("cu"), r.get("cascade"))
        for r in results
    ]

    path.write_text("\n".join(header + body), encoding="utf-8")

    # Machine-readable sidecar for downstream analysis.
    json_path = out_dir / f"comparison-{stamp}.json"
    payload = []
    for r in results:
        entry: dict[str, Any] = {"document": r["document"]}
        for k in ("di", "cu"):
            res: ExtractionResult | None = r.get(k)
            if res:
                entry[k] = {
                    "source": res.source,
                    "model_or_analyzer": res.model_or_analyzer,
                    "error": res.error,
                    "coverage": round(res.coverage, 4),
                    "mean_confidence": round(res.mean_confidence, 4),
                    "elapsed_seconds": round(res.elapsed_seconds, 3),
                    "line_item_count": len(res.line_items),
                    "fields": {
                        n: {"value": f.value, "confidence": f.confidence, "inferred": f.is_inferred}
                        for n, f in res.fields.items()
                    },
                }
        casc: CascadeResult | None = r.get("cascade")
        if casc:
            entry["cascade"] = {
                "tiers_attempted": casc.tiers_attempted,
                "final_source": casc.final_source,
                "escalation_reason": casc.escalation_reason,
                "total_elapsed_seconds": round(casc.total_elapsed_seconds, 3),
            }
        payload.append(entry)
    json_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    return path
