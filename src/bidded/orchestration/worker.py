from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from bidded.orchestration.graph import (
    GraphNodeHandlers,
    GraphRunResult,
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

DEFAULT_WORKER_NAME = "bidded_cli_worker"


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


GraphRunner = Callable[[BidRunState], GraphRunResult]
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

        def _runner(state: BidRunState) -> GraphRunResult:
            return run_bidded_graph_shell(state, handlers=graph_handlers)

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
        raise WorkerLifecycleError(
            f"Agent run {normalized_run_id} must be pending, not {status.value}."
        )

    metadata = _mapping(selected_run.get("metadata"))
    started_at = _timestamp(now)
    _log(log, f"Starting agent run {normalized_run_id}.")
    metadata = _update_run_status(
        client,
        run_id=normalized_run_id,
        tenant_key=tenant_key,
        status=AgentRunStatus.RUNNING,
        timestamp=started_at,
        metadata=metadata,
        current_step="preflight",
        error_details=None,
    )

    try:
        state = build_bid_run_state_from_supabase(
            client,
            run_row=selected_run,
            tenant_key=tenant_key,
        )
        graph_result = graph_runner(state)
        terminal_state = graph_result.state
        visited_nodes = tuple(node.value for node in graph_result.visited_nodes)

        if terminal_state.status is AgentRunStatus.FAILED:
            completed_at = _timestamp(now)
            error_details = _graph_error_details(terminal_state.last_error)
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
                ),
                error_details=error_details,
            )
            message = (
                f"Agent run {normalized_run_id} failed: "
                f"{error_details['message']}"
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

        output_count = persist_agent_outputs(
            client,
            terminal_state.agent_outputs,
            run_id=normalized_run_id,
            tenant_key=tenant_key,
        )
        if terminal_state.final_decision is None:
            raise WorkerLifecycleError("Graph completed without a final decision.")
        persist_final_decision(client, terminal_state, tenant_key=tenant_key)

        completed_at = _timestamp(now)
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
                current_step="failed",
                details={"error_code": error_details["code"]},
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
        (
            "id,tenant_key,document_id,page_start,page_end,chunk_index,text,"
            "metadata"
        ),
        tenant_key=tenant_key,
    )
    evidence_rows = _fetch_tenant_rows(
        client,
        "evidence_items",
        (
            "id,tenant_key,evidence_key,source_type,excerpt,normalized_meaning,"
            "category,confidence,source_metadata,document_id,chunk_id,page_start,"
            "page_end,company_id,field_path,metadata"
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
        and str(row.get("text") or "").strip()
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


def _terminal_metadata(
    metadata: Mapping[str, Any],
    *,
    terminal_state: BidRunState,
    visited_nodes: Sequence[str],
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
        timestamp=_utc_now().isoformat(),
        current_step=_current_step_value(terminal_state),
        details=details,
    )


def _worker_metadata(
    metadata: Mapping[str, Any],
    *,
    status: AgentRunStatus,
    timestamp: str,
    current_step: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    merged = dict(metadata)
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
    return {
        "tenant_key": tenant_key,
        "agent_run_id": str(run_id),
        "agent_role": output.agent_role,
        "round_name": output.round_name,
        "output_type": output.output_type,
        "validated_payload": output.payload,
        "model_metadata": {},
        "validation_errors": [
            error.model_dump(mode="json") for error in output.validation_errors
        ],
        "metadata": {
            "source": DEFAULT_WORKER_NAME,
            "audit_artifact": "validated_payload",
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
    rows = _response_rows(
        client.table(table_name).select(columns).eq("tenant_key", tenant_key).execute()
    )
    return [dict(row) for row in rows]


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
        confidence=float(row.get("confidence") or 0),
        source_metadata=dict(_mapping(row.get("source_metadata"))),
        document_id=_optional_uuid(row.get("document_id")),
        chunk_id=_optional_uuid(row.get("chunk_id")),
        page_start=_optional_int(row.get("page_start")),
        page_end=_optional_int(row.get("page_end")),
        company_id=_optional_uuid(row.get("company_id")),
        field_path=(
            str(row.get("field_path"))
            if row.get("field_path") is not None
            else None
        ),
    )


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
