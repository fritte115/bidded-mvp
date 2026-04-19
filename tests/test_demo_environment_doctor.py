from __future__ import annotations

from types import SimpleNamespace

import pytest

import bidded.cli as cli


class RecordingDoctorQuery:
    def __init__(self, table_name: str, *, should_fail: bool = False) -> None:
        self.table_name = table_name
        self.should_fail = should_fail
        self.selected_columns: str | None = None
        self.limit_value: int | None = None

    def select(self, columns: str) -> RecordingDoctorQuery:
        self.selected_columns = columns
        return self

    def limit(self, row_limit: int) -> RecordingDoctorQuery:
        self.limit_value = row_limit
        return self

    def execute(self) -> object:
        if self.should_fail:
            raise RuntimeError(f"relation {self.table_name} does not exist")
        return SimpleNamespace(data=[])


class RecordingDoctorStorageBucket:
    def __init__(self, *, fail_upload: bool = False) -> None:
        self.fail_upload = fail_upload
        self.uploads: list[tuple[str, bytes, dict[str, str] | None]] = []
        self.downloads: list[str] = []
        self.removals: list[list[str]] = []
        self.files: dict[str, bytes] = {}

    def upload(
        self,
        path: str,
        file: bytes,
        *,
        file_options: dict[str, str] | None = None,
    ) -> object:
        if self.fail_upload:
            raise RuntimeError("bucket not found")
        self.uploads.append((path, file, file_options))
        self.files[path] = file
        return SimpleNamespace(data={"path": path})

    def download(self, path: str) -> bytes:
        self.downloads.append(path)
        return self.files[path]

    def remove(self, paths: list[str]) -> object:
        self.removals.append(paths)
        for path in paths:
            self.files.pop(path, None)
        return SimpleNamespace(data=paths)


class RecordingDoctorStorage:
    def __init__(self, *, fail_upload: bool = False) -> None:
        self.bucket_names: list[str] = []
        self.bucket = RecordingDoctorStorageBucket(fail_upload=fail_upload)

    def from_(self, bucket_name: str) -> RecordingDoctorStorageBucket:
        self.bucket_names.append(bucket_name)
        return self.bucket


class RecordingDoctorSupabaseClient:
    def __init__(
        self,
        *,
        failing_tables: set[str] | None = None,
        fail_storage_upload: bool = False,
    ) -> None:
        self.failing_tables = failing_tables or set()
        self.table_names: list[str] = []
        self.storage = RecordingDoctorStorage(fail_upload=fail_storage_upload)

    def table(self, table_name: str) -> RecordingDoctorQuery:
        self.table_names.append(table_name)
        return RecordingDoctorQuery(
            table_name,
            should_fail=table_name in self.failing_tables,
        )


