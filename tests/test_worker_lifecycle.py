from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from bidded.orchestration import (
    AgentOutputState,
    AgentRunStatus,
    EvidenceRef,
    EvidenceSourceType,
    FinalDecisionState,
    GraphRouteNode,
    GraphRunResult,
    RequirementType,
    Verdict,
    run_bidded_graph_shell,
)
from bidded.orchestration.worker import (
    DEFAULT_WORKER_NAME,
    build_bid_run_state_from_supabase,
    run_worker_once,
)

RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
OLDER_RUN_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
COMPANY_ID = UUID("22222222-2222-4222-8222-222222222222")
TENDER_ID = UUID("33333333-3333-4333-8333-333333333333")
DOCUMENT_ID = UUID("44444444-4444-4444-8444-444444444444")
CHUNK_ID = UUID("55555555-5555-4555-8555-555555555555")
EVIDENCE_ID = UUID("66666666-6666-4666-8666-666666666666")
SECOND_EVIDENCE_ID = UUID("77777777-7777-4777-8777-777777777777")


class RecordingWorkerQuery:
    def __init__(self, client: RecordingWorkerClient, table_name: str) -> None:
        self.client = client
        self.table_name = table_name
        self.filters: list[tuple[str, str]] = []
        self.order_column: str | None = None
        self.descending = False
        self.row_limit: int | None = None
        self.update_payload: dict[str, Any] | None = None
        self.insert_payload: dict[str, Any] | list[dict[str, Any]] | None = None

    def select(self, _columns: str) -> RecordingWorkerQuery:
        return self

    def eq(self, column: str, value: object) -> RecordingWorkerQuery:
        self.filters.append((column, str(value)))
        return self

    def order(self, column: str, *, desc: bool = False) -> RecordingWorkerQuery:
        self.order_column = column
        self.descending = desc
        return self

    def limit(self, row_limit: int) -> RecordingWorkerQuery:
        self.row_limit = row_limit
        return self

    def update(self, payload: dict[str, Any]) -> RecordingWorkerQuery:
        self.update_payload = payload
        return self

    def insert(
        self,
        payload: dict[str, Any] | list[dict[str, Any]],
    ) -> RecordingWorkerQuery:
        self.insert_payload = payload
        return self

    def execute(self) -> object:
        if self.update_payload is not None:
            if (
                self.table_name == "agent_runs"
                and self.client.skip_next_agent_run_update
            ):
                self.client.skip_next_agent_run_update = False
                for row in self.client.rows["agent_runs"]:
                    if row.get("id") == str(RUN_ID):
                        row["status"] = "running"
                        row["started_at"] = "2026-04-18T17:59:00+00:00"
                        row["metadata"] = {
                            "worker": {
                                "name": "other_worker",
                                "last_status": "running",
                                "updated_at": "2026-04-18T17:59:00+00:00",
                            }
                        }
                return type("Response", (), {"data": []})()

            self.client.updates.setdefault(self.table_name, []).append(
                (self.update_payload, self.filters)
            )
            rows = self._filtered_rows()
            for row in rows:
                row.update(self.update_payload)
            return type("Response", (), {"data": rows})()

        if self.insert_payload is not None:
            self.client.inserts.setdefault(self.table_name, []).append(
                self.insert_payload
            )
            payload_rows = (
                self.insert_payload
                if isinstance(self.insert_payload, list)
                else [self.insert_payload]
            )
            return type("Response", (), {"data": payload_rows})()

        return type("Response", (), {"data": self._filtered_rows()})()

    def _filtered_rows(self) -> list[dict[str, Any]]:
        rows = [
            row
            for row in self.client.rows.get(self.table_name, [])
            if all(str(row.get(column)) == value for column, value in self.filters)
        ]
        if self.order_column is not None:
            rows = sorted(
                rows,
                key=lambda row: str(row.get(self.order_column) or ""),
                reverse=self.descending,
            )
        if self.row_limit is not None:
            rows = rows[: self.row_limit]
        return rows


class RecordingWorkerClient:
    def __init__(self) -> None:
        self.rows: dict[str, list[dict[str, Any]]] = {
            "agent_runs": [_pending_agent_run()],
            "documents": [_parsed_document()],
            "document_chunks": [_document_chunk()],
            "evidence_items": [_tender_evidence_item()],
        }
        self.inserts: dict[str, list[dict[str, Any] | list[dict[str, Any]]]] = {}
        self.updates: dict[str, list[tuple[dict[str, Any], list[tuple[str, str]]]]] = {}
        self.table_names: list[str] = []
        self.skip_next_agent_run_update = False

    def table(self, table_name: str) -> RecordingWorkerQuery:
        self.table_names.append(table_name)
        return RecordingWorkerQuery(self, table_name)


