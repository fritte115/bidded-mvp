from __future__ import annotations

import argparse
import sys
from typing import Any

from bidded import __version__
from bidded.config import load_settings
from bidded.db.seed_demo_company import seed_demo_company


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
    return parser


def _create_supabase_client() -> Any:
    settings = load_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for seeding."
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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        return 0
    return handler(args)
