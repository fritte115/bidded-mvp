from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from bidded.db.schema_compat import (
    is_missing_requirement_type_column,
    select_without_requirement_type,
)
from bidded.evidence.company_profile import upsert_company_profile_evidence
from bidded.orchestration.graph import (
    GraphNodeHandlers,
    GraphRunResult,
    OnStepCallback,
    run_bidded_graph_shell,
)
from bidded.orchestration.judge import persist_final_decision
from bidded.orchestration.pending_run import DEMO_TENANT_KEY
from bidded.orchestration.state import (
    AgentOutputState,
    AgentRunStatus,
    BidRunState,
    DocumentChunkState,
    EvidenceItemState,
    EvidenceSourceType,
    RuntimeErrorState,
    Verdict,
)
from bidded.requirements import RequirementType
from bidded.versioning import normalize_version_metadata, version_metadata_dict

DEFAULT_WORKER_NAME = "bidded_cli_worker"
_REQUIREMENT_TYPE_BY_LEGACY_CATEGORY: dict[str, RequirementType] = {
    "mandatory_requirement": RequirementType.SHALL_REQUIREMENT,
    "shall_requirement": RequirementType.SHALL_REQUIREMENT,
    "qualification_criterion": RequirementType.QUALIFICATION_REQUIREMENT,
    "qualification_requirement": RequirementType.QUALIFICATION_REQUIREMENT,
    "exclusion_ground": RequirementType.EXCLUSION_GROUND,
    "financial_standing": RequirementType.FINANCIAL_STANDING,
    "legal_or_regulatory_reference": RequirementType.LEGAL_OR_REGULATORY_REFERENCE,
    "quality_management": RequirementType.QUALITY_MANAGEMENT,
    "submission_document": RequirementType.SUBMISSION_DOCUMENT,
    "contract_obligation": RequirementType.CONTRACT_OBLIGATION,
}


class WorkerLifecycleError(RuntimeError):
    """Raised when a worker run cannot be selected or persisted."""


class SupabaseWorkerQuery(Protocol):
    def select(self, columns: str) -> SupabaseWorkerQuery: ...

    def eq(self, column: str, value: object) -> SupabaseWorkerQuery: ...

    def order(self, column: str, *, desc: bool = False) -> SupabaseWorkerQuery: ...

    def limit(self, row_limit: int) -> SupabaseWorkerQuery: ...

    def update(self, payload: dict[str, Any]) -> SupabaseWorkerQuery: ...

    def insert(
        self,
        payload: dict[str, Any] | list[dict[str, Any]],
    ) -> SupabaseWorkerQuery: ...

    def execute(self) -> Any: ...


class SupabaseWorkerClient(Protocol):
    def table(self, table_name: str) -> SupabaseWorkerQuery: ...


GraphRunner = Callable[..., GraphRunResult]
LogSink = Callable[[str], None]
NowFactory = Callable[[], datetime]


@dataclass(frozen=True)
class WorkerRunResult:
    run_id: UUID | None
    terminal_status: AgentRunStatus | None
    visited_nodes: tuple[str, ...]
    agent_output_count: int
    decision_verdict: Verdict | None
    message: str


@dataclass(frozen=True)
class _TraceStepTiming:
    step: str
    started_at: str