def test_worker_runs_specified_pending_run_and_persists_audit_rows() -> None:
    client = RecordingWorkerClient()

    result = run_worker_once(
        client,
        run_id=RUN_ID,
        now_factory=lambda: datetime(2026, 4, 18, 18, 0, tzinfo=UTC),
    )

    assert result.run_id == RUN_ID
    assert result.terminal_status is AgentRunStatus.SUCCEEDED
    assert result.decision_verdict is Verdict.CONDITIONAL_BID
    assert result.agent_output_count == 10

    run_updates = client.updates["agent_runs"]
    assert run_updates[0][0]["status"] == "running"
    assert run_updates[0][0]["started_at"] == "2026-04-18T18:00:00+00:00"
    assert ("status", "pending") in run_updates[0][1]
    assert run_updates[-1][0]["status"] == "succeeded"
    assert run_updates[-1][0]["completed_at"] == "2026-04-18T18:00:00+00:00"
    assert client.rows["agent_runs"][0]["status"] == "succeeded"
    demo_trace = client.rows["agent_runs"][0]["metadata"]["demo_trace"]
    assert [entry["step"] for entry in demo_trace] == [
        "claim_run",
        "load_run_context",
        "run_graph",
        "persist_agent_outputs",
        "persist_final_decision",
        "complete_run",
    ]
    assert all(entry["status"] == "completed" for entry in demo_trace)
    assert all(
        entry["started_at"] == "2026-04-18T18:00:00+00:00"
        for entry in demo_trace
    )
    assert all(
        entry["completed_at"] == "2026-04-18T18:00:00+00:00"
        for entry in demo_trace
    )
    assert all(entry["duration_ms"] == 0 for entry in demo_trace)
    assert "raw_prompt" not in repr(demo_trace)
    assert "private_context" not in repr(demo_trace)
    assert "full_pdf_text" not in repr(demo_trace)

    agent_outputs = client.inserts["agent_outputs"][0]
    assert isinstance(agent_outputs, list)
    assert len(agent_outputs) == 10
    assert {
        output["agent_role"]
        for output in agent_outputs
        if output["round_name"] == "round_1_motion"
    } == {"compliance_officer", "win_strategist", "delivery_cfo", "red_team"}
    assert all("validated_payload" in output for output in agent_outputs)
    assert all("raw_prompt" not in output for output in agent_outputs)
    assert all("raw_prompt" not in output["metadata"] for output in agent_outputs)

    bid_decision = client.inserts["bid_decisions"][0]
    assert isinstance(bid_decision, dict)
    assert bid_decision["agent_run_id"] == str(RUN_ID)
    assert bid_decision["verdict"] == "conditional_bid"
    assert bid_decision["evidence_ids"] == [str(EVIDENCE_ID)]


def test_worker_persists_version_metadata_for_mocked_runs() -> None:
    client = RecordingWorkerClient()

    result = run_worker_once(
        client,
        run_id=RUN_ID,
        now_factory=lambda: datetime(2026, 4, 18, 18, 0, tzinfo=UTC),
    )

    assert result.terminal_status is AgentRunStatus.SUCCEEDED
    expected_metadata = {
        "prompt_version": "bidded_prompt_v1",
        "schema_version": "bidded_agent_output_schema_v1",
        "retrieval_version": "bidded_hybrid_retrieval_v1",
        "model_name": "mocked_graph_shell",
    }
    assert client.rows["agent_runs"][0]["metadata"]["version_metadata"] == (
        expected_metadata
    )

    agent_outputs = client.inserts["agent_outputs"][0]
    assert isinstance(agent_outputs, list)
    assert all(
        output["model_metadata"] == expected_metadata for output in agent_outputs
    )
    assert all(
        output["metadata"]["version_metadata"] == expected_metadata
        for output in agent_outputs
    )


def test_worker_claims_run_before_graph_execution() -> None:
    client = RecordingWorkerClient()
    captured_state: dict[str, Any] = {}

    def recording_runner(state: Any) -> GraphRunResult:
        captured_state["status"] = state.status
        captured_state["metadata"] = state.run_context["metadata"]
        return run_bidded_graph_shell(state)

    result = run_worker_once(
        client,
        run_id=RUN_ID,
        graph_runner=recording_runner,
        now_factory=lambda: datetime(2026, 4, 18, 18, 0, tzinfo=UTC),
    )

    assert result.terminal_status is AgentRunStatus.SUCCEEDED
    assert captured_state["status"] is AgentRunStatus.RUNNING
    assert captured_state["metadata"]["worker"]["name"] == DEFAULT_WORKER_NAME
    assert captured_state["metadata"]["worker"]["last_status"] == "running"
    assert captured_state["metadata"]["worker"]["updated_at"] == (
        "2026-04-18T18:00:00+00:00"
    )
    assert client.rows["agent_runs"][0]["started_at"] == (
        "2026-04-18T18:00:00+00:00"
    )


