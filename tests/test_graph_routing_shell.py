from __future__ import annotations

from dataclasses import replace
from uuid import UUID

import pytest

from bidded.orchestration import (
    AgentRunStatus,
    BidRunState,
    DocumentChunkState,
    EvidenceItemState,
    EvidenceSourceType,
    GraphNodeHandlers,
    GraphRouteNode,
    InvalidGraphOutput,
    SpecialistRole,
    Verdict,
    default_graph_node_handlers,
    graph_routing_edge_table,
    run_bidded_graph_shell,
)

RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
COMPANY_ID = UUID("22222222-2222-4222-8222-222222222222")
TENDER_ID = UUID("33333333-3333-4333-8333-333333333333")
DOCUMENT_ID = UUID("44444444-4444-4444-8444-444444444444")
CHUNK_ID = UUID("55555555-5555-4555-8555-555555555555")
EVIDENCE_ID = UUID("66666666-6666-4666-8666-666666666666")


def _ready_state() -> BidRunState:
    return BidRunState(
        run_id=RUN_ID,
        company_id=COMPANY_ID,
        tender_id=TENDER_ID,
        document_ids=[DOCUMENT_ID],
        run_context={
            "tenant_key": "demo",
            "document_parse_statuses": {str(DOCUMENT_ID): "parsed"},
        },
        chunks=[
            DocumentChunkState(
                chunk_id=CHUNK_ID,
                document_id=DOCUMENT_ID,
                chunk_index=0,
                page_start=1,
                page_end=1,
                text="The supplier must provide ISO 27001 certification.",
            )
        ],
        evidence_board=[
            EvidenceItemState(
                evidence_id=EVIDENCE_ID,
                evidence_key="TENDER-REQ-001",
                source_type=EvidenceSourceType.TENDER_DOCUMENT,
                excerpt="The supplier must provide ISO 27001 certification.",
                normalized_meaning="ISO 27001 certification is mandatory.",
                category="shall_requirement",
                confidence=0.94,
                source_metadata={"source_label": "Tender page 1"},
                document_id=DOCUMENT_ID,
                chunk_id=CHUNK_ID,
                page_start=1,
                page_end=1,
            )
        ],
    )


def test_mocked_success_path_runs_fixed_graph_shell_to_end() -> None:
    initial_state = _ready_state()

    result = run_bidded_graph_shell(initial_state)

    assert result.state.status is AgentRunStatus.SUCCEEDED
    assert result.visited_nodes[0] is GraphRouteNode.PREFLIGHT
    assert result.visited_nodes[-1] is GraphRouteNode.END
    assert GraphRouteNode.EVIDENCE_SCOUT in result.visited_nodes
    assert GraphRouteNode.ROUND_1_JOIN in result.visited_nodes
    assert GraphRouteNode.ROUND_2_JOIN in result.visited_nodes
    assert GraphRouteNode.JUDGE in result.visited_nodes
    assert GraphRouteNode.PERSIST_DECISION in result.visited_nodes
    assert result.visited_nodes[-2] is GraphRouteNode.PERSIST_DECISION

    assert {
        GraphRouteNode.ROUND_1_COMPLIANCE,
        GraphRouteNode.ROUND_1_WIN_STRATEGIST,
        GraphRouteNode.ROUND_1_DELIVERY_CFO,
        GraphRouteNode.ROUND_1_RED_TEAM,
    } <= set(result.visited_nodes)
    assert {
        GraphRouteNode.ROUND_2_COMPLIANCE,
        GraphRouteNode.ROUND_2_WIN_STRATEGIST,
        GraphRouteNode.ROUND_2_DELIVERY_CFO,
        GraphRouteNode.ROUND_2_RED_TEAM,
    } <= set(result.visited_nodes)

    assert result.state.scout_output is not None
    assert set(result.state.motions) == set(SpecialistRole)
    assert set(result.state.rebuttals) == set(SpecialistRole)
    assert result.state.final_decision is not None
    assert result.state.chunks == initial_state.chunks
    assert result.state.evidence_board == initial_state.evidence_board


def test_routing_edge_table_documents_orchestrator_controlled_topology() -> None:
    edge_table = graph_routing_edge_table()

    assert {
        GraphRouteNode.PREFLIGHT,
        GraphRouteNode.EVIDENCE_SCOUT,
        GraphRouteNode.ROUND_1_JOIN,
        GraphRouteNode.ROUND_2_JOIN,
        GraphRouteNode.JUDGE,
        GraphRouteNode.PERSIST_DECISION,
        GraphRouteNode.FAILED,
        GraphRouteNode.NEEDS_HUMAN_REVIEW,
        GraphRouteNode.END,
    } <= {edge.source for edge in edge_table}
    assert all(edge.orchestrator_controlled for edge in edge_table)
    assert not any("llm" in edge.condition.lower() for edge in edge_table)

    preflight_failure = next(
        edge
        for edge in edge_table
        if edge.source is GraphRouteNode.PREFLIGHT
        and edge.destinations == (GraphRouteNode.FAILED,)
    )
    assert "parser_failed" in preflight_failure.condition
    assert "empty evidence board" in preflight_failure.condition

    scout_success = next(
        edge
        for edge in edge_table
        if edge.source is GraphRouteNode.EVIDENCE_SCOUT
        and GraphRouteNode.ROUND_1_COMPLIANCE in edge.destinations
    )
    assert scout_success.destinations == (
        GraphRouteNode.ROUND_1_COMPLIANCE,
        GraphRouteNode.ROUND_1_WIN_STRATEGIST,
        GraphRouteNode.ROUND_1_DELIVERY_CFO,
        GraphRouteNode.ROUND_1_RED_TEAM,
    )


