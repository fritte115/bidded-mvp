from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from bidded.orchestration.pending_run import DEMO_TENANT_KEY
from bidded.orchestration.state import AgentRunStatus


class RunControlError(RuntimeError):
    """Raised when an operator run-control action cannot be completed."""


class SupabaseRunControlQuery(Protocol):
    def select(self, columns: str) -> SupabaseRunControlQuery: ...

    def eq(self, column: str, value: object) -> SupabaseRunControlQuery: ...

    def limit(self, row_limit: int) -> SupabaseRunControlQuery: ...

    def insert(
        self,
        payload: dict[str, Any] | list[dict[str, Any]],
    ) -> SupabaseRunControlQuery: ...

    def update(self, payload: dict[str, Any]) -> SupabaseRunControlQuery: ...

    def execute(self) -> Any: ...


class SupabaseRunControlClient(Protocol):
    def table(self, table_name: str) -> SupabaseRunControlQuery: ...


@dataclass(frozen=True)
class DemoTraceEntry:
    step: str
    status: str
    started_at: str | None
    completed_at: str | None
    duration_ms: int | None
    error_code: str | None = None


@dataclass(frozen=True)
class RunStatusSnapshot:
    run_id: UUID
    status: AgentRunStatus
    created_at: str | None
    started_at: str | None
    completed_at: str | None
    error_details: dict[str, Any] | None
    agent_output_count: int
    decision_present: bool
    last_recorded_step: str | None
    demo_trace: tuple[DemoTraceEntry, ...] = ()


@dataclass(frozen=True)
class RetryRunResult:
    source_run_id: UUID
    new_run_id: UUID
    source_status: AgentRunStatus


@dataclass(frozen=True)
class StaleResetResult:
    reset_count: int
    reset_run_ids: list[UUID]
    skipped_count: int


NowFactory = Callable[[], datetime]


def get_run_status(
    client: SupabaseRunControlClient,
    *,
    run_id: UUID | str,
    tenant_key: str = DEMO_TENANT_KEY,
) -> RunStatusSnapshot:
    """Return an operator-facing audit snapshot for one agent run."""

    normalized_run_id = _normalize_uuid(run_id, "run_id")
    run_row = _require_run_row(
        client,
        run_id=normalized_run_id,
        tenant_key=tenant_key,
    )
    output_rows = _response_rows(
        client.table("agent_outputs")
        .select("id")
        .eq("tenant_key", tenant_key)
        .eq("agent_run_id", str(normalized_run_id))
        .execute()
    )
    decision_rows = _response_rows(
        client.table("bid_decisions")
        .select("id")
        .eq("tenant_key", tenant_key)
        .eq("agent_run_id", str(normalized_run_id))
        .limit(1)
        .execute()
    )
    error_details = run_row.get("error_details")
    metadata = _mapping(run_row.get("metadata"))
    demo_trace = _demo_trace_entries(metadata)

    return RunStatusSnapshot(
        run_id=normalized_run_id,
        status=AgentRunStatus(str(run_row.get("status"))),
        created_at=_optional_string(run_row.get("created_at")),
        started_at=_optional_string(run_row.get("started_at")),
        completed_at=_optional_string(run_row.get("completed_at")),
        error_details=(
            dict(error_details) if isinstance(error_details, Mapping) else None
        ),
        agent_output_count=len(output_rows),
        decision_present=bool(decision_rows),
        last_recorded_step=_last_recorded_step(metadata, demo_trace),
        demo_trace=demo_trace,
    )