@pytest.mark.parametrize("status", ["succeeded", "failed", "needs_human_review"])
def test_worker_does_not_claim_terminal_run(status: str) -> None:
    client = RecordingWorkerClient()
    terminal_row = _pending_agent_run(
        status=status,
        started_at="2026-04-18T17:30:00+00:00",
        completed_at="2026-04-18T17:45:00+00:00",
    )
    client.rows["agent_runs"] = [terminal_row.copy()]

    def forbidden_runner(_state: Any) -> GraphRunResult:
        raise AssertionError("terminal runs must not execute the graph")

    result = run_worker_once(
        client,
        run_id=RUN_ID,
        graph_runner=forbidden_runner,
        now_factory=lambda: datetime(2026, 4, 18, 18, 0, tzinfo=UTC),
    )

    assert result.run_id is None
    assert result.terminal_status is None
    assert result.agent_output_count == 0
    assert "No pending demo agent run found." == result.message
    assert client.rows["agent_runs"][0] == terminal_row
    assert "agent_runs" not in client.updates
    assert "agent_outputs" not in client.inserts
    assert "bid_decisions" not in client.inserts


def test_worker_returns_no_run_when_pending_claim_was_already_taken() -> None:
    client = RecordingWorkerClient()
    client.skip_next_agent_run_update = True

    def forbidden_runner(_state: Any) -> GraphRunResult:
        raise AssertionError("double-claimed runs must not execute the graph")

    result = run_worker_once(
        client,
        run_id=RUN_ID,
        graph_runner=forbidden_runner,
        now_factory=lambda: datetime(2026, 4, 18, 18, 0, tzinfo=UTC),
    )

    assert result.run_id is None
    assert result.terminal_status is None
    assert result.agent_output_count == 0
    assert result.message == "No pending demo agent run found."
    assert client.rows["agent_runs"][0]["status"] == "running"
    assert client.rows["agent_runs"][0]["metadata"]["worker"]["name"] == (
        "other_worker"
    )
    assert "agent_runs" not in client.updates
    assert "agent_outputs" not in client.inserts
    assert "bid_decisions" not in client.inserts


def test_worker_returns_no_run_when_no_pending_run_exists() -> None:
    client = RecordingWorkerClient()
    client.rows["agent_runs"] = [
        _pending_agent_run(
            status="succeeded",
            started_at="2026-04-18T17:30:00+00:00",
            completed_at="2026-04-18T17:45:00+00:00",
        )
    ]

    def forbidden_runner(_state: Any) -> GraphRunResult:
        raise AssertionError("no-pending runs must not execute the graph")

    result = run_worker_once(
        client,
        graph_runner=forbidden_runner,
        now_factory=lambda: datetime(2026, 4, 18, 18, 0, tzinfo=UTC),
    )

    assert result.run_id is None
    assert result.terminal_status is None
    assert result.agent_output_count == 0
    assert result.message == "No pending demo agent run found."
    assert "agent_runs" not in client.updates
    assert "agent_outputs" not in client.inserts
    assert "bid_decisions" not in client.inserts


def test_worker_loads_typed_and_legacy_requirement_type_evidence() -> None:
    client = RecordingWorkerClient()
    typed_row = {
        **_tender_evidence_item(),
        "requirement_type": "shall_requirement",
        "metadata": {"contract_clause_ids": ["insurance"]},
    }
    legacy_row = {
        **_tender_evidence_item(),
        "id": str(SECOND_EVIDENCE_ID),
        "evidence_key": "TENDER-RISK-001",
        "excerpt": "Delay penalties apply for missed milestones.",
        "normalized_meaning": "Delay penalties are contract obligations.",
        "category": "contract_risk",
    }
    client.rows["evidence_items"] = [typed_row, legacy_row]

    state = build_bid_run_state_from_supabase(
        client,
        run_row=_pending_agent_run(),
    )

    assert state.evidence_board[0].requirement_type is (
        RequirementType.SHALL_REQUIREMENT
    )
    assert state.evidence_board[1].requirement_type is None
    assert [item.category for item in state.evidence_board] == [
        "shall_requirement",
        "contract_risk",
    ]
    assert state.evidence_board[0].metadata == {
        "contract_clause_ids": ["insurance"]
    }


