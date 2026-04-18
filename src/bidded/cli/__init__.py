from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from bidded import __version__
from bidded.config import load_settings
from bidded.db.seed_demo_company import seed_demo_company
from bidded.documents import TenderPdfRegistrationError, register_demo_tender_pdf
from bidded.orchestration import (
    AgentRunStatus,
    PendingRunContextError,
    WorkerLifecycleError,
    create_pending_run_context,
    run_worker_once,
)
from bidded.orchestration.evidence_locked_swarm import evidence_locked_graph_handlers

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

    serve_parser = subparsers.add_parser(
        "serve",
        help="Start the Bidded HTTP API server.",
        description="Start the Bidded HTTP API server (default: http://0.0.0.0:8000).",
    )
    serve_parser.add_argument("--host", default="0.0.0.0", help="Bind host.")
    serve_parser.add_argument("--port", type=int, default=8000, help="Bind port.")
    serve_parser.set_defaults(handler=_run_serve_command)

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
            document_ids=[args.document_id],
        )
    except (RuntimeError, PendingRunContextError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(f"Created pending agent run {result.run_id}.")
    return 0


def _run_serve_command(args: argparse.Namespace) -> int:
    try:
        import uvicorn  # noqa: PLC0415

        from bidded.api_server import app  # noqa: PLC0415
    except ImportError:
        print(
            "fastapi and uvicorn are required. "
            "Run: pip install fastapi 'uvicorn[standard]'",
            file=sys.stderr,
        )
        return 2
    uvicorn.run(app, host=args.host, port=args.port)
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
            graph_handlers=evidence_locked_graph_handlers(),
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