def run_worker_once(
    client: SupabaseWorkerClient,
    *,
    run_id: UUID | str | None = None,
    company_id: UUID | str | None = None,
    tenant_key: str = DEMO_TENANT_KEY,
    graph_runner: GraphRunner | None = None,
    graph_handlers: GraphNodeHandlers | None = None,
    now_factory: NowFactory | None = None,
    log: LogSink | None = None,
) -> WorkerRunResult:
    """Run one pending Supabase agent_run through the deterministic graph."""

    now = now_factory or _utc_now
    if graph_handlers is not None:

        def _runner(
            state: BidRunState,
            *,
            on_step: OnStepCallback | None = None,
        ) -> GraphRunResult:
            return run_bidded_graph_shell(
                state,
                handlers=graph_handlers,
                on_step=on_step,
            )

        graph_runner = _runner
    elif graph_runner is None:
        graph_runner = run_bidded_graph_shell

    selected_run = _select_worker_run(
        client,
        run_id=run_id,
        company_id=company_id,
        tenant_key=tenant_key,
    )
    if selected_run is None:
        message = "No pending demo agent run found."
        _log(log, message)
        return WorkerRunResult(
            run_id=None,
            terminal_status=None,
            visited_nodes=(),
            agent_output_count=0,
            decision_verdict=None,
            message=message,
        )

    normalized_run_id = _normalize_uuid(selected_run.get("id"), "agent_runs.id")
    status = AgentRunStatus(str(selected_run.get("status")))
    if status is not AgentRunStatus.PENDING:
        message = "No pending demo agent run found."
        _log(log, message)
        return WorkerRunResult(
            run_id=None,
            terminal_status=None,
            visited_nodes=(),
            agent_output_count=0,
            decision_verdict=None,
            message=message,
        )

    metadata = _mapping(selected_run.get("metadata"))
    demo_trace = _DemoTrace(metadata, now)
    claim_step = demo_trace.start("claim_run")
    started_at = claim_step.started_at
    demo_trace.complete(claim_step)
    claimed_run = _claim_worker_run(
        client,
        selected_run=selected_run,
        run_id=normalized_run_id,
        tenant_key=tenant_key,
        timestamp=started_at,
        metadata=metadata,
        demo_trace=demo_trace.entries,
        current_step="preflight",
    )
    if claimed_run is None:
        message = "No pending demo agent run found."
        _log(log, message)
        return WorkerRunResult(
            run_id=None,
            terminal_status=None,
            visited_nodes=(),
            agent_output_count=0,
            decision_verdict=None,
            message=message,
        )
    selected_run = claimed_run
    metadata = _mapping(selected_run.get("metadata"))
    _log(log, f"Starting agent run {normalized_run_id}.")

    active_step: _TraceStepTiming | None = None
    try:
        last_persisted_step: dict[str, str] = {"value": "preflight"}
        persisted_metadata: dict[str, Any] = {"value": dict(metadata)}

        def _on_step(current_state: BidRunState) -> None:
            if current_state.status is not AgentRunStatus.RUNNING:
                return
            new_step = _current_step_value(current_state)
            if not new_step or new_step == last_persisted_step["value"]:
                return
            try:
                persisted_metadata["value"] = _update_run_status(
                    client,
                    run_id=normalized_run_id,
                    tenant_key=tenant_key,
                    status=AgentRunStatus.RUNNING,
                    timestamp=_timestamp(now),
                    metadata=persisted_metadata["value"],
                    error_details=None,
                    current_step=new_step,
                )
                last_persisted_step["value"] = new_step
                _log(log, f"Agent run {normalized_run_id} reached {new_step}.")
            except Exception as exc:  # noqa: BLE001 - best-effort telemetry
                _log(
                    log,
                    f"Failed to persist stage {new_step} for "
                    f"run {normalized_run_id}: {exc}",
                )

        active_step = demo_trace.start("load_run_context")
        run_company_id = _normalize_uuid(
            selected_run.get("company_id"),
            "agent_runs.company_id",
        )
        _refresh_company_profile_evidence_for_run(
            client,
            company_id=run_company_id,
            tenant_key=tenant_key,
            log=log,
        )
        state = build_bid_run_state_from_supabase(
            client,
            run_row=selected_run,
            tenant_key=tenant_key,
        )
        demo_trace.complete(active_step)
        active_step = None
        active_step = demo_trace.start("run_graph")
        try:
            graph_result = graph_runner(state, on_step=_on_step)
        except TypeError:
            graph_result = graph_runner(state)
        metadata = persisted_metadata["value"]
        terminal_state = graph_result.state
        visited_nodes = tuple(node.value for node in graph_result.visited_nodes)

        if terminal_state.status is AgentRunStatus.FAILED:
            completed_at = _timestamp(now)
            error_details = _graph_error_details(terminal_state.last_error)
            demo_trace.fail(active_step, error_code=error_details["code"])
            active_step = None
            complete_step = demo_trace.start("complete_run")
            demo_trace.complete(complete_step)
            _update_run_status(
                client,
                run_id=normalized_run_id,
                tenant_key=tenant_key,
                status=AgentRunStatus.FAILED,
                timestamp=completed_at,
                metadata=_terminal_metadata(
                    metadata,
                    terminal_state=terminal_state,
                    visited_nodes=visited_nodes,
                    timestamp=completed_at,
                    demo_trace=demo_trace.entries,
                ),
                error_details=error_details,
            )
            message = (
                f"Agent run {normalized_run_id} failed: {error_details['message']}"
            )
            _log(log, message)
            return WorkerRunResult(
                run_id=normalized_run_id,
                terminal_status=AgentRunStatus.FAILED,
                visited_nodes=visited_nodes,
                agent_output_count=len(terminal_state.agent_outputs),
                decision_verdict=None,
                message=message,
            )

        demo_trace.complete(active_step)
        active_step = None
        active_step = demo_trace.start("persist_agent_outputs")
        output_count = persist_agent_outputs(
            client,
            terminal_state.agent_outputs,
            run_id=normalized_run_id,
            tenant_key=tenant_key,
        )
        demo_trace.complete(active_step)
        active_step = None
        if terminal_state.final_decision is None:
            raise WorkerLifecycleError("Graph completed without a final decision.")
        active_step = demo_trace.start("persist_final_decision")
        persist_final_decision(client, terminal_state, tenant_key=tenant_key)
        demo_trace.complete(active_step)
        active_step = None

        completed_at = _timestamp(now)
        active_step = demo_trace.start("complete_run")
        demo_trace.complete(active_step)
        active_step = None
        metadata = _update_run_status(
            client,
            run_id=normalized_run_id,
            tenant_key=tenant_key,
            status=terminal_state.status,
            timestamp=completed_at,
            metadata=_terminal_metadata(
                metadata,
                terminal_state=terminal_state,
                visited_nodes=visited_nodes,
                timestamp=completed_at,
                demo_trace=demo_trace.entries,
            ),
            error_details=None,
        )
        verdict = terminal_state.final_decision.verdict
        message = (
            f"Agent run {normalized_run_id} finished with "
            f"{terminal_state.status.value}; verdict: {verdict.value}."
        )
        _log(log, message)
        return WorkerRunResult(
            run_id=normalized_run_id,
            terminal_status=terminal_state.status,
            visited_nodes=visited_nodes,
            agent_output_count=output_count,
            decision_verdict=verdict,
            message=message,
        )
    except Exception as exc:
        completed_at = _timestamp(now)
        if active_step is not None:
            demo_trace.fail(active_step, error_code="worker_error")
            active_step = None
        else:
            failure_step = demo_trace.start("worker_error")
            demo_trace.fail(failure_step, error_code="worker_error")
        complete_step = demo_trace.start("complete_run")
        demo_trace.complete(complete_step)
        error_details = {
            "code": "worker_error",
            "message": str(exc),
            "source": DEFAULT_WORKER_NAME,
        }
        _update_run_status(
            client,
            run_id=normalized_run_id,
            tenant_key=tenant_key,
            status=AgentRunStatus.FAILED,
            timestamp=completed_at,
            metadata=_worker_metadata(
                metadata,
                status=AgentRunStatus.FAILED,
                timestamp=completed_at,
                details={"error_code": error_details["code"]},
                demo_trace=demo_trace.entries,
            ),
            error_details=error_details,
        )
        message = f"Agent run {normalized_run_id} failed: {exc}"
        _log(log, message)
        return WorkerRunResult(
            run_id=normalized_run_id,
            terminal_status=AgentRunStatus.FAILED,
            visited_nodes=(),
            agent_output_count=0,
            decision_verdict=None,
            message=message,
        )