def test_invalid_output_routes_to_retry_handler_and_failed_status() -> None:
    handlers = replace(
        default_graph_node_handlers(),
        evidence_scout=lambda _: InvalidGraphOutput(
            source=GraphRouteNode.EVIDENCE_SCOUT,
            message="Scout output omitted required evidence references.",
            field_path="scout_output.findings[0].evidence_refs",
        ),
    )

    result = run_bidded_graph_shell(_ready_state(), handlers=handlers)

    assert result.visited_nodes == (
        GraphRouteNode.PREFLIGHT,
        GraphRouteNode.EVIDENCE_SCOUT,
        GraphRouteNode.RETRY_HANDLER,
        GraphRouteNode.FAILED,
        GraphRouteNode.END,
    )
    assert result.state.status is AgentRunStatus.FAILED
    assert result.state.retry_counts == {GraphRouteNode.EVIDENCE_SCOUT.value: 1}
    assert result.state.last_error is not None
    assert result.state.last_error.retryable is False
    assert "Retry handling reached" in result.state.last_error.message
    assert result.state.validation_errors[0].field_path == (
        "scout_output.findings[0].evidence_refs"
    )


@pytest.mark.parametrize(
    ("state", "expected_error"),
    [
        (
            _ready_state().model_copy(update={"document_ids": []}),
            "At least one tender document must be registered.",
        ),
        (
            _ready_state().model_copy(
                update={
                    "run_context": {
                        "document_parse_statuses": {str(DOCUMENT_ID): "unparsed"}
                    }
                }
            ),
            f"Tender document {DOCUMENT_ID} is not parsed: unparsed.",
        ),
        (
            _ready_state().model_copy(
                update={
                    "run_context": {
                        "document_parse_statuses": {
                            str(DOCUMENT_ID): "parser_failed"
                        }
                    }
                }
            ),
            f"Tender document {DOCUMENT_ID} has parser_failed status.",
        ),
    ],
)
def test_preflight_routes_missing_or_unparsed_documents_to_failed(
    state: BidRunState,
    expected_error: str,
) -> None:
    result = run_bidded_graph_shell(state)

    assert result.visited_nodes == (
        GraphRouteNode.PREFLIGHT,
        GraphRouteNode.FAILED,
        GraphRouteNode.END,
    )
    assert result.state.status is AgentRunStatus.FAILED
    assert result.state.last_error is not None
    assert expected_error in result.state.last_error.message
    assert GraphRouteNode.EVIDENCE_SCOUT not in result.visited_nodes


def test_preflight_routes_empty_evidence_board_to_failed() -> None:
    state = _ready_state().model_copy(update={"evidence_board": []})

    result = run_bidded_graph_shell(state)

    assert result.visited_nodes == (
        GraphRouteNode.PREFLIGHT,
        GraphRouteNode.FAILED,
        GraphRouteNode.END,
    )
    assert result.state.status is AgentRunStatus.FAILED
    assert result.state.last_error is not None
    assert "Evidence board is empty." in result.state.last_error.message


def test_needs_human_review_decision_persists_then_routes_to_end() -> None:
    defaults = default_graph_node_handlers()

    def judge_needs_human_review(state: BidRunState):
        return defaults.judge(state).model_copy(
            update={
                "verdict": Verdict.NEEDS_HUMAN_REVIEW,
                "rationale": "Critical conflicting evidence prevents a verdict.",
                "missing_info": ["Confirm whether the mandatory certificate is valid."],
            }
        )

    handlers: GraphNodeHandlers = replace(
        defaults,
        judge=judge_needs_human_review,
    )

    result = run_bidded_graph_shell(_ready_state(), handlers=handlers)

    assert result.state.status is AgentRunStatus.NEEDS_HUMAN_REVIEW
    assert result.state.final_decision is not None
    assert result.state.final_decision.verdict is Verdict.NEEDS_HUMAN_REVIEW
    assert result.visited_nodes[-3:] == (
        GraphRouteNode.PERSIST_DECISION,
        GraphRouteNode.NEEDS_HUMAN_REVIEW,
        GraphRouteNode.END,
    )
