from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

DoctorStatus = Literal["pass", "fail", "skip"]
SupabaseClientFactory = Callable[[Any], Any]
AnthropicClientFactory = Callable[[str], Any]

EXPECTED_DEMO_TABLES = (
    "companies",
    "tenders",
    "documents",
    "document_chunks",
    "evidence_items",
    "agent_runs",
    "agent_outputs",
    "bid_decisions",
)
REQUIRED_DEMO_ENVIRONMENT = (
    ("SUPABASE_URL", "supabase_url"),
    ("SUPABASE_SERVICE_ROLE_KEY", "supabase_service_role_key"),
    ("SUPABASE_STORAGE_BUCKET", "supabase_storage_bucket"),
)
STORAGE_PROBE_PATH = "demo/doctor/probe.txt"
STORAGE_PROBE_BYTES = b"bidded demo doctor probe\n"


class SupabaseDoctorQuery(Protocol):
    def select(self, columns: str) -> SupabaseDoctorQuery: ...

    def limit(self, row_limit: int) -> SupabaseDoctorQuery: ...

    def execute(self) -> Any: ...


class SupabaseDoctorStorageBucket(Protocol):
    def upload(
        self,
        path: str,
        file: bytes,
        *,
        file_options: dict[str, str] | None = None,
    ) -> Any: ...

    def download(self, path: str) -> Any: ...

    def remove(self, paths: list[str]) -> Any: ...


class SupabaseDoctorStorage(Protocol):
    def from_(self, bucket_name: str) -> SupabaseDoctorStorageBucket: ...


class SupabaseDoctorClient(Protocol):
    storage: SupabaseDoctorStorage

    def table(self, table_name: str) -> SupabaseDoctorQuery: ...


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    status: DoctorStatus
    message: str


@dataclass(frozen=True)
class DemoEnvironmentDoctorResult:
    checks: tuple[DoctorCheck, ...]

    @property
    def passed(self) -> bool:
        return all(check.status != "fail" for check in self.checks)


def run_demo_environment_doctor(
    settings: Any,
    *,
    supabase_client_factory: SupabaseClientFactory,
    anthropic_client_factory: AnthropicClientFactory,
    check_anthropic: bool = False,
) -> DemoEnvironmentDoctorResult:
    """Check local demo prerequisites without exposing configured secret values."""

    checks: list[DoctorCheck] = []
    missing_environment: set[str] = set()
    for env_name, setting_name in REQUIRED_DEMO_ENVIRONMENT:
        if _has_setting(settings, setting_name):
            checks.append(DoctorCheck("env", "pass", f"{env_name} is set"))
        else:
            missing_environment.add(env_name)
            checks.append(DoctorCheck("env", "fail", f"{env_name} is missing"))

    client: SupabaseDoctorClient | None = None
    if {"SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"}.intersection(missing_environment):
        checks.append(
            DoctorCheck(
                "supabase database",
                "skip",
                "Supabase credentials are missing",
            )
        )
    else:
        try:
            client = supabase_client_factory(settings)
        except Exception as exc:
            checks.append(
                DoctorCheck(
                    "supabase database",
                    "fail",
                    f"Supabase client unavailable: {_redact(str(exc), settings)}",
                )
            )
        else:
            checks.append(_check_supabase_tables(client))

    if "SUPABASE_STORAGE_BUCKET" in missing_environment:
        checks.append(
            DoctorCheck(
                "supabase storage",
                "skip",
                "SUPABASE_STORAGE_BUCKET is missing",
            )
        )
    elif client is None:
        checks.append(
            DoctorCheck(
                "supabase storage",
                "skip",
                "Supabase client is unavailable",
            )
        )
    else:
        checks.append(_check_storage_bucket(client, settings))

    checks.append(
        _check_anthropic_connectivity(
            settings,
            anthropic_client_factory=anthropic_client_factory,
            required=check_anthropic,
        )
    )

    return DemoEnvironmentDoctorResult(tuple(checks))


def _check_supabase_tables(client: SupabaseDoctorClient) -> DoctorCheck:
    missing_or_unreadable: list[str] = []
    for table_name in EXPECTED_DEMO_TABLES:
        try:
            client.table(table_name).select("id").limit(1).execute()
        except Exception:
            missing_or_unreadable.append(table_name)

    if missing_or_unreadable:
        return DoctorCheck(
            "supabase database",
            "fail",
            f"Missing or unreadable demo tables: {', '.join(missing_or_unreadable)}",
        )
    return DoctorCheck(
        "supabase database",
        "pass",
        "all expected demo tables are reachable",
    )


def _check_storage_bucket(client: SupabaseDoctorClient, settings: Any) -> DoctorCheck:
    bucket_name = str(settings.supabase_storage_bucket)
    bucket: SupabaseDoctorStorageBucket | None = None
    uploaded = False
    try:
        bucket = client.storage.from_(bucket_name)
        bucket.upload(
            STORAGE_PROBE_PATH,
            STORAGE_PROBE_BYTES,
            file_options={"content-type": "text/plain", "upsert": "true"},
        )
        uploaded = True
        downloaded = bucket.download(STORAGE_PROBE_PATH)
        if isinstance(downloaded, bytes) and downloaded != STORAGE_PROBE_BYTES:
            return DoctorCheck(
                "supabase storage",
                "fail",
                "storage read probe returned unexpected content",
            )
    except Exception as exc:
        return DoctorCheck(
            "supabase storage",
            "fail",
            f"Storage bucket probe failed: {_redact(str(exc), settings)}",
        )
    finally:
        if uploaded and bucket is not None:
            try:
                bucket.remove([STORAGE_PROBE_PATH])
            except Exception:
                pass

    return DoctorCheck(
        "supabase storage",
        "pass",
        "bucket accepted write, read, and cleanup probe",
    )


def _check_anthropic_connectivity(
    settings: Any,
    *,
    anthropic_client_factory: AnthropicClientFactory,
    required: bool,
) -> DoctorCheck:
    api_key = _setting_text(settings, "anthropic_api_key")
    should_check = required or bool(api_key)
    if not should_check:
        return DoctorCheck(
            "anthropic",
            "skip",
            "ANTHROPIC_API_KEY is not set; live LLM check was not requested",
        )
    if not api_key:
        return DoctorCheck(
            "anthropic",
            "fail",
            "live-LLM unavailable: ANTHROPIC_API_KEY is missing",
        )

    try:
        client = anthropic_client_factory(api_key)
        client.models.list(limit=1)
    except Exception as exc:
        return DoctorCheck(
            "anthropic",
            "fail",
            f"live-LLM unavailable: {_redact(str(exc), settings)}",
        )

    return DoctorCheck("anthropic", "pass", "live LLM connectivity is available")


def _has_setting(settings: Any, setting_name: str) -> bool:
    return bool(_setting_text(settings, setting_name))


def _setting_text(settings: Any, setting_name: str) -> str:
    value = getattr(settings, setting_name, None)
    if value is None:
        return ""
    return str(value).strip()


def _redact(value: str, settings: Any) -> str:
    redacted = value
    for setting_name in (
        "anthropic_api_key",
        "supabase_service_role_key",
        "supabase_url",
        "openai_api_key",
    ):
        setting_value = _setting_text(settings, setting_name)
        if setting_value:
            redacted = redacted.replace(setting_value, "<redacted>")
    return redacted


__all__ = [
    "DemoEnvironmentDoctorResult",
    "DoctorCheck",
    "EXPECTED_DEMO_TABLES",
    "REQUIRED_DEMO_ENVIRONMENT",
    "run_demo_environment_doctor",
]
