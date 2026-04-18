from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import UUID

from bidded.orchestration import (
    AgentRunStatus,
    BidRunState,
    DocumentChunkState,
    EvidenceItemState,
    EvidenceSourceType,
    GraphRouteNode,
    default_graph_node_handlers,
    run_bidded_graph_shell,
)
from bidded.orchestration.evidence_scout import (
    SIX_PACK_SCOUT_CATEGORIES,
    EvidenceScoutRequest,
    build_evidence_scout_handler,
)

RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
COMPANY_ID = UUID("22222222-2222-4222-8222-222222222222")
TENDER_ID = UUID("33333333-3333-4333-8333-333333333333")
DOCUMENT_ID = UUID("44444444-4444-4444-8444-444444444444")

SCOUT_FACTS = [
    (
        "deadline",
        "TENDER-DEADLINE-001",
        UUID("66666666-6666-4666-8666-666666666661"),
        UUID("55555555-5555-4555-8555-555555555551"),
        "Tenders must be submitted by 2026-05-15 at 12:00 CET.",
        "The submission deadline is 2026-05-15 at 12:00 CET.",
    ),
    (
        "shall_requirement",
        "TENDER-SHALL-001",
        UUID("66666666-6666-4666-8666-666666666662"),
        UUID("55555555-5555-4555-8555-555555555552"),
        "The supplier shall provide ISO 27001 certification.",
        "ISO 27001 certification is mandatory.",
    ),
    (
        "qualification_criterion",
        "TENDER-QUAL-001",
        UUID("66666666-6666-4666-8666-666666666663"),
        UUID("55555555-5555-4555-8555-555555555553"),
        "Bidders must show three comparable public-sector references.",
        "The tender requires three comparable public-sector references.",
    ),
    (
        "evaluation_criterion",
        "TENDER-EVAL-001",
        UUID("66666666-6666-4666-8666-666666666664"),
        UUID("55555555-5555-4555-8555-555555555554"),
        "Award evaluation weighs quality at 60 percent and price at 40 percent.",
        "Evaluation is weighted 60 percent quality and 40 percent price.",
    ),
    (
        "contract_risk",
        "TENDER-RISK-001",
        UUID("66666666-6666-4666-8666-666666666665"),
        UUID("55555555-5555-4555-8555-555555555555"),
        "Delay penalties apply for missed delivery milestones.",
        "Delay penalties apply if delivery milestones are missed.",
    ),
    (
        "required_submission_document",
        "TENDER-DOC-001",
        UUID("66666666-6666-4666-8666-666666666666"),
        UUID("55555555-5555-4555-8555-555555555556"),
        "The bid must include a signed data processing agreement.",
        "A signed data processing agreement is required in the submission.",
    ),
]


class RecordingMockClaude:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.requests: list[EvidenceScoutRequest] = []

    def extract(self, request: EvidenceScoutRequest) -> dict[str, Any]:
        self.requests.append(request)
        return self.payload


def _ready_state() -> BidRunState:
    chunks: list[DocumentChunkState] = []
    evidence_board: list[EvidenceItemState] = []
    for index, (category, evidence_key, evidence_id, chunk_id, excerpt, meaning) in (
        enumerate(SCOUT_FACTS, start=1)
    ):
        chunks.append(
            DocumentChunkState(
                chunk_id=chunk_id,
                document_id=DOCUMENT_ID,
                chunk_index=index - 1,
                page_start=index,
                page_end=index,
                text=excerpt,
                metadata={"source_label": f"Tender page {index}"},
            )
        )
        evidence_board.append(
            EvidenceItemState(
                evidence_id=evidence_id,
                evidence_key=evidence_key,
                source_type=EvidenceSourceType.TENDER_DOCUMENT,
                excerpt=excerpt,
                normalized_meaning=meaning,
                category=category,
                confidence=0.93,
                source_metadata={"source_label": f"Tender page {index}"},
                document_id=DOCUMENT_ID,
                chunk_id=chunk_id,
                page_start=index,
                page_end=index,
            )
        )

    return BidRunState(
        run_id=RUN_ID,
        company_id=COMPANY_ID,
        tender_id=TENDER_ID,
        document_ids=[DOCUMENT_ID],
        run_context={
            "tenant_key": "demo",
            "document_parse_statuses": {str(DOCUMENT_ID): "parsed"},
        },
        chunks=chunks,
        evidence_board=evidence_board,
    )


