from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import bidded.cli as cli
from bidded.db.seed_demo_company import DEMO_COMPANY_NAME
from bidded.orchestration import AgentRunStatus, Verdict

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_cli_help_prints_without_external_services() -> None:
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("SUPABASE_URL", None)
    env.pop("SUPABASE_SERVICE_ROLE_KEY", None)
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")

    result = subprocess.run(
        [sys.executable, "-m", "bidded.cli", "--help"],
        cwd=PROJECT_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "Bidded" in result.stdout
    assert "usage:" in result.stdout.lower()
    assert "seed-demo-company" in result.stdout


def test_cli_seed_demo_company_help_prints_without_external_services() -> None:
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("SUPABASE_URL", None)
    env.pop("SUPABASE_SERVICE_ROLE_KEY", None)
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")

    result = subprocess.run(
        [sys.executable, "-m", "bidded.cli", "seed-demo-company", "--help"],
        cwd=PROJECT_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "seed-demo-company" in result.stdout
    assert "demo IT consultancy company" in result.stdout


def test_cli_register_demo_tender_help_prints_demo_pdf_hint_without_services() -> None:
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("SUPABASE_URL", None)
    env.pop("SUPABASE_SERVICE_ROLE_KEY", None)
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")

    result = subprocess.run(
        [sys.executable, "-m", "bidded.cli", "register-demo-tender", "--help"],
        cwd=PROJECT_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "register-demo-tender" in result.stdout
    assert "data/demo/incoming/Bilaga Skakrav.pdf" in result.stdout


def test_cli_create_pending_run_help_prints_without_external_services() -> None:
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("SUPABASE_URL", None)
    env.pop("SUPABASE_SERVICE_ROLE_KEY", None)
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")

    result = subprocess.run(
        [sys.executable, "-m", "bidded.cli", "create-pending-run", "--help"],
        cwd=PROJECT_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "create-pending-run" in result.stdout
    assert "--tender-id" in result.stdout
    assert "--company-id" in result.stdout
    assert "--document-id" in result.stdout


def test_cli_worker_help_prints_without_external_services() -> None:
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("SUPABASE_URL", None)
    env.pop("SUPABASE_SERVICE_ROLE_KEY", None)
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")

    result = subprocess.run(
        [sys.executable, "-m", "bidded.cli", "worker", "--help"],
        cwd=PROJECT_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "worker" in result.stdout
    assert "--run-id" in result.stdout
    assert "--company-id" in result.stdout


class RecordingCompanyTable:
    def __init__(self) -> None:
        self.upserts: list[tuple[dict[str, Any], str | None]] = []

    def upsert(
        self,
        payload: dict[str, Any],
        *,
        on_conflict: str | None = None,
    ) -> RecordingCompanyTable:
        self.upserts.append((payload, on_conflict))
        return self

    def execute(self) -> object:
        payload = self.upserts[-1][0]
        return type("Response", (), {"data": [payload]})()


class RecordingSupabaseClient:
    def __init__(self) -> None:
        self.company_table = RecordingCompanyTable()
        self.table_names: list[str] = []

    def table(self, table_name: str) -> RecordingCompanyTable:
        self.table_names.append(table_name)
        return self.company_table


def test_cli_seed_demo_company_upserts_demo_company(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = RecordingSupabaseClient()
    monkeypatch.setattr(cli, "_create_supabase_client", lambda: client)

    result = cli.main(["seed-demo-company"])

    captured = capsys.readouterr()
    assert result == 0
    assert DEMO_COMPANY_NAME in captured.out
    assert client.table_names == ["companies"]
    assert client.company_table.upserts[0][1] == "tenant_key,name"


def test_cli_register_demo_tender_fails_without_supabase_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pdf_path = tmp_path / "tender.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda: type(
            "Settings",
            (),
            {
                "supabase_url": None,
                "supabase_service_role_key": None,
                "supabase_storage_bucket": "procurement-fixtures",
            },
        )(),
    )

    result = cli.main(
        [
            "register-demo-tender",
            str(pdf_path),
            "--title",
            "Skakrav",
            "--issuing-authority",
            "Example Municipality",
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY" in captured.err


def test_cli_register_demo_tender_accepts_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pdf_path = tmp_path / "tender.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    client = object()
    captured_registration: dict[str, Any] = {}
    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda: type(
            "Settings",
            (),
            {
                "supabase_url": "https://example.supabase.co",
                "supabase_service_role_key": "service-role",
                "supabase_storage_bucket": "procurement-fixtures",
            },
        )(),
    )
    monkeypatch.setattr(cli, "_create_supabase_client", lambda _settings: client)

    def record_registration(
        supabase_client: object,
        **kwargs: Any,
    ) -> SimpleNamespace:
        captured_registration["client"] = supabase_client
        captured_registration.update(kwargs)
        return SimpleNamespace(
            document_id="document-1",
            storage_path="demo/procurements/skakrav/tender.pdf",
        )

    monkeypatch.setattr(cli, "register_demo_tender_pdf", record_registration)

    result = cli.main(
        [
            "register-demo-tender",
            str(pdf_path),
            "--title",
            "Skakrav",
            "--issuing-authority",
            "Example Municipality",
            "--procurement-reference",
            "REF-2026-001",
            "--metadata",
            "procedure=open",
            "--metadata",
            "cpv=72000000",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert "Registered demo tender Skakrav" in captured.out
    assert captured_registration == {
        "client": client,
        "pdf_path": pdf_path,
        "bucket_name": "procurement-fixtures",
        "tender_title": "Skakrav",
        "issuing_authority": "Example Municipality",
        "procurement_reference": "REF-2026-001",
        "procurement_metadata": {"procedure": "open", "cpv": "72000000"},
    }


def test_cli_create_pending_run_delegates_to_service(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = object()
    captured_run: dict[str, Any] = {}
    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda: type(
            "Settings",
            (),
            {
                "supabase_url": "https://example.supabase.co",
                "supabase_service_role_key": "service-role",
            },
        )(),
    )
    monkeypatch.setattr(cli, "_create_supabase_client", lambda _settings: client)

    def record_pending_run(
        supabase_client: object,
        **kwargs: Any,
    ) -> SimpleNamespace:
        captured_run["client"] = supabase_client
        captured_run.update(kwargs)
        return SimpleNamespace(run_id="11111111-1111-4111-8111-111111111111")

    monkeypatch.setattr(cli, "create_pending_run_context", record_pending_run)

    result = cli.main(
        [
            "create-pending-run",
            "--tender-id",
            "33333333-3333-4333-8333-333333333333",
            "--company-id",
            "22222222-2222-4222-8222-222222222222",
            "--document-id",
            "44444444-4444-4444-8444-444444444444",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert "Created pending agent run 11111111-1111-4111-8111-111111111111" in (
        captured.out
    )
    assert captured_run == {
        "client": client,
        "tender_id": "33333333-3333-4333-8333-333333333333",
        "company_id": "22222222-2222-4222-8222-222222222222",
        "document_ids": ["44444444-4444-4444-8444-444444444444"],
    }


def test_cli_worker_delegates_to_lifecycle_service(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = object()
    captured_worker: dict[str, Any] = {}
    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda: type(
            "Settings",
            (),
            {
                "supabase_url": "https://example.supabase.co",
                "supabase_service_role_key": "service-role",
                "anthropic_api_key": None,
                "bidded_swarm_backend": "evidence_locked",
                "bidded_anthropic_model": "claude-3-5-sonnet-20241022",
            },
        )(),
    )
    monkeypatch.setattr(cli, "_create_supabase_client", lambda _settings: client)

    def record_worker(supabase_client: object, **kwargs: Any) -> SimpleNamespace:
        captured_worker["client"] = supabase_client
        captured_worker.update(kwargs)
        kwargs["log"]("Starting agent run 11111111-1111-4111-8111-111111111111.")
        return SimpleNamespace(
            run_id="11111111-1111-4111-8111-111111111111",
            terminal_status=AgentRunStatus.SUCCEEDED,
            visited_nodes=("preflight", "END"),
            agent_output_count=10,
            decision_verdict=Verdict.CONDITIONAL_BID,
            message=(
                "Agent run 11111111-1111-4111-8111-111111111111 finished "
                "with succeeded; verdict: conditional_bid."
            ),
        )

    monkeypatch.setattr(cli, "run_worker_once", record_worker)

    result = cli.main(
        [
            "worker",
            "--run-id",
            "11111111-1111-4111-8111-111111111111",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert "Starting agent run" in captured.out
    assert "Agent outputs: 10" in captured.out
    assert "Decision verdict: conditional_bid" in captured.out
    assert captured_worker["client"] is client
    assert captured_worker["run_id"] == "11111111-1111-4111-8111-111111111111"
    assert captured_worker["company_id"] is None