def retry_agent_run(
    client: SupabaseRunControlClient,
    *,
    run_id: UUID | str,
    reason: str,
    tenant_key: str = DEMO_TENANT_KEY,
    force: bool = False,
    now_factory: NowFactory | None = None,
) -> RetryRunResult:
    """Create a new pending retry run linked to a failed source run."""

    normalized_run_id = _normalize_uuid(run_id, "run_id")
    source_row = _require_run_row(
        client,
        run_id=normalized_run_id,
        tenant_key=tenant_key,
    )
    source_status = AgentRunStatus(str(source_row.get("status")))
    if source_status not in {
        AgentRunStatus.FAILED,
        AgentRunStatus.NEEDS_HUMAN_REVIEW,
    }:
        if source_status is AgentRunStatus.SUCCEEDED and not force:
            raise RunControlError(
                "Succeeded agent runs require force=True before retry."
            )
        if source_status is not AgentRunStatus.SUCCEEDED:
            raise RunControlError(
                "Only failed or needs_human_review agent runs can be retried."
            )

    timestamp = _timestamp(now_factory or _utc_now)
    run_config = dict(_mapping(source_row.get("run_config")))
    source_metadata = _mapping(source_row.get("metadata"))
    payload: dict[str, Any] = {
        "tenant_key": tenant_key,
        "tender_id": str(_normalize_uuid(source_row.get("tender_id"), "tender_id")),
        "company_id": str(_normalize_uuid(source_row.get("company_id"), "company_id")),
        "status": AgentRunStatus.PENDING.value,
        "run_config": run_config,
        "metadata": {
            "created_via": "bidded_operator_retry",
            "document_ids": list(_sequence(source_metadata.get("document_ids"))),
            "retry": {
                "source_run_id": str(normalized_run_id),
                "source_status": source_status.value,
                "requested_at": timestamp,
                "reason": reason,
                "force": force,
            },
        },
    }
    response = client.table("agent_runs").insert(payload).execute()
    new_run_id = _first_returned_id(response, "agent_runs")
    return RetryRunResult(
        source_run_id=normalized_run_id,
        new_run_id=new_run_id,
        source_status=source_status,
    )