def _resolved_evidence_refs() -> list[dict[str, str]]:
    return [
        {
            "evidence_key": evidence_key,
            "source_type": "tender_document",
            "evidence_id": str(evidence_id),
        }
        for _, evidence_key, evidence_id, _, _, _ in SCOUT_FACTS
    ]


def _valid_scout_payload() -> dict[str, Any]:
    refs = _resolved_evidence_refs()
    return {
        "agent_role": "evidence_scout",
        "findings": [
            {
                "category": category,
                "claim": meaning,
                "evidence_refs": [refs[index]],
            }
            for index, (category, _, _, _, _, meaning) in enumerate(SCOUT_FACTS)
        ],
        "missing_info": [],
        "potential_blockers": [],
    }


def test_evidence_scout_extracts_six_pack_and_persists_agent_output() -> None:
    mock_claude = RecordingMockClaude(_valid_scout_payload())
    handlers = replace(
        default_graph_node_handlers(),
        evidence_scout=build_evidence_scout_handler(mock_claude),
    )

    result = run_bidded_graph_shell(_ready_state(), handlers=handlers)

    assert result.state.status is AgentRunStatus.SUCCEEDED
    assert GraphRouteNode.EVIDENCE_SCOUT in result.visited_nodes
    assert len(mock_claude.requests) == 1
    request = mock_claude.requests[0]
    assert tuple(request.categories) == SIX_PACK_SCOUT_CATEGORIES
    assert {chunk.category for chunk in request.retrieved_chunks} == set(
        SIX_PACK_SCOUT_CATEGORIES
    )

    assert result.state.scout_output is not None
    assert {finding.category for finding in result.state.scout_output.findings} == set(
        SIX_PACK_SCOUT_CATEGORIES
    )
    for finding in result.state.scout_output.findings:
        assert len(finding.evidence_refs) == 1
        assert finding.evidence_refs[0].evidence_id is not None

    scout_rows = [
        output
        for output in result.state.agent_outputs
        if output.agent_role == "evidence_scout"
    ]
    assert len(scout_rows) == 1
    scout_row = scout_rows[0]
    assert scout_row.round_name == "evidence"
    assert scout_row.output_type == "scout_output"
    assert len(scout_row.payload["findings"]) == 6
    assert {ref.evidence_id for ref in scout_row.evidence_refs} == {
        evidence_id for _, _, evidence_id, _, _, _ in SCOUT_FACTS
    }


def test_unsupported_mocked_claude_fact_fails_before_persistence() -> None:
    payload = _valid_scout_payload()
    payload["findings"][0] = {
        "category": "shall_requirement",
        "claim": "The supplier must hold ISO 9001 certification.",
        "evidence_refs": [
            {
                "evidence_key": "TENDER-UNSUPPORTED-001",
                "source_type": "tender_document",
                "evidence_id": str(UUID("99999999-9999-4999-8999-999999999999")),
            }
        ],
    }
    mock_claude = RecordingMockClaude(payload)
    handlers = replace(
        default_graph_node_handlers(),
        evidence_scout=build_evidence_scout_handler(mock_claude),
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
    assert result.state.scout_output is None
    assert result.state.agent_outputs == []
    assert result.state.validation_errors[0].field_path == "findings[0].evidence_refs"
    assert "not present in evidence_board" in result.state.validation_errors[0].message


def test_evidence_scout_schema_rejects_bid_recommendations() -> None:
    payload = _valid_scout_payload()
    payload["verdict"] = "bid"
    mock_claude = RecordingMockClaude(payload)
    handlers = replace(
        default_graph_node_handlers(),
        evidence_scout=build_evidence_scout_handler(mock_claude),
    )

    result = run_bidded_graph_shell(_ready_state(), handlers=handlers)

    assert result.state.status is AgentRunStatus.FAILED
    assert result.state.scout_output is None
    assert result.state.agent_outputs == []
    assert "Extra inputs are not permitted" in result.state.validation_errors[0].message