def _fetch_company_row_for_evidence_sync(
    client: SupabaseWorkerClient,
    *,
    company_id: UUID,
    tenant_key: str,
) -> dict[str, Any] | None:
    response = (
        client.table("companies")
        .select("*")
        .eq("tenant_key", tenant_key)
        .eq("id", str(company_id))
        .limit(1)
        .execute()
    )
    data = getattr(response, "data", None)
    if not isinstance(data, list) or not data:
        return None
    first = data[0]
    return dict(first) if isinstance(first, Mapping) else None


def _refresh_company_profile_evidence_for_run(
    client: SupabaseWorkerClient,
    *,
    company_id: UUID,
    tenant_key: str,
    log: LogSink | None,
) -> None:
    """Re-materialize ``company_profile`` evidence from the current ``companies`` row.

    ``evidence_items`` are derived from ``companies``; without a refresh, runs can
    see stale excerpts after profile edits until ``/api/company/resync-evidence``
    is called. Refreshing here keeps every agent run aligned with live data.
    """
    row = _fetch_company_row_for_evidence_sync(
        client,
        company_id=company_id,
        tenant_key=tenant_key,
    )
    if row is None:
        _log(
            log,
            f"No companies row for {company_id}; skipping company evidence refresh.",
        )
        return

    result = upsert_company_profile_evidence(
        client,
        company_id=company_id,
        company_profile=row,
    )
    if result.evidence_count > 0:
        _log(
            log,
            f"Refreshed company profile evidence ({result.evidence_count} items) for "
            f"company {company_id}.",
        )


