from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from bidded import __version__
from bidded.config import load_settings
from bidded.db.seed_demo_company import seed_demo_company
from bidded.db.seed_demo_states import seed_demo_states
from bidded.demo_smoke import (
    DEFAULT_ANTHROPIC_MODEL,
    DemoSmokeError,
    DemoSmokeResult,
    run_demo_smoke,
)
from bidded.doctor import run_demo_environment_doctor
from bidded.documents import TenderPdfRegistrationError, register_demo_tender_pdf
from bidded.evals.decision_diff import (
    DecisionDiffError,
    diff_decision_payloads,
    load_persisted_run_decision_payload,
    render_decision_diff_text,
    write_decision_diff_json,
)
from bidded.evals.golden_runner import (
    GoldenCaseEvalResult,
    GoldenEvalError,
    GoldenEvalReport,
    run_golden_evals,
    write_golden_eval_json,
    write_golden_eval_markdown,
)
from bidded.evals.live_comparison import (
    AnthropicGoldenEvalOutcomeProvider,
    LiveGoldenEvalComparisonReport,
    run_live_golden_eval_comparison,
    write_live_golden_eval_comparison_json,
    write_live_golden_eval_comparison_markdown,
)
from bidded.orchestration import (
    AgentRunStatus,
    PendingRunContextError,
    PrepareRunError,
    ProcurementManifestError,
    WorkerLifecycleError,
    create_pending_run_context,
    prepare_procurement_manifest_run,
    prepare_procurement_run,
    run_worker_once,
)
from bidded.orchestration.decision_export import (
    DecisionExportError,
    export_decision_bundle,
)
from bidded.orchestration.run_controls import (
    DemoTraceEntry,
    RunControlError,
    get_run_status,
    reset_stale_runs,
    retry_agent_run,
)

