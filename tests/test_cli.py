from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

import bidded.cli as cli
from bidded.db.seed_demo_company import DEMO_COMPANY_NAME

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