def build_bid_run_state_from_supabase(
    client: SupabaseWorkerClient,
    *,
    run_row: Mapping[str, Any],
    tenant_key: str = DEMO_TENANT_KEY,
) -> BidRunState:
    """Load Supabase rows into the typed graph state for one agent_run."""

    run_id = _normalize_uuid(run_row.get("id"), "agent_runs.id")
    company_id = _normalize_uuid(run_row.get("company_id"), "agent_runs.company_id")
    tender_id = _normalize_uuid(run_row.get("tender_id"), "agent_runs.tender_id")
    run_config = _mapping(run_row.get("run_config"))
    metadata = _mapping(run_row.get("metadata"))

    document_rows = _fetch_tenant_rows(
        client,
        "documents",
        (
            "id,tenant_key,tender_id,company_id,document_role,parse_status,"
            "original_filename,metadata"
        ),
        tenant_key=tenant_key,
    )
    document_ids = _document_ids_from_run(
        run_config=run_config,
        metadata=metadata,
        document_rows=document_rows,
        tender_id=tender_id,
    )
    chunk_rows = _fetch_tenant_rows(
        client,
        "document_chunks",
        ("id,tenant_key,document_id,page_start,page_end,chunk_index,text,metadata"),
        tenant_key=tenant_key,
    )
    evidence_rows = _fetch_tenant_rows(
        client,
        "evidence_items",
        (
            "id,tenant_key,evidence_key,source_type,excerpt,normalized_meaning,"
            "category,requirement_type,confidence,source_metadata,document_id,"
            "chunk_id,page_start,page_end,company_id,field_path,metadata"
        ),
        tenant_key=tenant_key,
    )

    relevant_documents = [
        row
        for row in document_rows
        if _optional_uuid(row.get("id")) in set(document_ids)
    ]
    chunks = [
        _chunk_state_from_row(row)
        for row in chunk_rows
        if _optional_uuid(row.get("document_id")) in set(document_ids)
    ]
    evidence_board = [
        _evidence_state_from_row(row)
        for row in evidence_rows
        if _evidence_belongs_to_run(
            row,
            company_id=company_id,
            document_ids=document_ids,
        )
    ]

    return BidRunState(
        run_id=run_id,
        company_id=company_id,
        tender_id=tender_id,
        document_ids=document_ids,
        run_context={
            "tenant_key": tenant_key,
            "run_config": run_config,
            "metadata": metadata,
            "preparation_audit": _mapping(metadata.get("preparation_audit")),
            "document_parse_statuses": {
                str(row["id"]): str(row.get("parse_status"))
                for row in relevant_documents
                if row.get("id") is not None and row.get("parse_status") is not None
            },
            "documents": [
                {
                    "id": str(row.get("id")),
                    "parse_status": str(row.get("parse_status")),
                    "document_role": str(row.get("document_role")),
                    "original_filename": str(row.get("original_filename") or ""),
                }
                for row in relevant_documents
            ],
        },
        chunks=chunks,
        evidence_board=evidence_board,
        status=AgentRunStatus(str(run_row.get("status"))),
    )


