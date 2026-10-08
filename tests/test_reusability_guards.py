"""Reusability + publish-safety guards.

The harness is published publicly and reused across scenarios, so the shared
baseline must stay domain-neutral and free of scenario-specific or private
content, and must not carry internal jargon an external reader can't decode. Banned words are stored as truncated SHA-256 hashes so the guard itself
doesn't re-publish them.
"""
from __future__ import annotations

import hashlib
import importlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".py", ".md", ".json", ".bicep", ".ps1", ".yaml", ".yml", ".txt", ".drawio", ".gitignore"}
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "out", ".azure", "icons", "badges"}

BANNED_WORD_HASHES = {
    "d700e1dd7c1104c9", "f756212276f70c29", "592ee81b3170f9fc",
    "3b6f68916865acbb", "34550715062af006", "c224cc422d7cc43a",
    "4e2295dd929e424a", "7b647ad335158318",
}
BANNED_PATTERNS = [
    re.compile(r"\[\[[A-Za-z][^\]\n]*\]\]"),            # wiki-style links from private notes
    re.compile(r"(?i)onedrive - "),                      # synced-folder paths
    re.compile(r"(?i)\b(Decisions|Projects)/[_A-Z]"),    # private notes folders
    re.compile(r"[A-Za-z]:\\Users\\"),                   # local user paths
]
GUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
# Generic internal jargon (not secrets) that has no meaning to an external reader.
INTERNAL_TERMS = re.compile(
    r"demo-pattern-authoring|azure-architecture-diagrams|daily[_ ]?driver|"
    r"\b(MCAPS|MCEM|MSX|TPID|CSAM|ATU|STU|CSU|CAIP|MACC)\b|hard[- ]rules?\s*#|authoring gates?|"
    r"hands-on-keyboard|\bHoK\b|technical close plan|solution play|azure consumed revenue|"
    r"tech elevate|cloud accelerate factory|microsoft\.sharepoint\.com|viva engage|"
    r"internal-only|microsoft-internal|not for customer distribution|solution engineers?",
    re.IGNORECASE,
)
# Public, well-known IDs that are allowed to appear (built-in role definitions).
ALLOWED_GUIDS = {"a97b65f3-24c7-4388-baec-2e87135dc908"}  # Cognitive Services User


def _files():
    for p in ROOT.rglob("*"):
        if p.is_file() and not (set(p.relative_to(ROOT).parts) & SKIP_DIRS) and (
            p.suffix.lower() in TEXT_SUFFIXES or p.name in TEXT_SUFFIXES
        ):
            if p.name == "test_reusability_guards.py":
                continue
            yield p


def _text(p: Path) -> str:
    t = p.read_text(encoding="utf-8", errors="ignore")
    # Embedded icon data URIs in .drawio files are base64 noise, not prose.
    return re.sub(r"data:image/svg\+xml,[A-Za-z0-9+/=]+", "", t)


def test_no_scenario_specific_words():
    hits = []
    for p in _files():
        for word in set(re.findall(r"[a-z]+", _text(p).lower())):
            if hashlib.sha256(word.encode()).hexdigest()[:16] in BANNED_WORD_HASHES:
                hits.append(f"{p.relative_to(ROOT)}: banned word (hash {hashlib.sha256(word.encode()).hexdigest()[:8]})")
    assert not hits, "\n".join(hits)


def test_no_private_notes_or_internal_references():
    hits = [f"{p.relative_to(ROOT)}: {m.group(0)}" for p in _files() for pat in BANNED_PATTERNS
            for m in pat.finditer(_text(p))]
    assert not hits, "\n".join(hits)


def test_no_internal_terminology():
    hits = [f"{p.relative_to(ROOT)}: {m.group(0)}" for p in _files() for m in INTERNAL_TERMS.finditer(_text(p))]
    assert not hits, "\n".join(hits)


def test_no_real_ids_or_keys():
    hits = []
    for p in _files():
        t = _text(p)
        hits += [f"{p.relative_to(ROOT)}: {g}" for g in GUID.findall(t) if g.lower() not in ALLOWED_GUIDS]
        hits += [f"{p.relative_to(ROOT)}: key-like token" for _ in re.findall(r"\b[0-9a-f]{32}\b", t)]
    assert not hits, "\n".join(hits)


def test_gitignore_covers_secrets_and_outputs():
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    for needed in ("demo-ids.local.json", ".env", ".azure/", "out/", "__pycache__/", ".venv/"):
        assert needed in gi, needed


def test_retarget_workload_by_configuration_only(monkeypatch):
    """Retargeting the gate at another document type is a config change, not a code change."""
    monkeypatch.setenv("CRITICAL_FIELDS", "MerchantName,Total,TransactionDate")
    monkeypatch.setenv("DI_MODEL_ID", "prebuilt-receipt")
    monkeypatch.setenv("CU_ANALYZER_ID", "receipt-analyzer")
    import config
    importlib.reload(config)
    s = config.load_settings()
    assert s.critical_fields == ["MerchantName", "Total", "TransactionDate"]
    assert (s.di_model_id, s.cu_analyzer_id) == ("prebuilt-receipt", "receipt-analyzer")
    assert "InvoiceId" not in s.critical_fields