def test_worker_picks_oldest_pending_demo_run_when_run_id_is_omitted() -> None:
    client = RecordingWorkerClient()
    client.rows["agent_runs"] = [
        _pending_agent_run(
            id=str(RUN_ID),
            created_at="2026-04-18T17:00:00+00:00",
        ),
        _pending_agent_run(
            id=str(OLDER_RUN_ID),
            created_at="2026-04-18T16:00:00+00:00",
        ),
    ]

    result = run_worker_once(
        client,
        now_factory=lambda: datetime(2026, 4, 18, 18, 0, tzinfo=UTC),
    )

    assert result.run_id == OLDER_RUN_ID
    assert result.terminal_status is AgentRunStatus.SUCCEEDED
    first_update_filters = client.updates["agent_runs"][0][1]
    assert ("id", str(OLDER_RUN_ID)) in first_update_filters
    assert client.rows["agent_runs"][0]["status"] == "pending"
    assert client.rows["agent_runs"][1]["status"] == "succeeded"


def test_worker_marks_run_failed_when_graph_preflight_fails() -> None:
    client = RecordingWorkerClient()
    client.rows["evidence_items"] = []

    result = run_worker_once(
        client,
        run_id=RUN_ID,
        now_factory=lambda: datetime(2026, 4, 18, 18, 0, tzinfo=UTC),
    )

    assert result.terminal_status is AgentRunStatus.FAILED
    assert result.decision_verdict is None
    assert "Evidence board is empty." in result.message
    assert client.rows["agent_runs"][0]["status"] == "failed"

    failed_update = client.updates["agent_runs"][-1][0]
    assert failed_update["status"] == "failed"
    assert failed_update["error_details"]["code"] == "graph_failed"
    assert "Evidence board is empty." in failed_update["error_details"]["message"]
    demo_trace = client.rows["agent_runs"][0]["metadata"]["demo_trace"]
    assert [entry["step"] for entry in demo_trace] == [
        "claim_run",
        "load_run_context",
        "run_graph",
        "complete_run",
    ]
    assert demo_trace[2]["status"] == "failed"
    assert demo_trace[2]["error_code"] == "graph_failed"
    assert demo_trace[2]["duration_ms"] == 0
    assert demo_trace[-1]["status"] == "completed"
    assert "agent_outputs" not in client.inserts
    assert "bid_decisions" not in client.inserts


def test_worker_trace_redacts_exception_context() -> None:
    client = RecordingWorkerClient()

    def failing_runner(_state: Any) -> GraphRunResult:
        raise RuntimeError(
            "raw_prompt sk-ant-secret full_pdf_text private_context supplier data"
        )

    result = run_worker_once(
        client,
        run_id=RUN_ID,
        graph_runner=failing_runner,
        now_factory=lambda: datetime(2026, 4, 18, 18, 0, tzinfo=UTC),
    )

    assert result.terminal_status is AgentRunStatus.FAILED
    demo_trace = client.rows["agent_runs"][0]["metadata"]["demo_trace"]
    assert demo_trace[2]["step"] == "run_graph"
    assert demo_trace[2]["status"] == "failed"
    assert demo_trace[2]["error_code"] == "worker_error"
    trace_text = repr(demo_trace)
    assert "raw_prompt" not in trace_text
    assert "sk-ant-secret" not in trace_text
    assert "full_pdf_text" not in trace_text
    assert "private_context" not in trace_text


def test_worker_appends_trace_entries_and_preserves_run_metadata() -> None:
    client = RecordingWorkerClient()
    existing_trace = {
        "step": "register_demo_tender",
        "status": "completed",
        "started_at": "2026-04-18T17:50:00+00:00",
        "completed_at": "2026-04-18T17:50:01+00:00",
        "duration_ms": 1000,
    }
    client.rows["agent_runs"][0]["metadata"] = {
        "created_via": "test",
        "operator_note": "preserve this compact note",
        "demo_trace": [existing_trace],
    }

    result = run_worker_once(
        client,
        run_id=RUN_ID,
        now_factory=lambda: datetime(2026, 4, 18, 18, 0, tzinfo=UTC),
    )

    assert result.terminal_status is AgentRunStatus.SUCCEEDED
    metadata = client.rows["agent_runs"][0]["metadata"]
    assert metadata["created_via"] == "test"
    assert metadata["operator_note"] == "preserve this compact note"
    assert metadata["demo_trace"][0] == existing_trace
    assert [entry["step"] for entry in metadata["demo_trace"][1:]] == [
        "claim_run",
        "load_run_context",
        "run_graph",
        "persist_agent_outputs",
        "persist_final_decision",
        "complete_run",
    ]