DEMO_TENDER_PDF_HINT = "data/demo/incoming/Bilaga Skakrav.pdf"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bidded",
        description="Bidded local worker and agent-core utilities.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command")
    seed_parser = subparsers.add_parser(
        "seed-demo-company",
        help="Seed the demo IT consultancy company.",
        description="Seed the demo IT consultancy company in Supabase.",
    )
    seed_parser.set_defaults(handler=_run_seed_demo_company_command)

    demo_states_parser = subparsers.add_parser(
        "seed-demo-states",
        help="Seed replayable demo run states.",
        description=(
            "Seed deterministic replayable demo rows for pending, succeeded, "
            "failed, and needs-human-review states without live agent execution."
        ),
    )
    demo_states_parser.set_defaults(handler=_run_seed_demo_states_command)

    register_parser = subparsers.add_parser(
        "register-demo-tender",
        help="Register a local text-PDF as the demo tender.",
        description=(
            "Register a local text-PDF as the demo tender in Supabase. "
            f"Preferred local demo input when present: {DEMO_TENDER_PDF_HINT}."
        ),
    )
    register_parser.add_argument(
        "pdf_path",
        type=Path,
        help=(
            "Local text-PDF path. Preferred gitignored demo input: "
            f"{DEMO_TENDER_PDF_HINT}."
        ),
    )
    register_parser.add_argument("--title", required=True, help="Tender title.")
    register_parser.add_argument(
        "--issuing-authority",
        required=True,
        help="Issuing authority for the procurement.",
    )
    register_parser.add_argument(
        "--procurement-reference",
        help="Optional procurement reference or notice number.",
    )
    register_parser.add_argument(
        "--metadata",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        type=_metadata_pair,
        help="Optional procurement metadata; repeat for multiple key/value pairs.",
    )
    register_parser.set_defaults(handler=_run_register_demo_tender_command)

    pending_run_parser = subparsers.add_parser(
        "create-pending-run",
        help="Create a pending Supabase-backed agent run.",
        description=(
            "Create a pending Supabase-backed agent run for an existing "
            "demo tender, demo company, and registered tender document."
        ),
    )
    pending_run_parser.add_argument(
        "--tender-id",
        required=True,
        help="Existing demo tender UUID.",
    )
    pending_run_parser.add_argument(
        "--company-id",
        required=True,
        help="Existing demo company UUID.",
    )
    pending_run_parser.add_argument(
        "--document-id",
        required=True,
        help="Existing registered tender document UUID.",
    )
    pending_run_parser.set_defaults(handler=_run_create_pending_run_command)

    prepare_run_parser = subparsers.add_parser(
        "prepare-run",
        help="Prepare uploaded procurement documents and create a pending run.",
        description=(
            "Validate existing uploaded tender documents, run or reuse PDF "
            "ingestion, build tender and company evidence, then create one "
            "pending agent run for the prepared document set."
        ),
    )
    prepare_run_parser.add_argument(
        "--tender-id",
        required=True,
        help="Existing demo tender UUID.",
    )
    prepare_run_parser.add_argument(
        "--company-id",
        required=True,
        help="Existing demo company UUID.",
    )
    prepare_run_parser.add_argument(
        "--document-id",
        action="append",
        required=True,
        help=(
            "Existing uploaded tender document UUID. Repeat for multi-document "
            "procurement sets."
        ),
    )
    prepare_run_parser.set_defaults(handler=_run_prepare_run_command)

    manifest_run_parser = subparsers.add_parser(
        "prepare-manifest-run",
        help="Prepare a local multi-PDF procurement manifest.",
        description=(
            "Register every PDF listed in a local gitignored procurement "
            "manifest, then run preparation for the complete document set."
        ),
    )
    manifest_run_parser.add_argument(
        "manifest_path",
        type=Path,
        help=(
            "Path to a JSON procurement manifest, typically "
            "data/demo/incoming/<procurement-name>/procurement-manifest.json."
        ),
    )
    manifest_run_parser.set_defaults(handler=_run_prepare_manifest_run_command)

    doctor_parser = subparsers.add_parser(
        "doctor",
        aliases=["demo-doctor"],
        help="Check the local demo environment.",
        description=(
            "Check required demo environment variables, Supabase tables, "
            "Supabase Storage, and optional Anthropic connectivity."
        ),
    )
    doctor_parser.add_argument(
        "--check-anthropic",
        action="store_true",
        help=(
            "Require a live Anthropic connectivity check even when "
            "ANTHROPIC_API_KEY is missing."
        ),
    )
    doctor_parser.set_defaults(handler=_run_doctor_command)

    smoke_parser = subparsers.add_parser(
        "demo-smoke",
        aliases=["smoke-demo"],
        help="Run the bounded live-demo smoke flow.",
        description=(
            "Run a bounded opt-in demo smoke flow covering seed, PDF "
            "registration, ingestion, evidence creation, pending run creation, "
            "worker execution, and decision readback. If the PDF path is absent, "
            "a generated text-PDF fixture is used."
        ),
    )
    smoke_parser.add_argument(
        "--pdf-path",
        type=Path,
        default=Path(DEMO_TENDER_PDF_HINT),
        help=(
            "Local text-PDF path. Defaults to the preferred gitignored demo "
            f"input {DEMO_TENDER_PDF_HINT}; when absent, a generated fixture "
            "PDF is used."
        ),
    )
    smoke_parser.add_argument(
        "--live-llm",
        action="store_true",
        help=(
            "Use real Claude calls for agent outputs. By default the smoke "
            "uses deterministic mocked graph handlers."
        ),
    )
    smoke_parser.add_argument(
        "--anthropic-model",
        help=(
            "Anthropic model for --live-llm. Defaults to "
            f"{DEFAULT_ANTHROPIC_MODEL}."
        ),
    )
    smoke_parser.set_defaults(handler=_run_demo_smoke_command)

    worker_parser = subparsers.add_parser(
        "worker",
        help="Run one pending agent run through the local worker.",
        description=(
            "Run one pending Supabase-backed agent run through the local "
            "Bidded worker. Provide --run-id for a specific pending run, or "
            "omit it to pick the oldest pending demo run."
        ),
    )
    worker_parser.add_argument(
        "--run-id",
        help="Specific pending agent_runs UUID to execute.",
    )
    worker_parser.add_argument(
        "--company-id",
        help="Optional demo company UUID filter when picking the oldest pending run.",
    )
    worker_parser.set_defaults(handler=_run_worker_command)

    status_parser = subparsers.add_parser(
        "run-status",
        help="Print status and audit counters for one agent run.",
        description=(
            "Print current status, timestamps, errors, output counts, "
            "decision presence, and last recorded step for one agent run."
        ),
    )
    status_parser.add_argument("--run-id", required=True, help="agent_runs UUID.")
    status_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print the compact demo trace and highlight the latest problem step.",
    )
    status_parser.set_defaults(handler=_run_status_command)

    retry_parser = subparsers.add_parser(
        "retry-run",
        help="Create a pending retry run for a failed run.",
        description=(
            "Create a new pending run linked to a failed or needs-human-review "
            "source run. Succeeded source runs require --force."
        ),
    )
    retry_parser.add_argument("--run-id", required=True, help="Source run UUID.")
    retry_parser.add_argument(
        "--reason",
        required=True,
        help="Operator reason recorded in retry metadata.",
    )
    retry_parser.add_argument(
        "--force",
        action="store_true",
        help="Allow retrying a succeeded run and record force usage in metadata.",
    )
    retry_parser.set_defaults(handler=_run_retry_command)

    reset_parser = subparsers.add_parser(
        "reset-stale-runs",
        help="Fail running runs that are older than a configured age.",
        description=(
            "Mark running runs as failed when their started_at timestamp exceeds "
            "the configured age, recording an explicit operator reason."
        ),
    )
    reset_parser.add_argument(
        "--max-age-minutes",
        required=True,
        type=int,
        help="Minimum running age before a run is considered stale.",
    )
    reset_parser.add_argument(
        "--reason",
        required=True,
        help="Operator reason recorded on every stale reset.",
    )
    reset_parser.set_defaults(handler=_run_reset_stale_command)

    export_parser = subparsers.add_parser(
        "export-decision",
        help="Export a persisted final decision bundle.",
        description=(
            "Export a selected agent run as Markdown and JSON using persisted "
            "bid_decisions, agent_outputs, and evidence_items rows."
        ),
    )
    export_parser.add_argument("--run-id", required=True, help="agent_runs UUID.")
    export_parser.add_argument(
        "--markdown-path",
        required=True,
        type=Path,
        help="Destination path for the readable Markdown decision bundle.",
    )
    export_parser.add_argument(
        "--json-path",
        required=True,
        type=Path,
        help="Destination path for the stable JSON decision bundle.",
    )
    export_parser.set_defaults(handler=_run_export_decision_command)

    eval_parser = subparsers.add_parser(
        "eval-golden",
        help="Run deterministic golden decision evals.",
        description=(
            "Run deterministic golden decision evals for all fixture cases or "
            "one selected case ID without live Claude or live Supabase."
        ),
    )
    eval_parser.add_argument(
        "--case-id",
        help="Optional golden case ID to run instead of the full fixture set.",
    )
    eval_parser.add_argument(
        "--fixture-group",
        choices=("core", "adversarial", "all"),
        default="core",
        help=(
            "Fixture group to run. Defaults to core; use adversarial for "
            "edge-case fixtures or all for the combined set."
        ),
    )
    eval_parser.add_argument(
        "--json-path",
        type=Path,
        help="Optional destination for a stable JSON eval report.",
    )
    eval_parser.add_argument(
        "--markdown-path",
        type=Path,
        help="Optional destination for a readable Markdown eval report.",
    )
    eval_parser.add_argument(
        "--compare-live",
        action="store_true",
        help=(
            "Compare deterministic mock eval outputs with live Claude outputs. "
            "Requires --confirm-live."
        ),
    )
    eval_parser.add_argument(
        "--confirm-live",
        action="store_true",
        help="Explicitly confirm live Claude calls for --compare-live.",
    )
    eval_parser.add_argument(
        "--anthropic-model",
        help=(
            "Anthropic model for --compare-live. Defaults to "
            f"{DEFAULT_ANTHROPIC_MODEL}."
        ),
    )
    eval_parser.set_defaults(handler=_run_eval_golden_command)

    diff_parser = subparsers.add_parser(
        "diff-decisions",
        help="Diff normalized decisions from eval JSON or persisted runs.",
        description=(
            "Compare two eval-result JSON files, decision export JSON files, "
            "or persisted run IDs using normalized material decision fields."
        ),
    )
    diff_parser.add_argument(
        "--baseline-json",
        type=Path,
        help="Baseline eval-result or decision-export JSON path.",
    )
    diff_parser.add_argument(
        "--candidate-json",
        type=Path,
        help="Candidate eval-result or decision-export JSON path.",
    )
    diff_parser.add_argument(
        "--baseline-run-id",
        help="Baseline persisted agent_runs UUID.",
    )
    diff_parser.add_argument(
        "--candidate-run-id",
        help="Candidate persisted agent_runs UUID.",
    )
    diff_parser.add_argument(
        "--json-path",
        type=Path,
        help="Optional destination for a stable JSON diff report.",
    )
    diff_parser.add_argument(
        "--strict",
        action="store_true",
        help="Return exit code 1 when material decision fields differ.",
    )
    diff_parser.set_defaults(handler=_run_diff_decisions_command)
    return parser