def persist_agent_outputs(
    client: SupabaseWorkerClient,
    agent_outputs: Sequence[AgentOutputState],
    *,
    run_id: UUID,
    tenant_key: str = DEMO_TENANT_KEY,
) -> int:
    """Persist normalized graph agent outputs as immutable audit rows."""

    if not agent_outputs:
        return 0

    payload = [
        _agent_output_payload(output, run_id=run_id, tenant_key=tenant_key)
        for output in agent_outputs
    ]
    response = client.table("agent_outputs").insert(payload).execute()
    rows = _response_rows(response)
    return len(rows) if rows else len(payload)


def _select_worker_run(
    client: SupabaseWorkerClient,
    *,
    run_id: UUID | str | None,
    company_id: UUID | str | None,
    tenant_key: str,
) -> dict[str, Any] | None:
    if run_id is not None:
        normalized_run_id = _normalize_uuid(run_id, "run_id")
        rows = _response_rows(
            client.table("agent_runs")
            .select(_AGENT_RUN_SELECT_COLUMNS)
            .eq("tenant_key", tenant_key)
            .eq("id", str(normalized_run_id))
            .execute()
        )
        if not rows:
            raise WorkerLifecycleError(f"Agent run does not exist: {normalized_run_id}")
        return dict(rows[0])

    query = (
        client.table("agent_runs")
        .select(_AGENT_RUN_SELECT_COLUMNS)
        .eq("tenant_key", tenant_key)
        .eq("status", AgentRunStatus.PENDING.value)
    )
    if company_id is not None:
        query = query.eq("company_id", str(_normalize_uuid(company_id, "company_id")))
    rows = _response_rows(query.order("created_at", desc=False).limit(1).execute())
    if not rows:
        return None
    return dict(rows[0])


def _update_run_status(
    client: SupabaseWorkerClient,
    *,
    run_id: UUID,
    tenant_key: str,
    status: AgentRunStatus,
    timestamp: str,
    metadata: Mapping[str, Any],
    error_details: Mapping[str, Any] | None,
    current_step: str | None = None,
) -> dict[str, Any]:
    next_metadata = _worker_metadata(
        metadata,
        status=status,
        timestamp=timestamp,
        current_step=current_step,
    )
    payload: dict[str, Any] = {
        "status": status.value,
        "metadata": next_metadata,
        "error_details": dict(error_details) if error_details is not None else None,
    }
    if status is AgentRunStatus.RUNNING:
        payload["started_at"] = timestamp
    if status in {
        AgentRunStatus.SUCCEEDED,
        AgentRunStatus.FAILED,
        AgentRunStatus.NEEDS_HUMAN_REVIEW,
    }:
        payload["completed_at"] = timestamp

    client.table("agent_runs").update(payload).eq("tenant_key", tenant_key).eq(
        "id",
        str(run_id),
    ).execute()
    return next_metadata


def _claim_worker_run(
    client: SupabaseWorkerClient,
    *,
    selected_run: Mapping[str, Any],
    run_id: UUID,
    tenant_key: str,
    timestamp: str,
    metadata: Mapping[str, Any],
    demo_trace: Sequence[Mapping[str, Any]],
    current_step: str | None = None,
) -> dict[str, Any] | None:
    next_metadata = _worker_metadata(
        metadata,
        status=AgentRunStatus.RUNNING,
        timestamp=timestamp,
        demo_trace=demo_trace,
        current_step=current_step,
    )
    payload: dict[str, Any] = {
        "status": AgentRunStatus.RUNNING.value,
        "metadata": next_metadata,
        "error_details": None,
        "started_at": timestamp,
    }
    rows = _response_rows(
        client.table("agent_runs")
        .update(payload)
        .eq("tenant_key", tenant_key)
        .eq("id", str(run_id))
        .eq("status", AgentRunStatus.PENDING.value)
        .execute()
    )
    if not rows:
        return None
    claimed_run = {**selected_run, **dict(rows[0])}
    return claimed_run


