from __future__ import annotations

import argparse
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
from bidded.orchestration import (
    AgentRunStatus,
    PendingRunContextError,
    WorkerLifecycleError,
    create_pending_run_context,
    run_worker_once,
)
from bidded.orchestration.run_controls import (
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


def _display_value(value: object | None) -> str:
    return str(value) if value is not None else "none"


def _format_error_details(error_details: dict[str, Any] | None) -> str:
    if not error_details:
        return "none"
    code = _display_value(error_details.get("code"))
    source = _display_value(error_details.get("source"))
    message = _display_value(error_details.get("message"))
    return f"{code} from {source} - {message}"


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