def _create_supabase_client(settings: Any | None = None) -> Any:
    settings = settings or load_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for "
            "Supabase commands."
        )

    from supabase import create_client

    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def _create_anthropic_client(api_key: str) -> Any:
    from anthropic import Anthropic

    return Anthropic(api_key=api_key)


def _run_doctor_command(args: argparse.Namespace) -> int:
    settings = load_settings()
    result = run_demo_environment_doctor(
        settings,
        supabase_client_factory=_create_supabase_client,
        anthropic_client_factory=_create_anthropic_client,
        check_anthropic=args.check_anthropic,
    )

    print("Bidded demo environment doctor")
    for check in result.checks:
        print(f"{check.status.upper()} {check.name}: {check.message}")
    return 0 if result.passed else 1


def _run_seed_demo_company_command(_args: argparse.Namespace) -> int:
    try:
        client = _create_supabase_client()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    result = seed_demo_company(client)
    print(
        "Upserted demo company "
        f"{result.company_name} for tenant {result.tenant_key}; "
        f"rows returned: {result.rows_returned}."
    )
    return 0


def _run_seed_demo_states_command(_args: argparse.Namespace) -> int:
    try:
        client = _create_supabase_client()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    result = seed_demo_states(client)
    state_order = ["pending", "succeeded", "failed", "needs_human_review"]
    present_states = [
        state for state in state_order if state in result.run_ids_by_state
    ]
    print(
        "Seeded replayable demo states for tenant "
        f"{result.tenant_key}: {', '.join(present_states)}; "
        f"evidence items: {result.evidence_items_seeded}; "
        f"agent outputs: {result.agent_outputs_seeded}; "
        f"bid decisions: {result.bid_decisions_seeded}."
    )
    return 0


