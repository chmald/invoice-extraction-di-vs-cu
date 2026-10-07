"""Configuration guards: everything configurable is documented, and the azd wrapper passes every parameter."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = (ROOT / "docs" / "08-configuration-reference.md").read_text(encoding="utf-8")


def _documented(name: str) -> bool:
    return f"`{name}`" in DOC or f"`-{name}`" in DOC


def test_azd_parameters_are_documented():
    params = json.loads((ROOT / "infra" / "azd.parameters.json").read_text(encoding="utf-8"))["parameters"]
    names = {m for p in params.values() for m in re.findall(r"\$\{([A-Z_]+)", p["value"])}
    assert names, "no ${VAR} substitutions found"
    missing = sorted(n for n in names if not _documented(n))
    assert not missing, f"azd variables missing from docs/08: {missing}"


def test_azd_outputs_are_documented():
    outputs = re.findall(r"^output (\w+) ", (ROOT / "infra" / "azd.bicep").read_text(encoding="utf-8"), re.M)
    missing = sorted(o for o in outputs if not _documented(o))
    assert not missing, f"azd.bicep outputs missing from docs/08: {missing}"


def test_hook_variables_are_documented():
    names: set[str] = set()
    for ps1 in (ROOT / "infra" / "hooks").glob("*.ps1"):
        names |= set(re.findall(r'Get-EnvValue -Name "([A-Z_]+)"', ps1.read_text(encoding="utf-8")))
    missing = sorted(n for n in names if not _documented(n))
    assert not missing, f"hook variables missing from docs/08: {missing}"


def test_config_keys_and_env_vars_are_documented():
    src = (ROOT / "src" / "config.py").read_text(encoding="utf-8")
    pairs = re.findall(r'_get\(\s*"([A-Z_]+)",\s*"(\w+)"', src)
    assert pairs
    missing = sorted({n for pair in pairs for n in pair if not _documented(n)})
    assert not missing, f"config keys / env vars missing from docs/08: {missing}"
    template = json.loads((ROOT / "demo-ids.template.json").read_text(encoding="utf-8"))
    keys = {k for k in template if not k.startswith("_") and k != "workload"}
    keys |= {k for k in template["workload"] if not k.startswith("_")}
    missing = sorted(k for k in keys if k not in DOC)
    assert not missing, f"template keys missing from docs/08: {missing}"


def test_deploy_script_parameters_are_documented():
    text = (ROOT / "infra" / "deploy.ps1").read_text(encoding="utf-8")
    block = text[text.index("param("):text.index(")\n\n")]
    names = [n for n in re.findall(r"\$(\w+)", block) if n not in ("true", "false")]
    missing = sorted(n for n in names if not _documented(n))
    assert not missing, f"deploy.ps1 parameters missing from docs/08: {missing}"


def test_azd_wrapper_passes_every_main_parameter():
    main = re.findall(r"^param (\w+) ", (ROOT / "infra" / "main.bicep").read_text(encoding="utf-8"), re.M)
    azd = (ROOT / "infra" / "azd.bicep").read_text(encoding="utf-8")
    module = azd[azd.index("module demo"):]
    missing = [p for p in main if not re.search(rf"^\s+{p}:", module, re.M)]
    assert not missing, f"azd.bicep does not pass: {missing}"
