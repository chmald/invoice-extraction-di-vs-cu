"""CLI entry point for the DI vs. CU comparison demo.

Usage
-----
  # verify configuration without calling any service
  python src/run_demo.py check

  # create the Content Understanding analyzer from the field schema
  python src/run_demo.py setup

  # run both services over every document in samples/ and write a report
  python src/run_demo.py compare --input samples

  # run the tiered DI -> CU -> OCR router
  python src/run_demo.py cascade --input samples

  # answer the 'can we migrate DI to CU?' question
  python src/run_demo.py migrate
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cascade as cascade_mod  # noqa: E402
import compare  # noqa: E402
import cu_extractor  # noqa: E402
import di_extractor  # noqa: E402
import fixtures  # noqa: E402
import schema_map  # noqa: E402
from config import load_settings  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCHEMA = REPO_ROOT / "analyzers" / "purchase-order-analyzer.json"
DEFAULT_OUT = REPO_ROOT / "out"
SUPPORTED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".heif", ".docx", ".xlsx"}


def collect_documents(input_path: str | Path) -> list[Path]:
    p = Path(input_path)
    if p.is_file():
        return [p]
    if not p.exists():
        return []
    return sorted(f for f in p.rglob("*") if f.is_file() and f.suffix.lower() in SUPPORTED_SUFFIXES)


def cmd_check(args, settings) -> int:
    print("Configuration\n" + settings.describe())
    print()

    ok = True
    if settings.di_configured:
        print("  [OK]   Document Intelligence endpoint + key resolved.")
    else:
        print("  [MISS] Document Intelligence not configured. Set DOCUMENTINTELLIGENCE_ENDPOINT / _KEY")
        print("         or populate demo-ids.local.json. See docs/02-prerequisites.md.")
        ok = False

    if settings.cu_configured:
        print("  [OK]   Content Understanding endpoint + key resolved.")
    else:
        print("  [MISS] Content Understanding not configured.")
        print("         This is expected if CU access is still pending — the demo will run")
        print("         DI-only and clearly mark CU columns as unavailable.")

    docs = collect_documents(args.input)
    print(f"\n  Documents found in '{args.input}': {len(docs)}")
    for d in docs[:10]:
        print(f"    - {d.name}")
    if len(docs) > 10:
        print(f"    … and {len(docs) - 10} more")
    if not docs:
        print("    (drop sample POs/invoices into samples/ — see samples/README.md)")

    return 0 if ok else 1


def cmd_setup(args, settings) -> int:
    if not settings.cu_configured:
        print("Content Understanding is not configured — cannot create the analyzer.")
        print("Set CONTENTUNDERSTANDING_ENDPOINT / _KEY first. See docs/02-prerequisites.md.")
        return 1

    schema_path = Path(args.schema or settings.cu_analyzer_schema)
    if not schema_path.is_absolute():
        schema_path = REPO_ROOT / schema_path
    if not schema_path.exists():
        print(f"Schema not found: {schema_path}")
        return 1

    print(f"Creating analyzer '{settings.cu_analyzer_id}' from {schema_path.name} …")
    try:
        if not args.skip_defaults:
            print("  " + cu_extractor.ensure_defaults(
                settings.cu_endpoint,
                settings.cu_key,
                settings.cu_api_version,
                {
                    settings.cu_completion_model: settings.cu_completion_deployment,
                    settings.cu_embedding_model: settings.cu_embedding_deployment,
                },
            ))
        created, message = cu_extractor.ensure_analyzer(
            settings.cu_endpoint,
            settings.cu_key,
            settings.cu_analyzer_id,
            schema_path,
            settings.cu_api_version,
            recreate=args.recreate,
            models={"completion": settings.cu_completion_model, "embedding": settings.cu_embedding_model},
        )
        print(f"  {message}")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"  Failed: {type(exc).__name__}: {exc}")
        return 1


def cmd_compare(args, settings) -> int:
    docs = collect_documents(args.input)
    if not docs:
        print(f"No documents found in '{args.input}'. See samples/README.md.")
        return 1

    if not settings.di_configured:
        print("Document Intelligence is not configured — nothing to compare against.")
        return 1

    results = []
    for doc in docs:
        print(f"\n=== {doc.name} ===")

        print("  Document Intelligence …", end=" ", flush=True)
        di_res = di_extractor.extract(doc, settings.di_endpoint, settings.di_key, settings.di_model_id)
        print(
            f"{'error: ' + di_res.error if di_res.error else f'{di_res.coverage:.0%} coverage, mean conf {di_res.mean_confidence:.2f}, {di_res.elapsed_seconds:.1f}s'}"
        )

        cu_res = None
        if settings.cu_configured:
            print("  Content Understanding …", end=" ", flush=True)
            cu_res = cu_extractor.extract(
                doc, settings.cu_endpoint, settings.cu_key, settings.cu_analyzer_id, settings.cu_api_version
            )
            print(
                f"{'error: ' + cu_res.error if cu_res.error else f'{cu_res.coverage:.0%} coverage, {cu_res.elapsed_seconds:.1f}s'}"
            )
        else:
            print("  Content Understanding … skipped (not configured)")

        results.append({"document": doc.name, "di": di_res, "cu": cu_res})

    report = compare.write_report(results, args.out, strategy="compare", threshold=settings.confidence_threshold)
    print(f"\nReport written -> {report}")
    return 0


def cmd_cascade(args, settings) -> int:
    docs = collect_documents(args.input)
    if not docs:
        print(f"No documents found in '{args.input}'. See samples/README.md.")
        return 1

    if not settings.di_configured and args.strategy != "cu-only":
        print("Document Intelligence is not configured.")
        return 1

    results = []
    for doc in docs:
        print(f"\n=== {doc.name} ===  strategy={args.strategy}")
        outcome = cascade_mod.run(doc, settings, strategy=args.strategy)
        print(f"  Tiers: {' -> '.join(outcome.tiers_attempted)}")
        print(f"  Resolved by: {outcome.final_source}")
        print(f"  Reason: {outcome.escalation_reason}")
        print(f"  Latency: {outcome.total_elapsed_seconds:.1f}s")
        results.append(
            {
                "document": doc.name,
                "di": outcome.di_result,
                "cu": outcome.cu_result,
                "cascade": outcome,
            }
        )

    report = compare.write_report(results, args.out, strategy=args.strategy, threshold=settings.confidence_threshold)
    print(f"\nReport written -> {report}")
    return 0


def cmd_simulate(args, settings) -> int:
    """Render the full comparison from fixtures — no Azure calls, no credentials.

    Use this to rehearse the demo, or to show the DI/CU difference before the
    customer's Content Understanding access has been granted.
    """
    print(f"*** {fixtures.SIMULATED_BANNER} ***\n")

    names = [args.scenario] if args.scenario != "all" else list(fixtures.SCENARIOS)
    results = []
    for name in names:
        scenario = fixtures.SCENARIOS[name]
        di_res = scenario["di"]()
        cu_res = scenario["cu"]()
        print(f"=== {name}: {scenario['label']} ===")
        print(f"  DI: {di_res.coverage:.0%} coverage, mean conf {di_res.mean_confidence:.2f}")
        print(f"  CU: {cu_res.coverage:.0%} coverage, {len(cu_res.line_items)} line items")

        accepted, reason = cascade_mod.evaluate(di_res, settings.confidence_threshold, settings.critical_fields)
        print(f"  Cascade: DI {'accepted' if accepted else 'REJECTED -> escalate to CU'} ({reason})\n")

        from models import CascadeResult

        casc = CascadeResult(
            document=di_res.document,
            tiers_attempted=["document-intelligence"] if accepted else ["document-intelligence", "content-understanding"],
            final_source="document-intelligence" if accepted else "content-understanding",
            escalation_reason=reason if accepted else f"escalated to CU ({reason}) -> resolved",
            total_elapsed_seconds=di_res.elapsed_seconds + (0 if accepted else cu_res.elapsed_seconds),
        )
        results.append({"document": di_res.document, "di": di_res, "cu": cu_res, "cascade": casc})

    report = compare.write_report(
        results, args.out, strategy=f"simulate ({fixtures.SIMULATED_BANNER})", threshold=settings.confidence_threshold
    )
    print(f"Report written -> {report}")
    return 0


def cmd_migrate(args, settings) -> int:
    print(schema_map.migration_report())
    if not args.report_only:
        import json

        schema = schema_map.build_cu_schema(
            include_cu_only=not args.no_cu_extras,
            completion_model=settings.cu_completion_model,
            embedding_model=settings.cu_embedding_model,
        )
        out_path = Path(args.out_schema)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")
        print(f"Generated starter CU analyzer schema -> {out_path}")
        print("Tune the field descriptions against real documents before production use.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_demo.py",
        description="Compare Azure AI Document Intelligence and Azure AI Content Understanding on the same documents.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="Verify configuration and list input documents")
    p_check.add_argument("--input", default=str(REPO_ROOT / "samples"))
    p_check.set_defaults(func=cmd_check)

    p_setup = sub.add_parser("setup", help="Create the Content Understanding analyzer")
    p_setup.add_argument("--schema", default=None, help="Analyzer schema (default: CU_ANALYZER_SCHEMA / workload.cuAnalyzerSchema)")
    p_setup.add_argument("--recreate", action="store_true", help="Delete and recreate if it already exists")
    p_setup.add_argument(
        "--skip-defaults",
        action="store_true",
        help="Don't PATCH contentunderstanding/defaults (use when the resource defaults are already set)",
    )
    p_setup.set_defaults(func=cmd_setup)

    p_cmp = sub.add_parser("compare", help="Run both services side by side and write a report")
    p_cmp.add_argument("--input", default=str(REPO_ROOT / "samples"))
    p_cmp.add_argument("--out", default=str(DEFAULT_OUT))
    p_cmp.set_defaults(func=cmd_compare)

    p_cas = sub.add_parser("cascade", help="Run the tiered DI -> CU -> OCR router")
    p_cas.add_argument("--input", default=str(REPO_ROOT / "samples"))
    p_cas.add_argument("--out", default=str(DEFAULT_OUT))
    p_cas.add_argument("--strategy", choices=["cascade", "di-only", "cu-only"], default="cascade")
    p_cas.set_defaults(func=cmd_cascade)

    p_sim = sub.add_parser("simulate", help="Render the comparison offline from fixtures (no Azure, no credentials)")
    p_sim.add_argument(
        "--scenario",
        choices=["all", "known-layout", "layout-drift", "new-vendor-layout"],
        default="all",
    )
    p_sim.add_argument("--out", default=str(DEFAULT_OUT))
    p_sim.set_defaults(func=cmd_simulate)

    p_mig = sub.add_parser("migrate", help="Assess DI -> CU migration and generate a starter analyzer schema")
    p_mig.add_argument("--out-schema", default=str(REPO_ROOT / "analyzers" / "migrated-from-di.json"))
    p_mig.add_argument("--no-cu-extras", action="store_true")
    p_mig.add_argument("--report-only", action="store_true")
    p_mig.set_defaults(func=cmd_migrate)

    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):  # Windows consoles default to cp1252
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args()
    settings = load_settings()

    if args.command != "check":
        threshold_override = getattr(args, "threshold", None)
        if threshold_override:
            settings.confidence_threshold = float(threshold_override)

    return args.func(args, settings)


if __name__ == "__main__":
    raise SystemExit(main())