class RecordingAnthropicModels:
    def __init__(self, *, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.list_calls = 0

    def list(self, *, limit: int) -> object:
        self.list_calls += 1
        if self.should_fail:
            raise RuntimeError("401 invalid API key sk-ant-test-secret")
        return SimpleNamespace(data=[{"id": "claude-sonnet"}])


class RecordingAnthropicClient:
    def __init__(self, *, should_fail: bool = False) -> None:
        self.models = RecordingAnthropicModels(should_fail=should_fail)


def test_cli_doctor_reports_success_and_redacts_secrets(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    supabase_client = RecordingDoctorSupabaseClient()
    anthropic_client = RecordingAnthropicClient()
    settings = SimpleNamespace(
        anthropic_api_key="sk-ant-test-secret",
        supabase_url="https://demo-project.supabase.co",
        supabase_service_role_key="sb-service-role-secret",
        supabase_storage_bucket="procurement-fixtures",
    )
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(
        cli,
        "_create_supabase_client",
        lambda _settings: supabase_client,
    )
    monkeypatch.setattr(
        cli,
        "_create_anthropic_client",
        lambda api_key: anthropic_client,
        raising=False,
    )

    result = cli.main(["doctor"])

    captured = capsys.readouterr()
    combined_output = captured.out + captured.err
    assert result == 0
    assert "Bidded demo environment doctor" in captured.out
    assert "PASS env: SUPABASE_URL is set" in captured.out
    assert "PASS supabase database" in captured.out
    assert "PASS supabase storage" in captured.out
    assert "PASS anthropic" in captured.out
    assert "sk-ant-test-secret" not in combined_output
    assert "sb-service-role-secret" not in combined_output
    assert "https://demo-project.supabase.co" not in combined_output
    assert supabase_client.table_names == [
        "companies",
        "tenders",
        "documents",
        "document_chunks",
        "evidence_items",
        "agent_runs",
        "agent_outputs",
        "bid_decisions",
    ]
    assert supabase_client.storage.bucket_names == ["procurement-fixtures"]
    assert supabase_client.storage.bucket.downloads
    assert supabase_client.storage.bucket.removals
    assert anthropic_client.models.list_calls == 1


def test_cli_doctor_reports_missing_environment_without_external_clients(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = SimpleNamespace(
        anthropic_api_key=None,
        supabase_url=None,
        supabase_service_role_key="",
        supabase_storage_bucket="",
    )
    monkeypatch.setattr(cli, "load_settings", lambda: settings)

    def fail_supabase_client(_settings: object) -> object:
        raise AssertionError("Supabase client should not be created")

    def fail_anthropic_client(_api_key: str) -> object:
        raise AssertionError("Anthropic client should not be created")

    monkeypatch.setattr(cli, "_create_supabase_client", fail_supabase_client)
    monkeypatch.setattr(cli, "_create_anthropic_client", fail_anthropic_client)

    result = cli.main(["doctor"])

    captured = capsys.readouterr()
    assert result == 1
    assert "FAIL env: SUPABASE_URL is missing" in captured.out
    assert "FAIL env: SUPABASE_SERVICE_ROLE_KEY is missing" in captured.out
    assert "FAIL env: SUPABASE_STORAGE_BUCKET is missing" in captured.out
    assert "SKIP supabase database: Supabase credentials are missing" in captured.out
    assert "SKIP supabase storage: SUPABASE_STORAGE_BUCKET is missing" in captured.out
    assert "SKIP anthropic" in captured.out


def test_cli_doctor_reports_missing_demo_table(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    supabase_client = RecordingDoctorSupabaseClient(failing_tables={"documents"})
    settings = SimpleNamespace(
        anthropic_api_key=None,
        supabase_url="https://demo-project.supabase.co",
        supabase_service_role_key="sb-service-role-secret",
        supabase_storage_bucket="procurement-fixtures",
    )
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(
        cli,
        "_create_supabase_client",
        lambda _settings: supabase_client,
    )

    result = cli.main(["doctor"])

    captured = capsys.readouterr()
    combined_output = captured.out + captured.err
    assert result == 1
    assert "FAIL supabase database" in captured.out
    assert "documents" in captured.out
    assert "PASS supabase storage" in captured.out
    assert "sb-service-role-secret" not in combined_output


def test_cli_doctor_reports_missing_storage_bucket(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    supabase_client = RecordingDoctorSupabaseClient(fail_storage_upload=True)
    settings = SimpleNamespace(
        anthropic_api_key=None,
        supabase_url="https://demo-project.supabase.co",
        supabase_service_role_key="sb-service-role-secret",
        supabase_storage_bucket="procurement-fixtures",
    )
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(
        cli,
        "_create_supabase_client",
        lambda _settings: supabase_client,
    )

    result = cli.main(["doctor"])

    captured = capsys.readouterr()
    combined_output = captured.out + captured.err
    assert result == 1
    assert "PASS supabase database" in captured.out
    assert "FAIL supabase storage" in captured.out
    assert "bucket not found" in captured.out
    assert "sb-service-role-secret" not in combined_output


def test_cli_doctor_reports_anthropic_failure_as_live_llm_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    supabase_client = RecordingDoctorSupabaseClient()
    anthropic_client = RecordingAnthropicClient(should_fail=True)
    settings = SimpleNamespace(
        anthropic_api_key="sk-ant-test-secret",
        supabase_url="https://demo-project.supabase.co",
        supabase_service_role_key="sb-service-role-secret",
        supabase_storage_bucket="procurement-fixtures",
    )
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(
        cli,
        "_create_supabase_client",
        lambda _settings: supabase_client,
    )
    monkeypatch.setattr(
        cli,
        "_create_anthropic_client",
        lambda _api_key: anthropic_client,
    )

    result = cli.main(["doctor"])

    captured = capsys.readouterr()
    combined_output = captured.out + captured.err
    assert result == 1
    assert "FAIL anthropic: live-LLM unavailable" in captured.out
    assert "invalid API key" in captured.out
    assert "sk-ant-test-secret" not in combined_output