def _run_register_demo_tender_command(args: argparse.Namespace) -> int:
    settings = load_settings()
    try:
        client = _create_supabase_client(settings)
        result = register_demo_tender_pdf(
            client,
            pdf_path=args.pdf_path,
            bucket_name=settings.supabase_storage_bucket,
            tender_title=args.title,
            issuing_authority=args.issuing_authority,
            procurement_reference=args.procurement_reference,
            procurement_metadata=dict(args.metadata),
        )
    except (RuntimeError, TenderPdfRegistrationError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(
        "Registered demo tender "
        f"{args.title} as document {result.document_id}; "
        f"storage path: {result.storage_path}."
    )
    return 0


def _run_create_pending_run_command(args: argparse.Namespace) -> int:
    settings = load_settings()
    try:
        client = _create_supabase_client(settings)
        result = create_pending_run_context(
            client,
            tender_id=args.tender_id,
            company_id=args.company_id,
            document_id=args.document_id,
        )
    except (RuntimeError, PendingRunContextError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(f"Created pending agent run {result.run_id}.")
    return 0


def _run_prepare_run_command(args: argparse.Namespace) -> int:
    settings = load_settings()
    try:
        client = _create_supabase_client(settings)
        result = prepare_procurement_run(
            client,
            tender_id=args.tender_id,
            company_id=args.company_id,
            document_ids=args.document_id,
            bucket_name=settings.supabase_storage_bucket,
        )
    except (RuntimeError, PrepareRunError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    _print_prepare_run_result(result)
    return 0


def _run_prepare_manifest_run_command(args: argparse.Namespace) -> int:
    settings = load_settings()
    try:
        client = _create_supabase_client(settings)
        result = prepare_procurement_manifest_run(
            client,
            manifest_path=args.manifest_path,
            bucket_name=settings.supabase_storage_bucket,
        )
    except (
        RuntimeError,
        TenderPdfRegistrationError,
        ProcurementManifestError,
        PrepareRunError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(f"Prepared manifest procurement from {result.manifest_path}.")
    _print_prepare_run_result(result)
    return 0


def _run_worker_command(args: argparse.Namespace) -> int:
    settings = load_settings()
    try:
        client = _create_supabase_client(settings)
        result = run_worker_once(
            client,
            run_id=args.run_id,
            company_id=args.company_id,
            log=print,
        )
    except (RuntimeError, WorkerLifecycleError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if result.run_id is None:
        return 0

    if result.visited_nodes:
        print(f"Visited nodes: {', '.join(result.visited_nodes)}.")
    print(f"Agent outputs: {result.agent_output_count}.")
    if result.decision_verdict is not None:
        print(f"Decision verdict: {result.decision_verdict.value}.")
    if result.terminal_status is AgentRunStatus.FAILED:
        return 1
    return 0


def _print_prepare_run_result(result: Any) -> None:
    document_results = tuple(result.document_results)
    chunk_count = sum(summary.chunk_count for summary in document_results)
    print(
        f"Prepared pending agent run {result.agent_run_id} for tender "
        f"{result.tender_id}."
    )
    print(
        f"Documents: {len(result.document_ids)}; chunks: {chunk_count}; "
        f"tender evidence: {result.tender_evidence_count}; "
        f"company evidence: {result.company_evidence_count}; "
        f"total evidence: {result.evidence_count}."
    )
    for summary in document_results:
        print(
            f"Document {summary.document_id}: "
            f"parse_status={summary.parse_status} "
            f"chunks={summary.chunk_count} "
            f"evidence={summary.evidence_count}"
        )
    for warning in result.warnings:
        print(f"WARNING {warning}")
    audit = getattr(result, "audit", None)
    if audit is not None:
        for issue in audit.issues:
            print(f"AUDIT {issue.severity.upper()} {issue.check}: {issue.message}")


def _run_demo_smoke_command(args: argparse.Namespace) -> int:
    settings = load_settings()
    try:
        client = _create_supabase_client(settings)
    except RuntimeError as exc:
        print(_redact_known_secrets(str(exc), settings), file=sys.stderr)
        return 2

    anthropic_client = None
    if args.live_llm:
        api_key = getattr(settings, "anthropic_api_key", None)
        if not api_key:
            print("ANTHROPIC_API_KEY is required for --live-llm.", file=sys.stderr)
            return 2
        try:
            anthropic_client = _create_anthropic_client(api_key)
        except Exception as exc:  # pragma: no cover - depends on Anthropic internals
            print(_redact_known_secrets(str(exc), settings), file=sys.stderr)
            return 2

    try:
        result = run_demo_smoke(
            client,
            pdf_path=args.pdf_path,
            bucket_name=settings.supabase_storage_bucket,
            live_llm=args.live_llm,
            anthropic_client=anthropic_client,
            anthropic_model=args.anthropic_model,
        )
    except (RuntimeError, DemoSmokeError) as exc:
        print(_redact_known_secrets(str(exc), settings), file=sys.stderr)
        return 2

    _print_demo_smoke_result(result)
    return 1 if result.terminal_status is AgentRunStatus.FAILED else 0


def _run_status_command(args: argparse.Namespace) -> int:
    settings = load_settings()
    try:
        client = _create_supabase_client(settings)
        result = get_run_status(client, run_id=args.run_id)
    except (RuntimeError, RunControlError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(f"Run: {result.run_id}")
    print(f"Status: {result.status.value}")
    print(f"Created: {_display_value(result.created_at)}")
    print(f"Started: {_display_value(result.started_at)}")
    print(f"Completed: {_display_value(result.completed_at)}")
    print(f"Error: {_format_error_details(result.error_details)}")
    print(f"Agent outputs: {result.agent_output_count}")
    print(f"Decision present: {'yes' if result.decision_present else 'no'}")
    print(f"Last recorded step: {_display_value(result.last_recorded_step)}")
    if args.verbose:
        _print_demo_trace(result.demo_trace)
    return 0


def _run_retry_command(args: argparse.Namespace) -> int:
    settings = load_settings()
    try:
        client = _create_supabase_client(settings)
        result = retry_agent_run(
            client,
            run_id=args.run_id,
            reason=args.reason,
            force=args.force,
        )
    except (RuntimeError, RunControlError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(
        f"Created retry run {result.new_run_id} from "
        f"source {result.source_run_id} ({result.source_status.value})."
    )
    return 0


def _run_reset_stale_command(args: argparse.Namespace) -> int:
    settings = load_settings()
    try:
        client = _create_supabase_client(settings)
        result = reset_stale_runs(
            client,
            max_age_minutes=args.max_age_minutes,
            reason=args.reason,
        )
    except (RuntimeError, RunControlError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(f"Reset stale running runs: {result.reset_count}.")
    print(f"Skipped running runs: {result.skipped_count}.")
    if result.reset_run_ids:
        print(
            "Reset run IDs: "
            f"{', '.join(str(run_id) for run_id in result.reset_run_ids)}."
        )
    return 0


def _run_export_decision_command(args: argparse.Namespace) -> int:
    settings = load_settings()
    try:
        client = _create_supabase_client(settings)
        result = export_decision_bundle(
            client,
            run_id=args.run_id,
            markdown_path=args.markdown_path,
            json_path=args.json_path,
        )
    except (RuntimeError, DecisionExportError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(
        f"Exported decision bundle for {result.run_id} ({result.verdict}) "
        f"to {result.markdown_path} and {result.json_path}. "
        f"Evidence items: {result.evidence_count}; "
        f"agent outputs: {result.agent_output_count}."
    )
    return 0


def _run_eval_golden_command(args: argparse.Namespace) -> int:
    if args.compare_live and not args.confirm_live:
        print("--confirm-live is required for --compare-live.", file=sys.stderr)
        return 2
    if args.compare_live:
        return _run_live_golden_eval_comparison_command(args)

    try:
        result = run_golden_evals(
            case_id=args.case_id,
            fixture_group=args.fixture_group,
        )
        if args.json_path is not None:
            write_golden_eval_json(result, args.json_path)
        if args.markdown_path is not None:
            write_golden_eval_markdown(result, args.markdown_path)
    except (GoldenEvalError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    _print_golden_eval_report(result)
    if args.json_path is not None:
        print(f"Wrote JSON: {args.json_path}")
    if args.markdown_path is not None:
        print(f"Wrote Markdown: {args.markdown_path}")
    return 0 if result.passed else 1


def _run_live_golden_eval_comparison_command(args: argparse.Namespace) -> int:
    settings = load_settings()
    api_key = getattr(settings, "anthropic_api_key", None)
    if not api_key:
        try:
            result = run_live_golden_eval_comparison(
                case_id=args.case_id,
                fixture_group=args.fixture_group,
                live_unavailable_reason=(
                    "ANTHROPIC_API_KEY is required for --compare-live."
                ),
            )
            _write_live_golden_eval_comparison_outputs(result, args)
        except (GoldenEvalError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        _print_live_golden_eval_comparison_report(result)
        _print_live_golden_eval_comparison_output_paths(args)
        return 2

    try:
        client = _create_anthropic_client(api_key)
        provider = AnthropicGoldenEvalOutcomeProvider(
            client,
            model_name=args.anthropic_model or DEFAULT_ANTHROPIC_MODEL,
        )
        result = run_live_golden_eval_comparison(
            case_id=args.case_id,
            fixture_group=args.fixture_group,
            live_outcome_provider=provider,
        )
        _write_live_golden_eval_comparison_outputs(result, args)
    except (GoldenEvalError, OSError, ValueError) as exc:
        print(_redact_known_secrets(str(exc), settings), file=sys.stderr)
        return 2
    except Exception as exc:  # pragma: no cover - depends on Anthropic internals
        result = run_live_golden_eval_comparison(
            case_id=args.case_id,
            fixture_group=args.fixture_group,
            live_unavailable_reason=_redact_known_secrets(str(exc), settings),
        )
        _write_live_golden_eval_comparison_outputs(result, args)
        _print_live_golden_eval_comparison_report(result)
        _print_live_golden_eval_comparison_output_paths(args)
        return 2

    _print_live_golden_eval_comparison_report(result)
    _print_live_golden_eval_comparison_output_paths(args)
    return 0 if result.passed else 1


def _write_live_golden_eval_comparison_outputs(
    result: LiveGoldenEvalComparisonReport,
    args: argparse.Namespace,
) -> None:
    if args.json_path is not None:
        write_live_golden_eval_comparison_json(result, args.json_path)
    if args.markdown_path is not None:
        write_live_golden_eval_comparison_markdown(result, args.markdown_path)


def _print_live_golden_eval_comparison_output_paths(args: argparse.Namespace) -> None:
    if args.json_path is not None:
        print(f"Wrote JSON: {args.json_path}")
    if args.markdown_path is not None:
        print(f"Wrote Markdown: {args.markdown_path}")


def _run_diff_decisions_command(args: argparse.Namespace) -> int:
    try:
        baseline_payload, baseline_source = _load_decision_diff_payload(
            json_path=args.baseline_json,
            run_id=args.baseline_run_id,
            source_label="baseline",
        )
        candidate_payload, candidate_source = _load_decision_diff_payload(
            json_path=args.candidate_json,
            run_id=args.candidate_run_id,
            source_label="candidate",
        )
        result = diff_decision_payloads(
            baseline_payload,
            candidate_payload,
            baseline_source=baseline_source,
            candidate_source=candidate_source,
        )
        if args.json_path is not None:
            write_decision_diff_json(result, args.json_path)
    except (DecisionDiffError, OSError, json.JSONDecodeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(render_decision_diff_text(result), end="")
    if args.json_path is not None:
        print(f"Wrote JSON: {args.json_path}")
    if args.strict and result.has_material_changes:
        return 1
    return 0


def _load_decision_diff_payload(
    *,
    json_path: Path | None,
    run_id: str | None,
    source_label: str,
) -> tuple[dict[str, Any], str]:
    if json_path is not None and run_id is not None:
        raise DecisionDiffError(
            f"Provide either --{source_label}-json or "
            f"--{source_label}-run-id, not both."
        )
    if json_path is None and run_id is None:
        raise DecisionDiffError(
            f"Provide --{source_label}-json or --{source_label}-run-id."
        )
    if json_path is not None:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise DecisionDiffError(f"{json_path} must contain a JSON object.")
        return payload, str(json_path)

    try:
        client = _create_supabase_client()
    except RuntimeError as exc:
        raise DecisionDiffError(str(exc)) from exc
    assert run_id is not None
    return (
        load_persisted_run_decision_payload(client, run_id=run_id),
        f"run:{run_id}",
    )


def _display_value(value: object | None) -> str:
    return str(value) if value is not None else "none"


def _format_error_details(error_details: dict[str, Any] | None) -> str:
    if not error_details:
        return "none"
    code = _display_value(error_details.get("code"))
    source = _display_value(error_details.get("source"))
    message = _display_value(error_details.get("message"))
    return f"{code} from {source} - {message}"


def _print_demo_trace(demo_trace: tuple[DemoTraceEntry, ...]) -> None:
    if not demo_trace:
        print("Demo trace: none")
        return

    print("Demo trace:")
    highlighted_index = _latest_problem_trace_index(demo_trace)
    for index, entry in enumerate(demo_trace):
        prefix = "!" if index == highlighted_index else "OK"
        line = (
            f"{prefix} {entry.step} {entry.status} "
            f"{_display_value(entry.started_at)} -> "
            f"{_display_value(entry.completed_at)} "
            f"duration_ms={_display_value(entry.duration_ms)}"
        )
        if entry.error_code is not None:
            line = f"{line} error={entry.error_code}"
        if index == highlighted_index:
            line = f"{line} <-- latest failed/incomplete"
        print(line)


def _latest_problem_trace_index(
    demo_trace: tuple[DemoTraceEntry, ...],
) -> int | None:
    for index in range(len(demo_trace) - 1, -1, -1):
        if demo_trace[index].status != "completed":
            return index
    return None


def _print_demo_smoke_result(result: DemoSmokeResult) -> None:
    print("Bidded demo smoke")
    print(f"PDF source: {result.pdf_source}")
    print(f"Requested PDF: {_display_value(result.requested_pdf_path)}")
    print(f"Resolved PDF: {result.resolved_pdf_path}")
    print(f"LLM mode: {result.llm_mode}")
    for step in result.steps:
        print(f"{step.status.upper()} {step.name}: {step.detail}")
    print(f"Run ID: {result.run_id}")
    print(f"Terminal status: {result.terminal_status.value}")
    print(
        "Decision verdict: "
        f"{result.decision_verdict.value if result.decision_verdict else 'none'}"
    )
    print(f"Evidence count: {result.evidence_count}")
    print(f"Failure reason: {result.failure_reason or 'none'}")


def _print_golden_eval_report(report: GoldenEvalReport) -> None:
    print(f"Golden evals: {report.passed_count}/{report.total_count} passed.")
    print(f"Version metadata: {_format_version_metadata(report.version_metadata)}")
    for warning in report.version_warnings:
        print(f"WARNING {warning}")
    for result in report.results:
        _print_golden_case_eval_result(result)


def _print_golden_case_eval_result(result: GoldenCaseEvalResult) -> None:
    status = "PASS" if result.passed else "FAIL"
    print(f"{status} {result.case_id}: {result.title}")
    if result.verdict_regression_failures:
        allowed_verdicts = result.allowed_verdicts or (result.expected_verdict,)
        print(
            "  Allowed verdicts: "
            f"{_verdict_values(allowed_verdicts)}; actual: "
            f"{result.actual_verdict.value}"
        )
    elif result.expected_verdict != result.actual_verdict and not result.passed:
        print(
            "  Expected verdict: "
            f"{result.expected_verdict.value}; actual: {result.actual_verdict.value}"
        )
    _print_issue_tuple(
        "Verdict regression failures",
        result.verdict_regression_failures,
    )
    _print_issue_tuple("Missing required blockers", result.missing_required_blockers)
    _print_issue_tuple("Unexpected hard blockers", result.unexpected_hard_blockers)
    _print_issue_tuple(
        "Missing required missing info",
        result.missing_required_missing_info,
    )
    _print_issue_tuple(
        "Missing required recommended actions",
        result.missing_required_recommended_actions,
    )
    _print_issue_tuple(
        "Missing unsupported-claim rejections",
        result.missing_expected_unsupported_claim_rejections,
    )
    _print_issue_tuple(
        "Unexpected unsupported-claim rejections",
        result.unexpected_unsupported_claim_rejections,
    )
    _print_issue_tuple("Validation errors", result.actual_validation_errors)
    _print_issue_tuple(
        "Missing expected validation errors",
        result.missing_expected_validation_errors,
    )
    _print_issue_tuple(
        "Unexpected validation errors",
        result.unexpected_validation_errors,
    )
    _print_issue_tuple(
        "Evidence-reference failures",
        result.evidence_reference_failures,
    )
    if not result.evidence_coverage.passed:
        coverage = result.evidence_coverage
        print(
            "  Evidence coverage: "
            f"{coverage.score:.2f} below threshold {coverage.threshold:.2f}"
        )
        if coverage.unsupported_claim_count:
            print(
                "  Unsupported material claims: "
                f"{coverage.unsupported_claim_count}"
            )
        for detail in coverage.missing_citation_details:
            missing = _source_type_values(detail.missing_source_types)
            present = _source_type_values(detail.present_source_types)
            unresolved = ", ".join(detail.unresolved_evidence_refs) or "none"
            print(
                "  Missing citation: "
                f"{detail.claim_type.value} - {detail.claim} "
                f"reason={detail.reason}; missing={missing}; "
                f"present={present}; unresolved={unresolved}"
            )


def _print_live_golden_eval_comparison_report(
    report: LiveGoldenEvalComparisonReport,
) -> None:
    print(f"Live golden eval comparison: {report.status.value}")
    print(
        "Mock evals: "
        f"{report.mock_report.passed_count}/{report.mock_report.total_count} "
        f"{'passed' if report.mock_report.passed else 'failed'}"
    )
    print(f"Compared cases: {report.compared_count}/{report.total_count}")
    print(f"Unavailable cases: {report.unavailable_count}")
    print(f"Live validation failures: {report.validation_failure_count}")
    print(f"Differences: {report.difference_count}")
    if report.unavailable_reason:
        print(report.unavailable_reason)
    for comparison in report.case_comparisons:
        status = _live_comparison_case_status(comparison).upper()
        live_verdict = (
            comparison.live_result.actual_verdict.value
            if comparison.live_result is not None
            else "n/a"
        )
        print(
            f"{status} {comparison.case_id}: "
            f"mock={comparison.mock_result.actual_verdict.value}; "
            f"live={live_verdict}; "
            f"latency_ms={_display_value(comparison.latency_ms)}; "
            f"input_tokens={_display_value(comparison.input_tokens)}; "
            f"output_tokens={_display_value(comparison.output_tokens)}; "
            f"estimated_cost_usd={_display_value(comparison.estimated_cost_usd)}"
        )
        if comparison.live_unavailable_reason:
            print(f"  Live unavailable: {comparison.live_unavailable_reason}")
        if comparison.live_validation_failure:
            print(f"  Live validation failure: {comparison.live_validation_failure}")
        if comparison.verdict_changed:
            print("  Verdict changed: yes")
        if comparison.validation_errors_changed:
            print(
                "  Validation errors changed: "
                f"mock={_joined_issue_values(comparison.mock_validation_errors)}; "
                f"live={_joined_issue_values(comparison.live_validation_errors)}"
            )
        if comparison.evidence_coverage_delta not in (None, 0):
            print(
                "  Evidence coverage delta: "
                f"{comparison.evidence_coverage_delta:+.2f}"
            )


def _live_comparison_case_status(comparison: Any) -> str:
    if comparison.live_unavailable_reason:
        return "unavailable"
    if comparison.live_validation_failure:
        return "validation_failure"
    if comparison.has_difference:
        return "diff"
    return "match"


def _joined_issue_values(values: tuple[str, ...]) -> str:
    return "; ".join(values) or "none"


def _print_issue_tuple(label: str, values: tuple[str, ...]) -> None:
    if values:
        print(f"  {label}: {'; '.join(values)}")


def _source_type_values(values: tuple[Any, ...]) -> str:
    return ", ".join(value.value for value in values) or "none"


def _format_version_metadata(metadata: Any) -> str:
    fields = (
        "prompt_version",
        "schema_version",
        "retrieval_version",
        "model_name",
        "eval_fixture_version",
    )
    values = [
        f"{field}={value}"
        for field in fields
        if (value := getattr(metadata, field, None)) is not None
    ]
    return "; ".join(values) or "none"


def _verdict_values(values: tuple[Any, ...]) -> str:
    return ", ".join(value.value for value in values) or "none"


def _redact_known_secrets(message: str, settings: Any) -> str:
    redacted = message
    for attr in ("supabase_service_role_key", "anthropic_api_key"):
        secret = getattr(settings, attr, None)
        if secret:
            redacted = redacted.replace(str(secret), "[redacted]")
    return redacted


def _metadata_pair(value: str) -> tuple[str, str]:
    key, separator, metadata_value = value.partition("=")
    key = key.strip()
    if not separator or not key:
        raise argparse.ArgumentTypeError("metadata must be provided as KEY=VALUE")
    return key, metadata_value.strip()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        return 0
    return handler(args)