def reset_stale_runs(
    client: SupabaseRunControlClient,
    *,
    max_age_minutes: int,
    reason: str,
    tenant_key: str = DEMO_TENANT_KEY,
    now_factory: NowFactory | None = None,
) -> StaleResetResult:
    """Fail running agent runs that have exceeded the configured age."""

    if max_age_minutes < 0:
        raise RunControlError("max_age_minutes must be non-negative.")
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise RunControlError("An operator reason is required for stale reset.")

    now = (now_factory or _utc_now)().astimezone(UTC)
    timestamp = now.isoformat()
    running_rows = _response_rows(
        client.table("agent_runs")
        .select(_AGENT_RUN_SELECT_COLUMNS)
        .eq("tenant_key", tenant_key)
        .eq("status", AgentRunStatus.RUNNING.value)
        .execute()
    )
    reset_run_ids: list[UUID] = []
    skipped_count = 0
    for row in running_rows:
        started_at = _parse_timestamp(row.get("started_at"))
        if started_at is None:
            skipped_count += 1
            continue
        stale_age_minutes = int((now - started_at).total_seconds() // 60)
        if stale_age_minutes <= max_age_minutes:
            skipped_count += 1
            continue

        run_id = _normalize_uuid(row.get("id"), "agent_runs.id")
        metadata = _operator_reset_metadata(
            _mapping(row.get("metadata")),
            reason=normalized_reason,
            timestamp=timestamp,
            max_age_minutes=max_age_minutes,
            stale_age_minutes=stale_age_minutes,
        )
        error_details = {
            "code": "operator_stale_reset",
            "message": normalized_reason,
            "source": "operator",
            "stale_age_minutes": stale_age_minutes,
        }
        updated_rows = _response_rows(
            client.table("agent_runs")
            .update(
                {
                    "status": AgentRunStatus.FAILED.value,
                    "completed_at": timestamp,
                    "metadata": metadata,
                    "error_details": error_details,
                }
            )
            .eq("tenant_key", tenant_key)
            .eq("id", str(run_id))
            .eq("status", AgentRunStatus.RUNNING.value)
            .execute()
        )
        if not updated_rows:
            raise RunControlError(
                f"Stale agent run could not be reset because it changed: {run_id}"
            )
        reset_run_ids.append(run_id)

    return StaleResetResult(
        reset_count=len(reset_run_ids),
        reset_run_ids=reset_run_ids,
        skipped_count=skipped_count,
    )


def _require_run_row(
    client: SupabaseRunControlClient,
    *,
    run_id: UUID,
    tenant_key: str,
) -> dict[str, Any]:
    rows = _response_rows(
        client.table("agent_runs")
        .select(_AGENT_RUN_SELECT_COLUMNS)
        .eq("tenant_key", tenant_key)
        .eq("id", str(run_id))
        .execute()
    )
    if not rows:
        raise RunControlError(f"Agent run does not exist: {run_id}")
    return dict(rows[0])


def _last_recorded_step(
    metadata: Mapping[str, Any],
    demo_trace: Sequence[DemoTraceEntry],
) -> str | None:
    if demo_trace:
        return demo_trace[-1].step
    worker = _mapping(metadata.get("worker"))
    visited_nodes = _sequence(worker.get("visited_nodes"))
    if visited_nodes:
        return str(visited_nodes[-1])
    last_status = worker.get("last_status")
    return str(last_status) if last_status is not None else None


def _demo_trace_entries(metadata: Mapping[str, Any]) -> tuple[DemoTraceEntry, ...]:
    entries: list[DemoTraceEntry] = []
    for raw_entry in _sequence(metadata.get("demo_trace")):
        if not isinstance(raw_entry, Mapping):
            continue
        step = _safe_trace_text(raw_entry.get("step"))
        status = _safe_trace_status(raw_entry.get("status"))
        if not step or status is None:
            continue
        entries.append(
            DemoTraceEntry(
                step=step,
                status=status,
                started_at=_safe_trace_timestamp(raw_entry.get("started_at")),
                completed_at=_safe_trace_timestamp(raw_entry.get("completed_at")),
                duration_ms=_safe_non_negative_int(raw_entry.get("duration_ms")),
                error_code=_short_error_code(raw_entry.get("error_code")),
            )
        )
    return tuple(entries)


def _safe_trace_text(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    safe = "".join(
        char if char.isalnum() or char in {"_", "-"} else "_" for char in text.lower()
    )
    return safe[:64] or None


def _safe_trace_status(value: object) -> str | None:
    text = _safe_trace_text(value)
    if text in {"running", "completed", "failed"}:
        return text
    return None


def _safe_trace_timestamp(value: object) -> str | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


def _safe_non_negative_int(value: object) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed < 0:
        return None
    return parsed


def _short_error_code(value: object) -> str | None:
    if value is None:
        return None
    return _safe_trace_text(value)


def _operator_reset_metadata(
    metadata: Mapping[str, Any],
    *,
    reason: str,
    timestamp: str,
    max_age_minutes: int,
    stale_age_minutes: int,
) -> dict[str, Any]:
    merged = dict(metadata)
    merged["operator_control"] = {
        "action": "reset_stale",
        "reason": reason,
        "requested_at": timestamp,
        "max_age_minutes": max_age_minutes,
        "stale_age_minutes": stale_age_minutes,
    }
    return merged


def _response_rows(response: Any) -> list[Mapping[str, Any]]:
    data = getattr(response, "data", None)
    if not isinstance(data, list):
        raise RunControlError("Supabase query did not return a row list.")
    return [row for row in data if isinstance(row, Mapping)]


def _normalize_uuid(value: Any, field_name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise RunControlError(f"{field_name} must be a UUID.") from exc


def _first_returned_id(response: Any, table_name: str) -> UUID:
    rows = _response_rows(response)
    if rows:
        row_id = rows[0].get("id")
        if row_id:
            return _normalize_uuid(row_id, f"{table_name}.id")
    raise RunControlError(f"Supabase {table_name} insert did not return a row id.")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, str) else ()


def _optional_string(value: Any) -> str | None:
    return str(value) if value is not None else None


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise RunControlError(f"Invalid timestamp: {value}") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _timestamp(now: NowFactory) -> str:
    return now().astimezone(UTC).isoformat()


def _utc_now() -> datetime:
    return datetime.now(UTC)


_AGENT_RUN_SELECT_COLUMNS = (
    "id,created_at,tenant_key,tender_id,company_id,status,run_config,"
    "error_details,started_at,completed_at,metadata"
)


__all__ = [
    "DemoTraceEntry",
    "RetryRunResult",
    "RunControlError",
    "RunStatusSnapshot",
    "StaleResetResult",
    "SupabaseRunControlClient",
    "get_run_status",
    "reset_stale_runs",
    "retry_agent_run",
]
