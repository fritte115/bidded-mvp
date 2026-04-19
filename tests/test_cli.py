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
from bidded.db.seed_demo_states import DemoStatesSeedResult
from bidded.evals.golden_runner import GoldenCaseEvalResult, GoldenEvalReport
from bidded.orchestration import AgentRunStatus, Verdict
from bidded.orchestration.run_controls import (
    DemoTraceEntry,
    RetryRunResult,
    RunStatusSnapshot,
    StaleResetResult,
)

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
    assert "seed-demo-states" in result.stdout
    assert "doctor" in result.stdout
    assert "demo-smoke" in result.stdout
    assert "run-status" in result.stdout
    assert "retry-run" in result.stdout
    assert "reset-stale-runs" in result.stdout
    assert "export-decision" in result.stdout
    assert "eval-golden" in result.stdout


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


def test_cli_seed_demo_states_help_prints_without_external_services() -> None:
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("SUPABASE_URL", None)
    env.pop("SUPABASE_SERVICE_ROLE_KEY", None)
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")

    result = subprocess.run(
        [sys.executable, "-m", "bidded.cli", "seed-demo-states", "--help"],
        cwd=PROJECT_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "seed-demo-states" in result.stdout
    assert "pending, succeeded, failed, and needs-human-review" in (
        result.stdout.replace("\n", " ")
    )


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


def test_cli_doctor_help_prints_without_external_services() -> None:
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("SUPABASE_URL", None)
    env.pop("SUPABASE_SERVICE_ROLE_KEY", None)
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")

    result = subprocess.run(
        [sys.executable, "-m", "bidded.cli", "doctor", "--help"],
        cwd=PROJECT_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "doctor" in result.stdout
    assert "--check-anthropic" in result.stdout


def test_cli_demo_smoke_help_prints_without_external_services() -> None:
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("SUPABASE_URL", None)
    env.pop("SUPABASE_SERVICE_ROLE_KEY", None)
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")

    result = subprocess.run(
        [sys.executable, "-m", "bidded.cli", "demo-smoke", "--help"],
        cwd=PROJECT_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "demo-smoke" in result.stdout
    assert "--pdf-path" in result.stdout
    assert "--live-llm" in result.stdout


def test_cli_export_decision_help_prints_without_external_services() -> None:
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("SUPABASE_URL", None)
    env.pop("SUPABASE_SERVICE_ROLE_KEY", None)
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")

    result = subprocess.run(
        [sys.executable, "-m", "bidded.cli", "export-decision", "--help"],
        cwd=PROJECT_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "export-decision" in result.stdout
    assert "--run-id" in result.stdout
    assert "--markdown-path" in result.stdout
    assert "--json-path" in result.stdout


def test_cli_eval_golden_help_prints_without_external_services() -> None:
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("SUPABASE_URL", None)
    env.pop("SUPABASE_SERVICE_ROLE_KEY", None)
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")

    result = subprocess.run(
        [sys.executable, "-m", "bidded.cli", "eval-golden", "--help"],
        cwd=PROJECT_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "eval-golden" in result.stdout
    assert "--case-id" in result.stdout
    assert "--json-path" in result.stdout


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


def test_cli_seed_demo_states_invokes_replayable_fixture_seed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = object()
    monkeypatch.setattr(cli, "_create_supabase_client", lambda: client)

    def record_seed(received_client: object) -> DemoStatesSeedResult:
        assert received_client is client
        return DemoStatesSeedResult(
            tenant_key="demo",
            company_id="11111111-1111-4111-8111-111111111111",
            tender_id="22222222-2222-4222-8222-222222222222",
            document_id="33333333-3333-4333-8333-333333333333",
            run_ids_by_state={
                "pending": "44444444-4444-4444-8444-444444444441",
                "succeeded": "44444444-4444-4444-8444-444444444442",
                "failed": "44444444-4444-4444-8444-444444444443",
                "needs_human_review": "44444444-4444-4444-8444-444444444444",
            },
            evidence_items_seeded=9,
            agent_outputs_seeded=12,
            bid_decisions_seeded=2,
        )

    monkeypatch.setattr(cli, "seed_demo_states", record_seed)

    result = cli.main(["seed-demo-states"])

    captured = capsys.readouterr()
    assert result == 0
    assert "Seeded replayable demo states for tenant demo" in captured.out
    assert "pending, succeeded, failed, needs_human_review" in captured.out
    assert "evidence items: 9" in captured.out


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
            storage_path="demo/tenders/skakrav/tender.pdf",
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
        "document_id": "44444444-4444-4444-8444-444444444444",
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


def test_cli_demo_smoke_delegates_and_prints_operator_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pdf_path = tmp_path / "missing.pdf"
    client = object()
    captured_smoke: dict[str, Any] = {}
    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda: type(
            "Settings",
            (),
            {
                "supabase_url": "https://example.supabase.co",
                "supabase_service_role_key": "test-service-role-secret",
                "supabase_storage_bucket": "procurement-fixtures",
                "anthropic_api_key": None,
            },
        )(),
    )
    monkeypatch.setattr(cli, "_create_supabase_client", lambda _settings: client)

    def fail_anthropic_client(_api_key: str) -> object:
        raise AssertionError("mocked smoke must not construct Anthropic")

    monkeypatch.setattr(cli, "_create_anthropic_client", fail_anthropic_client)

    def record_smoke(supabase_client: object, **kwargs: Any) -> SimpleNamespace:
        captured_smoke["client"] = supabase_client
        captured_smoke.update(kwargs)
        return SimpleNamespace(
            requested_pdf_path=pdf_path,
            resolved_pdf_path=tmp_path / "bidded-smoke-tender.pdf",
            pdf_source="generated_fixture",
            llm_mode="mocked",
            run_id="11111111-1111-4111-8111-111111111111",
            terminal_status=AgentRunStatus.SUCCEEDED,
            decision_verdict=Verdict.CONDITIONAL_BID,
            evidence_count=14,
            failure_reason=None,
            steps=[
                SimpleNamespace(
                    name="seed_demo_company",
                    status="ok",
                    detail="seeded Nordic Digital Delivery AB",
                ),
                SimpleNamespace(
                    name="read_decision",
                    status="ok",
                    detail="status succeeded; decision present yes",
                ),
            ],
        )

    monkeypatch.setattr(cli, "run_demo_smoke", record_smoke)

    result = cli.main(["demo-smoke", "--pdf-path", str(pdf_path)])

    captured = capsys.readouterr()
    assert result == 0
    assert "Bidded demo smoke" in captured.out
    assert "PDF source: generated_fixture" in captured.out
    assert "LLM mode: mocked" in captured.out
    assert "OK seed_demo_company: seeded Nordic Digital Delivery AB" in captured.out
    assert "Terminal status: succeeded" in captured.out
    assert "Decision verdict: conditional_bid" in captured.out
    assert "Evidence count: 14" in captured.out
    assert "Failure reason: none" in captured.out
    assert "test-service-role-secret" not in captured.out
    assert captured_smoke == {
        "client": client,
        "pdf_path": pdf_path,
        "bucket_name": "procurement-fixtures",
        "live_llm": False,
        "anthropic_client": None,
        "anthropic_model": None,
    }


def test_cli_demo_smoke_live_llm_creates_anthropic_client(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = object()
    anthropic_client = object()
    captured_smoke: dict[str, Any] = {}
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
                "anthropic_api_key": "sk-ant-test-secret",
            },
        )(),
    )
    monkeypatch.setattr(cli, "_create_supabase_client", lambda _settings: client)
    monkeypatch.setattr(
        cli,
        "_create_anthropic_client",
        lambda api_key: anthropic_client if api_key == "sk-ant-test-secret" else None,
    )

    def record_smoke(supabase_client: object, **kwargs: Any) -> SimpleNamespace:
        captured_smoke["client"] = supabase_client
        captured_smoke.update(kwargs)
        return SimpleNamespace(
            requested_pdf_path=Path(cli.DEMO_TENDER_PDF_HINT),
            resolved_pdf_path=Path(cli.DEMO_TENDER_PDF_HINT),
            pdf_source="provided",
            llm_mode="live",
            run_id="11111111-1111-4111-8111-111111111111",
            terminal_status=AgentRunStatus.SUCCEEDED,
            decision_verdict=Verdict.BID,
            evidence_count=15,
            failure_reason=None,
            steps=[],
        )

    monkeypatch.setattr(cli, "run_demo_smoke", record_smoke)

    result = cli.main(
        [
            "demo-smoke",
            "--live-llm",
            "--anthropic-model",
            "claude-test-model",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert "LLM mode: live" in captured.out
    assert "Decision verdict: bid" in captured.out
    assert captured_smoke == {
        "client": client,
        "pdf_path": Path(cli.DEMO_TENDER_PDF_HINT),
        "bucket_name": "procurement-fixtures",
        "live_llm": True,
        "anthropic_client": anthropic_client,
        "anthropic_model": "claude-test-model",
    }


def test_cli_demo_smoke_live_llm_requires_anthropic_key(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = object()
    monkeypatch.setattr(
        cli,
        "load_settings",
        lambda: type(
            "Settings",
            (),
            {
                "supabase_url": "https://example.supabase.co",
                "supabase_service_role_key": "test-service-role-secret",
                "supabase_storage_bucket": "procurement-fixtures",
                "anthropic_api_key": None,
            },
        )(),
    )
    monkeypatch.setattr(cli, "_create_supabase_client", lambda _settings: client)
    monkeypatch.setattr(
        cli,
        "run_demo_smoke",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("smoke should not run without an Anthropic key")
        ),
    )

    result = cli.main(["demo-smoke", "--live-llm"])

    captured = capsys.readouterr()
    assert result == 2
    assert "ANTHROPIC_API_KEY is required" in captured.err
    assert "test-service-role-secret" not in captured.err


def test_cli_run_status_prints_operator_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = object()
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

    def record_status(supabase_client: object, **kwargs: Any) -> RunStatusSnapshot:
        assert supabase_client is client
        assert kwargs == {
            "run_id": "11111111-1111-4111-8111-111111111111"
        }
        return RunStatusSnapshot(
            run_id="11111111-1111-4111-8111-111111111111",
            status=AgentRunStatus.FAILED,
            created_at="2026-04-18T17:00:00+00:00",
            started_at="2026-04-18T17:30:00+00:00",
            completed_at="2026-04-18T17:45:00+00:00",
            error_details={
                "code": "graph_failed",
                "message": "Evidence board is empty.",
                "source": "graph",
            },
            agent_output_count=10,
            decision_present=True,
            last_recorded_step="judge",
        )

    monkeypatch.setattr(cli, "get_run_status", record_status)

    result = cli.main(
        [
            "run-status",
            "--run-id",
            "11111111-1111-4111-8111-111111111111",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert "Run: 11111111-1111-4111-8111-111111111111" in captured.out
    assert "Status: failed" in captured.out
    assert "Created: 2026-04-18T17:00:00+00:00" in captured.out
    assert "Started: 2026-04-18T17:30:00+00:00" in captured.out
    assert "Completed: 2026-04-18T17:45:00+00:00" in captured.out
    assert "Error: graph_failed from graph - Evidence board is empty." in (
        captured.out
    )
    assert "Agent outputs: 10" in captured.out
    assert "Decision present: yes" in captured.out
    assert "Last recorded step: judge" in captured.out


def test_cli_run_status_verbose_prints_demo_trace_with_latest_problem_step(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = object()
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

    def record_status(supabase_client: object, **kwargs: Any) -> RunStatusSnapshot:
        assert supabase_client is client
        assert kwargs == {
            "run_id": "11111111-1111-4111-8111-111111111111"
        }
        return RunStatusSnapshot(
            run_id="11111111-1111-4111-8111-111111111111",
            status=AgentRunStatus.FAILED,
            created_at="2026-04-18T17:00:00+00:00",
            started_at="2026-04-18T17:30:00+00:00",
            completed_at="2026-04-18T17:45:00+00:00",
            error_details={
                "code": "graph_failed",
                "message": "Evidence board is empty.",
                "source": "graph",
            },
            agent_output_count=10,
            decision_present=False,
            last_recorded_step="run_graph",
            demo_trace=(
                DemoTraceEntry(
                    step="claim_run",
                    status="completed",
                    started_at="2026-04-18T17:30:00+00:00",
                    completed_at="2026-04-18T17:30:00+00:00",
                    duration_ms=0,
                    error_code=None,
                ),
                DemoTraceEntry(
                    step="run_graph",
                    status="failed",
                    started_at="2026-04-18T17:31:00+00:00",
                    completed_at="2026-04-18T17:32:00+00:00",
                    duration_ms=60_000,
                    error_code="graph_failed",
                ),
            ),
        )

    monkeypatch.setattr(cli, "get_run_status", record_status)

    result = cli.main(
        [
            "run-status",
            "--run-id",
            "11111111-1111-4111-8111-111111111111",
            "--verbose",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert "Demo trace:" in captured.out
    assert (
        "OK claim_run completed 2026-04-18T17:30:00+00:00 -> "
        "2026-04-18T17:30:00+00:00 duration_ms=0"
    ) in captured.out
    assert (
        "! run_graph failed 2026-04-18T17:31:00+00:00 -> "
        "2026-04-18T17:32:00+00:00 duration_ms=60000 "
        "error=graph_failed <-- latest failed/incomplete"
    ) in captured.out


def test_cli_retry_run_delegates_and_prints_lineage(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = object()
    captured_retry: dict[str, Any] = {}
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

    def record_retry(supabase_client: object, **kwargs: Any) -> RetryRunResult:
        captured_retry["client"] = supabase_client
        captured_retry.update(kwargs)
        return RetryRunResult(
            source_run_id="11111111-1111-4111-8111-111111111111",
            new_run_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            source_status=AgentRunStatus.FAILED,
        )

    monkeypatch.setattr(cli, "retry_agent_run", record_retry)

    result = cli.main(
        [
            "retry-run",
            "--run-id",
            "11111111-1111-4111-8111-111111111111",
            "--reason",
            "retry after fixture repair",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert "Created retry run aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa" in captured.out
    assert "source 11111111-1111-4111-8111-111111111111" in captured.out
    assert captured_retry == {
        "client": client,
        "run_id": "11111111-1111-4111-8111-111111111111",
        "reason": "retry after fixture repair",
        "force": False,
    }


def test_cli_reset_stale_runs_delegates_and_prints_count(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = object()
    captured_reset: dict[str, Any] = {}
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

    def record_reset(supabase_client: object, **kwargs: Any) -> StaleResetResult:
        captured_reset["client"] = supabase_client
        captured_reset.update(kwargs)
        return StaleResetResult(
            reset_count=1,
            reset_run_ids=["11111111-1111-4111-8111-111111111111"],
            skipped_count=2,
        )

    monkeypatch.setattr(cli, "reset_stale_runs", record_reset)

    result = cli.main(
        [
            "reset-stale-runs",
            "--max-age-minutes",
            "45",
            "--reason",
            "operator confirmed worker stopped",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert "Reset stale running runs: 1" in captured.out
    assert "Skipped running runs: 2" in captured.out
    assert "11111111-1111-4111-8111-111111111111" in captured.out
    assert captured_reset == {
        "client": client,
        "max_age_minutes": 45,
        "reason": "operator confirmed worker stopped",
    }


def test_cli_eval_golden_runs_selected_case_and_writes_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    json_path = tmp_path / "golden-eval.json"

    result = cli.main(
        [
            "eval-golden",
            "--case-id",
            "obvious_bid",
            "--json-path",
            str(json_path),
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert "Golden evals: 1/1 passed" in captured.out
    assert "PASS obvious_bid" in captured.out
    assert "Wrote JSON" in captured.out
    assert '"case_id": "obvious_bid"' in json_path.read_text(encoding="utf-8")


def test_cli_eval_golden_returns_nonzero_for_failed_expectations(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    failed_report = GoldenEvalReport(
        passed=False,
        total_count=1,
        passed_count=0,
        failed_count=1,
        results=(
            GoldenCaseEvalResult(
                case_id="hard_compliance_no_bid",
                title="Hard compliance no-bid",
                passed=False,
                expected_verdict=Verdict.NO_BID,
                actual_verdict=Verdict.BID,
                missing_required_blockers=("Required blocker.",),
                unexpected_hard_blockers=("Unexpected blocker.",),
                unexpected_validation_errors=("schema_error",),
                actual_validation_errors=("schema_error",),
                evidence_reference_failures=("missing required evidence ref: E1",),
            ),
        ),
    )
    monkeypatch.setattr(cli, "run_golden_evals", lambda **_kwargs: failed_report)

    result = cli.main(["eval-golden", "--case-id", "hard_compliance_no_bid"])

    captured = capsys.readouterr()
    assert result == 1
    assert "Golden evals: 0/1 passed" in captured.out
    assert "FAIL hard_compliance_no_bid" in captured.out
    assert "Expected verdict: no_bid; actual: bid" in captured.out
    assert "Missing required blockers: Required blocker." in captured.out
    assert "Unexpected hard blockers: Unexpected blocker." in captured.out
    assert "Validation errors: schema_error" in captured.out
    assert "Evidence-reference failures: missing required evidence ref: E1" in (
        captured.out
    )
