"""Behavioral tests for the comparison harness (offline - no Azure calls)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import cascade
import compare
import cu_extractor
import di_extractor
import fixtures
import schema_map

ROOT = Path(__file__).resolve().parents[1]


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}
        self.text = json.dumps(self._payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    """Records every call; returns scripted responses keyed by HTTP method."""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def _call(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses[method].pop(0)

    def get(self, url, **kw):
        return self._call("GET", url, **kw)

    def put(self, url, **kw):
        return self._call("PUT", url, **kw)

    def post(self, url, **kw):
        return self._call("POST", url, **kw)

    def patch(self, url, **kw):
        return self._call("PATCH", url, **kw)

    def delete(self, url, **kw):
        return self._call("DELETE", url, **kw)


def test_simulate_runs_offline_and_writes_report(tmp_path):
    r = subprocess.run(
        [sys.executable, str(ROOT / "src" / "run_demo.py"), "simulate", "--out", str(tmp_path)],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert r.returncode == 0, r.stdout + r.stderr
    reports = list(tmp_path.glob("comparison-*.md"))
    assert len(reports) == 1
    text = reports[0].read_text(encoding="utf-8")
    assert "SIMULATED" in text
    assert "Escalation rate:** 2/3" in text
    sidecar = json.loads(next(tmp_path.glob("comparison-*.json")).read_text(encoding="utf-8"))
    assert [d["cascade"]["final_source"] for d in sidecar] == [
        "document-intelligence", "content-understanding", "content-understanding",
    ]


def test_reconciliation_catches_shifted_column_that_row_count_misses():
    di, cu = fixtures.layout_drift_di(), fixtures.layout_drift_cu()
    assert len(di.line_items) == len(cu.line_items)  # row count agrees...
    table = compare.line_item_comparison(di, cu)
    assert "MISMATCH" in table  # ...but DI's amounts don't add up
    assert "reconciles" in table


def test_cascade_gate_uses_critical_fields_not_mean():
    known = fixtures.known_layout_di()
    assert cascade.evaluate(known, 0.6) == (True, "all critical fields present and above threshold")
    drift = fixtures.layout_drift_di()
    accepted, reason = cascade.evaluate(drift, 0.6)
    assert not accepted and "PurchaseOrder" in reason
    # A workload that doesn't gate on PurchaseOrder escalates for the next weakest field instead.
    accepted, reason = cascade.evaluate(drift, 0.6, ["VendorName", "InvoiceId"])
    assert not accepted and "'InvoiceId' confidence 0.34" in reason


def test_di_currency_code_comes_from_amount_fields():
    # prebuilt-invoice (v4.0) has no top-level CurrencyCode field.
    assert "CurrencyCode" not in di_extractor.DI_FIELD_MAP
    fields = {"InvoiceTotal": {"valueCurrency": {"amount": 10.0, "currencyCode": "EUR"}, "confidence": 0.9}}
    assert di_extractor.currency_code(fields) == ("EUR", 0.9)
    assert di_extractor.currency_code({}) == (None, None)


def test_cu_extract_uses_ga_analyze_binary(tmp_path, monkeypatch):
    doc = tmp_path / "invoice.pdf"
    doc.write_bytes(b"%PDF-1.4 synthetic")
    monkeypatch.setattr(cu_extractor, "POLL_INTERVAL_SECONDS", 0)
    payload = {
        "status": "Succeeded",
        "result": {"contents": [{"fields": {
            "VendorName": {"type": "string", "valueString": "Contoso", "confidence": 0.9},
            "InvoiceTotal": {"type": "number", "valueNumber": 12.5, "confidence": 0.8},
            "LineItems": {"type": "array", "valueArray": [
                {"type": "object", "valueObject": {"Amount": {"type": "number", "valueNumber": 12.5}}},
            ]},
        }}]},
    }
    session = FakeSession({
        "POST": [FakeResponse(202, headers={"Operation-Location": "https://x/contentunderstanding/analyzerResults/1"})],
        "GET": [FakeResponse(200, payload)],
    })
    res = cu_extractor.extract(doc, "https://res.services.ai.azure.com/", "k", "po-analyzer", "2025-11-01", session=session)
    method, url, kwargs = session.calls[0]
    assert url == "https://res.services.ai.azure.com/contentunderstanding/analyzers/po-analyzer:analyzeBinary?api-version=2025-11-01"
    assert kwargs["data"] == b"%PDF-1.4 synthetic"
    assert res.error is None
    assert res.fields["VendorName"].value == "Contoso"
    assert res.line_items == [{"Amount": 12.5}]


def test_cu_setup_sets_defaults_and_injects_models(tmp_path):
    session = FakeSession({"PATCH": [FakeResponse(200)]})
    msg = cu_extractor.ensure_defaults("https://r/", "k", "2025-11-01", {"gpt-5.2": "chat"}, session=session)
    assert session.calls[0][1] == "https://r/contentunderstanding/defaults?api-version=2025-11-01"
    assert session.calls[0][2]["json"] == {"modelDeployments": {"gpt-5.2": "chat"}}
    assert "gpt-5.2 -> chat" in msg

    session = FakeSession({"GET": [FakeResponse(404)], "PUT": [FakeResponse(201)]})
    created, _ = cu_extractor.ensure_analyzer(
        "https://r/", "k", "po-analyzer", ROOT / "analyzers" / "purchase-order-analyzer.json", "2025-11-01",
        models={"completion": "gpt-5.4", "embedding": "text-embedding-3-large"}, session=session,
    )
    body = session.calls[1][2]["json"]
    assert created and body["models"]["completion"] == "gpt-5.4"


def test_analyzer_schemas_use_ga_shape():
    bundled = json.loads((ROOT / "analyzers" / "purchase-order-analyzer.json").read_text(encoding="utf-8"))
    generated = schema_map.build_cu_schema()
    for schema in (bundled, generated):
        assert schema["baseAnalyzerId"] == "prebuilt-document"
        assert set(schema["models"]) == {"completion", "embedding"}
        assert "descriptions" not in schema["fieldSchema"]
        assert schema["config"]["estimateFieldSourceAndConfidence"] is True
        assert schema["fieldSchema"]["fields"]["LineItems"]["type"] == "array"