def test_worker_persists_needs_human_review_terminal_status() -> None:
    client = RecordingWorkerClient()

    def needs_human_review_runner(state: Any) -> GraphRunResult:
        evidence_ref = EvidenceRef(
            evidence_key="TENDER-REQ-001",
            source_type=EvidenceSourceType.TENDER_DOCUMENT,
            evidence_id=EVIDENCE_ID,
        )
        decision = FinalDecisionState(
            verdict=Verdict.NEEDS_HUMAN_REVIEW,
            confidence=0.4,
            rationale="Critical conflicting evidence prevents a defensible verdict.",
            cited_memo=(
                "Critical conflicting evidence prevents a defensible final verdict."
            ),
            missing_info=["Confirm whether the certificate evidence is current."],
            evidence_ids=[EVIDENCE_ID],
            evidence_refs=[evidence_ref],
        )
        output = AgentOutputState(
            agent_role="judge",
            round_name="final_decision",
            output_type="decision",
            payload=decision.model_dump(mode="json"),
            evidence_refs=[evidence_ref],
        )
        return GraphRunResult(
            state=state.model_copy(
                update={
                    "status": AgentRunStatus.NEEDS_HUMAN_REVIEW,
                    "final_decision": decision,
                    "agent_outputs": [output],
                }
            ),
            visited_nodes=(
                GraphRouteNode.PREFLIGHT,
                GraphRouteNode.PERSIST_DECISION,
                GraphRouteNode.NEEDS_HUMAN_REVIEW,
                GraphRouteNode.END,
            ),
        )

    result = run_worker_once(
        client,
        run_id=RUN_ID,
        graph_runner=needs_human_review_runner,
        now_factory=lambda: datetime(2026, 4, 18, 18, 0, tzinfo=UTC),
    )

    assert result.terminal_status is AgentRunStatus.NEEDS_HUMAN_REVIEW
    assert result.decision_verdict is Verdict.NEEDS_HUMAN_REVIEW
    assert client.rows["agent_runs"][0]["status"] == "needs_human_review"
    assert client.inserts["bid_decisions"][0]["verdict"] == "needs_human_review"
    assert client.inserts["agent_outputs"][0][0]["agent_role"] == "judge"


def _pending_agent_run(**overrides: Any) -> dict[str, Any]:
    row = {
        "id": str(RUN_ID),
        "created_at": "2026-04-18T17:00:00+00:00",
        "tenant_key": "demo",
        "tender_id": str(TENDER_ID),
        "company_id": str(COMPANY_ID),
        "status": "pending",
        "run_config": {"document_ids": [str(DOCUMENT_ID)]},
        "metadata": {"created_via": "test"},
        "error_details": None,
        "started_at": None,
        "completed_at": None,
    }
    row.update(overrides)
    return row


def _parsed_document() -> dict[str, Any]:
    return {
        "id": str(DOCUMENT_ID),
        "tenant_key": "demo",
        "tender_id": str(TENDER_ID),
        "company_id": None,
        "document_role": "tender_document",
        "parse_status": "parsed",
        "original_filename": "Tender.pdf",
        "metadata": {"source_label": "Tender.pdf"},
    }


def _document_chunk() -> dict[str, Any]:
    return {
        "id": str(CHUNK_ID),
        "tenant_key": "demo",
        "document_id": str(DOCUMENT_ID),
        "page_start": 1,
        "page_end": 1,
        "chunk_index": 0,
        "text": "The supplier must provide ISO 27001 certification.",
        "metadata": {"source_label": "Tender.pdf"},
    }


def _tender_evidence_item() -> dict[str, Any]:
    return {
        "id": str(EVIDENCE_ID),
        "tenant_key": "demo",
        "evidence_key": "TENDER-REQ-001",
        "source_type": "tender_document",
        "excerpt": "The supplier must provide ISO 27001 certification.",
        "normalized_meaning": "ISO 27001 certification is mandatory.",
        "category": "shall_requirement",
        "confidence": 0.94,
        "source_metadata": {"source_label": "Tender page 1"},
        "document_id": str(DOCUMENT_ID),
        "chunk_id": str(CHUNK_ID),
        "page_start": 1,
        "page_end": 1,
        "company_id": None,
        "field_path": None,
        "metadata": {},
    }
