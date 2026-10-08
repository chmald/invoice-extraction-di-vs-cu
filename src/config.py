"""Configuration loader for the DI vs. CU comparison harness.

Resolution order for every setting:
  1. Environment variable
  2. demo-ids.local.json (gitignored, never committed)
  3. Default / None

Nothing in this module hardcodes a tenant, subscription, endpoint, or key.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCAL_IDS = REPO_ROOT / "demo-ids.local.json"
DEFAULT_ANALYZER_SCHEMA = REPO_ROOT / "analyzers" / "purchase-order-analyzer.json"

# Fields that must be present and confident for a document to post without a human
# touch. Override per workload (CRITICAL_FIELDS env var or workload.criticalFields).
DEFAULT_CRITICAL_FIELDS = ["VendorName", "InvoiceId", "InvoiceTotal", "PurchaseOrder", "InvoiceDate"]

# Confidence below this triggers escalation from DI to CU in the cascade router.
DEFAULT_CONFIDENCE_THRESHOLD = 0.60

# Content Understanding API version.
#
# 2025-11-01 is the GA API version — use it for production work.
# 2026-06-01-preview is a public preview that adds agentic mode, synchronous
# Read/Layout operations, signature detection, document metadata, and
# classification enhancements. Preview APIs carry no SLA.
#
# Verify the current version against the CU "What's new" page before relying on
# it: https://learn.microsoft.com/azure/ai-services/content-understanding/whats-new
DEFAULT_CU_API_VERSION = "2025-11-01"

# Generative models a GA custom analyzer uses. The analyzer references model
# NAMES; the resource-level `contentunderstanding/defaults` maps each name to a
# model DEPLOYMENT in the Foundry resource. `infra/main.bicep` creates both
# deployments with these names by default.
DEFAULT_CU_COMPLETION_MODEL = "gpt-5.2"
DEFAULT_CU_EMBEDDING_MODEL = "text-embedding-3-large"


def _load_local() -> dict[str, Any]:
    if LOCAL_IDS.exists():
        with LOCAL_IDS.open(encoding="utf-8") as fh:
            return json.load(fh)
    return {}


_LOCAL = _load_local()


def _get(env_key: str, json_key: str, default: Any = None) -> Any:
    val = os.environ.get(env_key)
    if val not in (None, ""):
        return val
    val = _LOCAL.get(json_key)
    if val in (None, "") and isinstance(_LOCAL.get("workload"), dict):
        val = _LOCAL["workload"].get(json_key)
    if val not in (None, ""):
        return val
    return default


def _critical_fields() -> list[str]:
    raw = _get("CRITICAL_FIELDS", "criticalFields", DEFAULT_CRITICAL_FIELDS)
    if isinstance(raw, str):
        raw = raw.split(",")
    return [f.strip() for f in raw if str(f).strip()]


@dataclass
class Settings:
    """Resolved runtime settings for both services."""

    di_endpoint: str | None = field(
        default_factory=lambda: _get("DOCUMENTINTELLIGENCE_ENDPOINT", "documentIntelligenceEndpoint")
    )
    di_key: str | None = field(
        default_factory=lambda: _get("DOCUMENTINTELLIGENCE_KEY", "documentIntelligenceKey")
    )
    di_model_id: str = field(
        default_factory=lambda: _get("DI_MODEL_ID", "diModelId", "prebuilt-invoice")
    )

    cu_endpoint: str | None = field(
        default_factory=lambda: _get("CONTENTUNDERSTANDING_ENDPOINT", "contentUnderstandingEndpoint")
    )
    cu_key: str | None = field(
        default_factory=lambda: _get("CONTENTUNDERSTANDING_KEY", "contentUnderstandingKey")
    )
    cu_analyzer_id: str = field(
        default_factory=lambda: _get("CU_ANALYZER_ID", "contentUnderstandingAnalyzerId", "po-analyzer")
    )
    cu_api_version: str = field(
        default_factory=lambda: _get("CU_API_VERSION", "contentUnderstandingApiVersion", DEFAULT_CU_API_VERSION)
    )
    cu_completion_model: str = field(
        default_factory=lambda: _get("CU_COMPLETION_MODEL", "cuCompletionModel", DEFAULT_CU_COMPLETION_MODEL)
    )
    cu_completion_deployment: str = field(
        default_factory=lambda: _get(
            "CU_COMPLETION_DEPLOYMENT", "cuCompletionDeployment", _get("CU_COMPLETION_MODEL", "cuCompletionModel", DEFAULT_CU_COMPLETION_MODEL)
        )
    )
    cu_embedding_model: str = field(
        default_factory=lambda: _get("CU_EMBEDDING_MODEL", "cuEmbeddingModel", DEFAULT_CU_EMBEDDING_MODEL)
    )
    cu_embedding_deployment: str = field(
        default_factory=lambda: _get(
            "CU_EMBEDDING_DEPLOYMENT", "cuEmbeddingDeployment", _get("CU_EMBEDDING_MODEL", "cuEmbeddingModel", DEFAULT_CU_EMBEDDING_MODEL)
        )
    )

    confidence_threshold: float = field(
        default_factory=lambda: float(_get("CONFIDENCE_THRESHOLD", "confidenceThreshold", DEFAULT_CONFIDENCE_THRESHOLD))
    )

    # Workload block (the only document-type-specific surface): which fields must be
    # present and confident before a document can skip human review.
    critical_fields: list[str] = field(default_factory=lambda: _critical_fields())
    cu_analyzer_schema: str = field(
        default_factory=lambda: _get("CU_ANALYZER_SCHEMA", "cuAnalyzerSchema", str(DEFAULT_ANALYZER_SCHEMA))
    )

    # Multi-tenant safety: these are surfaced so the deployment docs can verify the
    # active az context matches the intended target before any resource write.
    tenant_id: str | None = field(default_factory=lambda: _get("AZURE_TENANT_ID", "tenantId"))
    subscription_id: str | None = field(default_factory=lambda: _get("AZURE_SUBSCRIPTION_ID", "subscriptionId"))

    @property
    def di_configured(self) -> bool:
        return bool(self.di_endpoint and self.di_key)

    @property
    def cu_configured(self) -> bool:
        return bool(self.cu_endpoint and self.cu_key)

    def describe(self) -> str:
        def mask(v: str | None) -> str:
            if not v:
                return "(not set)"
            return f"{v[:4]}…{v[-4:]}" if len(v) > 12 else "(set)"

        return (
            f"  Document Intelligence : {self.di_endpoint or '(not set)'}  key={mask(self.di_key)}  model={self.di_model_id}\n"
            f"  Content Understanding : {self.cu_endpoint or '(not set)'}  key={mask(self.cu_key)}  "
            f"analyzer={self.cu_analyzer_id}  api={self.cu_api_version}\n"
            f"  CU models             : completion={self.cu_completion_model} -> {self.cu_completion_deployment}  "
            f"embedding={self.cu_embedding_model} -> {self.cu_embedding_deployment}\n"
            f"  Cascade threshold     : {self.confidence_threshold:.2f}\n"
            f"  Critical fields       : {', '.join(self.critical_fields)}"
        )


def load_settings() -> Settings:
    return Settings()