def _terminal_metadata(
    metadata: Mapping[str, Any],
    *,
    terminal_state: BidRunState,
    visited_nodes: Sequence[str],
    timestamp: str,
    demo_trace: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    details: dict[str, Any] = {
        "visited_nodes": list(visited_nodes),
        "agent_output_count": len(terminal_state.agent_outputs),
    }
    if terminal_state.final_decision is not None:
        details["decision_verdict"] = terminal_state.final_decision.verdict.value
    return _worker_metadata(
        metadata,
        status=terminal_state.status,
        timestamp=timestamp,
        current_step=_current_step_value(terminal_state),
        details=details,
        demo_trace=demo_trace,
    )


def _worker_metadata(
    metadata: Mapping[str, Any],
    *,
    status: AgentRunStatus,
    timestamp: str,
    current_step: str | None = None,
    details: Mapping[str, Any] | None = None,
    demo_trace: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    merged = dict(metadata)
    merged["version_metadata"] = version_metadata_dict(
        normalize_version_metadata(_mapping(merged.get("version_metadata")))
    )
    if demo_trace is not None:
        merged["demo_trace"] = _sanitize_demo_trace_entries(demo_trace)
    worker = dict(_mapping(merged.get("worker")))
    if current_step is not None:
        merged["current_step"] = current_step
        worker["current_step"] = current_step
    worker.update(
        {
            "name": DEFAULT_WORKER_NAME,
            "last_status": status.value,
            "updated_at": timestamp,
        }
    )
    if details:
        worker.update(dict(details))
    merged["worker"] = worker
    return merged


def _current_step_value(state: BidRunState) -> str:
    value = state.current_step
    return value.value if hasattr(value, "value") else str(value)


class _DemoTrace:
    def __init__(self, metadata: Mapping[str, Any], now: NowFactory) -> None:
        self._now = now
        self._entries = _sanitize_demo_trace_entries(
            _sequence(metadata.get("demo_trace"))
        )

    @property
    def entries(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(entry) for entry in self._entries)

    def start(self, step: str) -> _TraceStepTiming:
        return _TraceStepTiming(step=step, started_at=_timestamp(self._now))

    def complete(self, timing: _TraceStepTiming) -> None:
        self._append(timing, status="completed", completed_at=_timestamp(self._now))

    def fail(self, timing: _TraceStepTiming, *, error_code: str) -> None:
        self._append(
            timing,
            status="failed",
            completed_at=_timestamp(self._now),
            error_code=error_code,
        )

    def _append(
        self,
        timing: _TraceStepTiming,
        *,
        status: str,
        completed_at: str,
        error_code: str | None = None,
    ) -> None:
        entry: dict[str, Any] = {
            "step": _safe_trace_text(timing.step),
            "status": status,
            "started_at": timing.started_at,
            "completed_at": completed_at,
            "duration_ms": _duration_ms(timing.started_at, completed_at),
        }
        if error_code is not None:
            entry["error_code"] = _short_error_code(error_code)
        self._entries.append(entry)


def _sanitize_demo_trace_entries(
    entries: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for raw_entry in entries:
        if not isinstance(raw_entry, Mapping):
            continue
        step = _safe_trace_text(raw_entry.get("step"))
        status = _safe_trace_status(raw_entry.get("status"))
        if not step or status is None:
            continue
        entry: dict[str, Any] = {"step": step, "status": status}
        started_at = _safe_trace_timestamp(raw_entry.get("started_at"))
        completed_at = _safe_trace_timestamp(raw_entry.get("completed_at"))
        if started_at is not None:
            entry["started_at"] = started_at
        if completed_at is not None:
            entry["completed_at"] = completed_at
        duration_ms = _safe_non_negative_int(raw_entry.get("duration_ms"))
        if duration_ms is not None:
            entry["duration_ms"] = duration_ms
        error_code = _short_error_code(raw_entry.get("error_code"))
        if error_code is not None:
            entry["error_code"] = error_code
        sanitized.append(entry)
    return sanitized


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


def _duration_ms(started_at: str, completed_at: str) -> int:
    try:
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        completed = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
    except ValueError:
        return 0
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    if completed.tzinfo is None:
        completed = completed.replace(tzinfo=UTC)
    return max(0, int((completed - started).total_seconds() * 1000))


def _graph_error_details(last_error: RuntimeErrorState | None) -> dict[str, Any]:
    if last_error is None:
        return {
            "code": "graph_failed",
            "message": "Graph ended with failed status.",
            "source": "graph",
        }
    return {
        "code": "graph_failed",
        "message": last_error.message,
        "source": last_error.source,
        "retryable": last_error.retryable,
    }


def _agent_output_payload(
    output: AgentOutputState,
    *,
    run_id: UUID,
    tenant_key: str,
) -> dict[str, Any]:
    version_metadata = version_metadata_dict(normalize_version_metadata(None))
    return {
        "tenant_key": tenant_key,
        "agent_run_id": str(run_id),
        "agent_role": output.agent_role,
        "round_name": output.round_name,
        "output_type": output.output_type,
        "validated_payload": output.payload,
        "model_metadata": version_metadata,
        "validation_errors": [
            error.model_dump(mode="json") for error in output.validation_errors
        ],
        "metadata": {
            "source": DEFAULT_WORKER_NAME,
            "audit_artifact": "validated_payload",
            "version_metadata": version_metadata,
            "evidence_refs": [
                evidence_ref.model_dump(mode="json")
                for evidence_ref in output.evidence_refs
            ],
        },
    }


def _fetch_tenant_rows(
    client: SupabaseWorkerClient,
    table_name: str,
    columns: str,
    *,
    tenant_key: str,
) -> list[dict[str, Any]]:
    try:
        rows = _response_rows(
            client.table(table_name)
            .select(columns)
            .eq("tenant_key", tenant_key)
            .execute()
        )
        return [dict(row) for row in rows]
    except Exception as exc:
        if table_name != "evidence_items" or not is_missing_requirement_type_column(
            exc
        ):
            raise

    rows = _response_rows(
        client.table(table_name)
        .select(select_without_requirement_type(columns))
        .eq("tenant_key", tenant_key)
        .execute()
    )
    return [
        dict(row, requirement_type=_infer_legacy_requirement_type(row)) for row in rows
    ]


def _document_ids_from_run(
    *,
    run_config: Mapping[str, Any],
    metadata: Mapping[str, Any],
    document_rows: Sequence[Mapping[str, Any]],
    tender_id: UUID,
) -> list[UUID]:
    raw_document_ids = _sequence(run_config.get("document_ids")) or _sequence(
        metadata.get("document_ids")
    )
    if raw_document_ids:
        return [_normalize_uuid(value, "document_ids") for value in raw_document_ids]

    return [
        _normalize_uuid(row.get("id"), "documents.id")
        for row in document_rows
        if str(row.get("tender_id")) == str(tender_id)
        and row.get("document_role") == EvidenceSourceType.TENDER_DOCUMENT.value
    ]


def _chunk_state_from_row(row: Mapping[str, Any]) -> DocumentChunkState:
    return DocumentChunkState(
        chunk_id=_normalize_uuid(row.get("id"), "document_chunks.id"),
        document_id=_normalize_uuid(
            row.get("document_id"),
            "document_chunks.document_id",
        ),
        chunk_index=_int_value(row.get("chunk_index"), "chunk_index"),
        page_start=_int_value(row.get("page_start"), "page_start"),
        page_end=_int_value(row.get("page_end"), "page_end"),
        text=str(row.get("text") or ""),
        metadata=dict(_mapping(row.get("metadata"))),
    )


def _evidence_state_from_row(row: Mapping[str, Any]) -> EvidenceItemState:
    source_type = EvidenceSourceType(str(row.get("source_type")))
    return EvidenceItemState(
        evidence_id=_optional_uuid(row.get("id")),
        evidence_key=str(row.get("evidence_key") or ""),
        source_type=source_type,
        excerpt=str(row.get("excerpt") or ""),
        normalized_meaning=str(row.get("normalized_meaning") or ""),
        category=str(row.get("category") or ""),
        requirement_type=row.get("requirement_type")
        or _infer_legacy_requirement_type(row),
        confidence=float(row.get("confidence") or 0),
        source_metadata=dict(_mapping(row.get("source_metadata"))),
        metadata=dict(_mapping(row.get("metadata"))),
        document_id=_optional_uuid(row.get("document_id")),
        chunk_id=_optional_uuid(row.get("chunk_id")),
        page_start=_optional_int(row.get("page_start")),
        page_end=_optional_int(row.get("page_end")),
        company_id=_optional_uuid(row.get("company_id")),
        field_path=(
            str(row.get("field_path")) if row.get("field_path") is not None else None
        ),
    )


def _infer_legacy_requirement_type(
    row: Mapping[str, Any],
) -> RequirementType | None:
    for value in (
        _mapping(row.get("metadata")).get("requirement_type"),
        _mapping(row.get("source_metadata")).get("requirement_type"),
        row.get("category"),
    ):
        requirement_type = _coerce_requirement_type(value)
        if requirement_type is not None:
            return requirement_type
    return None


def _coerce_requirement_type(value: Any) -> RequirementType | None:
    if value is None:
        return None
    if isinstance(value, RequirementType):
        return value
    text = str(value).strip().casefold()
    if not text:
        return None
    try:
        return RequirementType(text)
    except ValueError:
        return _REQUIREMENT_TYPE_BY_LEGACY_CATEGORY.get(text)


def _evidence_belongs_to_run(
    row: Mapping[str, Any],
    *,
    company_id: UUID,
    document_ids: Sequence[UUID],
) -> bool:
    source_type = str(row.get("source_type"))
    if source_type == EvidenceSourceType.TENDER_DOCUMENT.value:
        return _optional_uuid(row.get("document_id")) in set(document_ids)
    if source_type == EvidenceSourceType.COMPANY_PROFILE.value:
        return _optional_uuid(row.get("company_id")) == company_id
    return False


def _response_rows(response: Any) -> list[Mapping[str, Any]]:
    data = getattr(response, "data", None)
    if not isinstance(data, list):
        raise WorkerLifecycleError("Supabase query did not return a row list.")
    return [row for row in data if isinstance(row, Mapping)]


def _normalize_uuid(value: Any, field_name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise WorkerLifecycleError(f"{field_name} must be a UUID.") from exc


def _optional_uuid(value: Any) -> UUID | None:
    if value is None:
        return None
    return _normalize_uuid(value, "uuid")


def _int_value(value: Any, field_name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise WorkerLifecycleError(f"{field_name} must be an integer.") from exc


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return _int_value(value, "integer")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, str) else ()


def _timestamp(now: NowFactory) -> str:
    return now().astimezone(UTC).isoformat()


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _log(log: LogSink | None, message: str) -> None:
    if log is not None:
        log(message)


_AGENT_RUN_SELECT_COLUMNS = (
    "id,created_at,tenant_key,tender_id,company_id,status,run_config,"
    "error_details,started_at,completed_at,metadata"
)


__all__ = [
    "DEFAULT_WORKER_NAME",
    "SupabaseWorkerClient",
    "WorkerLifecycleError",
    "WorkerRunResult",
    "build_bid_run_state_from_supabase",
    "persist_agent_outputs",
    "run_worker_once",
]
