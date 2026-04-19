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
    ScoutOutputState,
    SpecialistRole,
    default_graph_node_handlers,
    run_bidded_graph_shell,
)
from bidded.orchestration.specialist_motions import (
    Round1SpecialistRequest,
    build_round_1_specialist_handler,
    build_round_1_specialist_request,
)
from bidded.requirements import RequirementType

RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
COMPANY_ID = UUID("22222222-2222-4222-8222-222222222222")
TENDER_ID = UUID("33333333-3333-4333-8333-333333333333")
DOCUMENT_ID = UUID("44444444-4444-4444-8444-444444444444")
CHUNK_ID = UUID("55555555-5555-4555-8555-555555555555")
TENDER_EVIDENCE_ID = UUID("66666666-6666-4666-8666-666666666666")
COMPANY_EVIDENCE_ID = UUID("77777777-7777-4777-8777-777777777777")
FINANCIAL_EVIDENCE_ID = UUID("88888888-8888-4888-8888-888888888888")


class RecordingRound1Model:
    def __init__(self) -> None:
        self.requests: list[Round1SpecialistRequest] = []

    def draft_motion(self, request: Round1SpecialistRequest) -> dict[str, Any]:
        self.requests.append(request)
        tender_ref = {
            "evidence_key": "TENDER-SHALL-001",
            "source_type": "tender_document",
            "evidence_id": str(TENDER_EVIDENCE_ID),
        }
        company_ref = {
            "evidence_key": "COMPANY-CERT-001",
            "source_type": "company_profile",
            "evidence_id": str(COMPANY_EVIDENCE_ID),
        }
        formal_blockers = []
        if request.agent_role.value == SpecialistRole.COMPLIANCE.value:
            formal_blockers = [
                {
                    "claim": (
                        "The tender requires ISO 27001 proof before submission."
                    ),
                    "evidence_refs": [tender_ref],
                }
            ]

        return {
            "agent_role": request.agent_role.value,
            "vote": "conditional_bid",
            "confidence": 0.76,
            "top_findings": [
                {
                    "claim": (
                        "The tender requires ISO 27001 and the company profile "
                        "cites ISO 27001."
                    ),
                    "evidence_refs": [tender_ref, company_ref],
                }
            ],
            "role_specific_risks": [
                {
                    "claim": f"{request.agent_role.value} needs certificate validity.",
                    "evidence_refs": [company_ref],
                }
            ],
            "formal_blockers": formal_blockers,
            "potential_blockers": [],
            "assumptions": ["The certificate remains valid through submission."],
            "missing_info": ["Certificate expiry date."],
            "recommended_actions": ["Confirm certificate validity."],
        }


class InvalidFormalBlockerModel(RecordingRound1Model):
    def draft_motion(self, request: Round1SpecialistRequest) -> dict[str, Any]:
        payload = super().draft_motion(request)
        if request.agent_role.value == SpecialistRole.WIN_STRATEGIST.value:
            payload["formal_blockers"] = [
                {
                    "claim": "Win Strategist must not mark formal blockers.",
                    "evidence_refs": [
                        {
                            "evidence_key": "TENDER-SHALL-001",
                            "source_type": "tender_document",
                            "evidence_id": str(TENDER_EVIDENCE_ID),
                        }
                    ],
                }
            ]
        return payload


class FinancialProofFormalBlockerModel(RecordingRound1Model):
    def draft_motion(self, request: Round1SpecialistRequest) -> dict[str, Any]:
        payload = super().draft_motion(request)
        if request.agent_role.value == SpecialistRole.COMPLIANCE.value:
            payload["formal_blockers"] = [
                {
                    "claim": (
                        "Missing credit report evidence is a hard no-bid blocker."
                    ),
                    "evidence_refs": [_financial_ref()],
                }
            ]
        return payload


def _ready_state() -> BidRunState:
    return BidRunState(
        run_id=RUN_ID,
        company_id=COMPANY_ID,
        tender_id=TENDER_ID,
        document_ids=[DOCUMENT_ID],
        run_context={
            "tenant_key": "demo",
            "private_context": "must not reach Round 1 specialists",
            "document_parse_statuses": {str(DOCUMENT_ID): "parsed"},
        },
        chunks=[
            DocumentChunkState(
                chunk_id=CHUNK_ID,
                document_id=DOCUMENT_ID,
                chunk_index=0,
                page_start=1,
                page_end=1,
                text="The supplier shall provide ISO 27001 certification.",
            )
        ],
        evidence_board=[
            EvidenceItemState(
                evidence_id=TENDER_EVIDENCE_ID,
                evidence_key="TENDER-SHALL-001",
                source_type=EvidenceSourceType.TENDER_DOCUMENT,
                excerpt="The supplier shall provide ISO 27001 certification.",
                normalized_meaning="ISO 27001 certification is mandatory.",
                category="shall_requirement",
                requirement_type=RequirementType.QUALIFICATION_REQUIREMENT,
                confidence=0.94,
                source_metadata={
                    "source_label": "Tender page 1",
                    "regulatory_glossary_ids": ["quality_management_sosfs"],
                    "regulatory_glossary": [
                        {
                            "entry_id": "quality_management_sosfs",
                            "requirement_type": "quality_management",
                            "display_label": "Quality management / SOSFS",
                            "suggested_proof_action": (
                                "Prepare quality management certificates."
                            ),
                            "blocker_hint": (
                                "Missing mandatory quality-system proof can block "
                                "qualification."
                            ),
                        }
                    ],
                },
                document_id=DOCUMENT_ID,
                chunk_id=CHUNK_ID,
                page_start=1,
                page_end=1,
            ),
            EvidenceItemState(
                evidence_id=COMPANY_EVIDENCE_ID,
                evidence_key="COMPANY-CERT-001",
                source_type=EvidenceSourceType.COMPANY_PROFILE,
                excerpt="The company maintains ISO 27001 certification.",
                normalized_meaning="The company profile cites ISO 27001.",
                category="certification",
                confidence=0.91,
                source_metadata={"source_label": "Company profile"},
                company_id=COMPANY_ID,
                field_path="certifications.iso_27001",
            ),
        ],
    )


def _state_with_financial_requirement() -> BidRunState:
    state = _ready_state()
    return state.model_copy(
        update={
            "evidence_board": [
                *state.evidence_board,
                EvidenceItemState(
                    evidence_id=FINANCIAL_EVIDENCE_ID,
                    evidence_key="TENDER-FINANCIAL-001",
                    source_type=EvidenceSourceType.TENDER_DOCUMENT,
                    excerpt="Supplier must submit a current credit report.",
                    normalized_meaning="Financial standing proof is required.",
                    category="qualification_criterion",
                    requirement_type=RequirementType.FINANCIAL_STANDING,
                    confidence=0.92,
                    source_metadata={
                        "source_label": "Tender page 2",
                        "regulatory_glossary_ids": ["financial_standing"],
                        "regulatory_glossary": [
                            {
                                "entry_id": "financial_standing",
                                "requirement_type": "financial_standing",
                                "display_label": "Financial standing",
                                "suggested_proof_action": (
                                    "Prepare current credit report."
                                ),
                                "blocker_hint": (
                                    "Missing financial standing proof can block "
                                    "qualification."
                                ),
                            }
                        ],
                    },
                    document_id=DOCUMENT_ID,
                    chunk_id=CHUNK_ID,
                    page_start=2,
                    page_end=2,
                ),
            ]
        }
    )


def test_round_1_specialists_get_evidence_locked_requests_and_persist_rows() -> None:
    model = RecordingRound1Model()
    handlers = replace(
        default_graph_node_handlers(),
        round_1_specialist=build_round_1_specialist_handler(model),
    )

    result = run_bidded_graph_shell(_ready_state(), handlers=handlers)

    assert result.state.status is AgentRunStatus.SUCCEEDED
    assert GraphRouteNode.ROUND_1_JOIN in result.visited_nodes
    assert {request.agent_role.value for request in model.requests} == {
        role.value for role in SpecialistRole
    }
    expected_evidence_keys = ["TENDER-SHALL-001", "COMPANY-CERT-001"]
    assert [
        [item.evidence_key for item in request.evidence_board]
        for request in model.requests
    ] == [expected_evidence_keys] * 4
    assert all(request.scout_output is not None for request in model.requests)
    compliance_request = next(
        request
        for request in model.requests
        if request.agent_role.value == SpecialistRole.COMPLIANCE.value
    )
    assert [
        context.model_dump(mode="json")
        for context in compliance_request.requirement_context
    ] == [
        {
            "evidence_key": "TENDER-SHALL-001",
            "source_type": "tender_document",
            "evidence_id": str(TENDER_EVIDENCE_ID),
            "source_label": "Tender page 1",
            "requirement_type": "qualification_requirement",
            "regulatory_glossary_ids": ["quality_management_sosfs"],
            "regulatory_glossary": [
                {
                    "entry_id": "quality_management_sosfs",
                    "requirement_type": "quality_management",
                    "display_label": "Quality management / SOSFS",
                    "suggested_proof_action": (
                        "Prepare quality management certificates."
                    ),
                    "blocker_hint": (
                        "Missing mandatory quality-system proof can block "
                        "qualification."
                    ),
                }
            ],
        }
    ]

    request_fields = set(Round1SpecialistRequest.model_fields)
    assert "motions" not in request_fields
    assert "rebuttals" not in request_fields
    assert "run_context" not in request_fields
    assert "private_context" not in request_fields

    assert set(result.state.motions) == set(SpecialistRole)
    motion_rows = [
        output
        for output in result.state.agent_outputs
        if output.round_name == "round_1_motion"
    ]
    assert len(motion_rows) == 4
    assert {row.agent_role for row in motion_rows} == {
        role.value for role in SpecialistRole
    }
    assert all(row.output_type == "motion" for row in motion_rows)
    assert all(row.evidence_refs for row in motion_rows)

    for row in motion_rows:
        payload = row.payload
        assert payload["vote"] == "conditional_bid"
        assert payload["confidence"] == 0.76
        assert payload["top_findings"][0]["evidence_refs"]
        assert payload["role_specific_risks"][0]["evidence_refs"]
        assert payload["assumptions"] == [
            "The certificate remains valid through submission."
        ]
        assert payload["missing_info"] == ["Certificate expiry date."]
        assert payload["recommended_actions"] == ["Confirm certificate validity."]

    blockers_by_role = {
        row.agent_role: row.payload["formal_blockers"] for row in motion_rows
    }
    assert blockers_by_role[SpecialistRole.COMPLIANCE.value]
    assert blockers_by_role[SpecialistRole.WIN_STRATEGIST.value] == []
    assert blockers_by_role[SpecialistRole.DELIVERY_CFO.value] == []
    assert blockers_by_role[SpecialistRole.RED_TEAM.value] == []


def test_compliance_request_includes_evidence_recall_warnings() -> None:
    state = _ready_state().model_copy(
        update={
            "chunks": [
                DocumentChunkState(
                    chunk_id=UUID("55555555-5555-4555-8555-555555555556"),
                    document_id=DOCUMENT_ID,
                    chunk_index=1,
                    page_start=2,
                    page_end=2,
                    text="Bidders must submit a current credit report.",
                    metadata={"source_label": "Tender page 2"},
                )
            ],
            "scout_output": ScoutOutputState(),
        }
    )

    request = build_round_1_specialist_request(state, SpecialistRole.COMPLIANCE)

    recalled_types = [
        warning.requirement_type for warning in request.evidence_recall_warnings
    ]
    assert recalled_types == [RequirementType.FINANCIAL_STANDING]
    assert request.evidence_recall_warnings[0].source_label == "Tender page 2"
    assert "financial_standing" in request.evidence_recall_warnings[0].missing_info


def test_non_compliance_formal_blocker_fails_before_round_1_persistence() -> None:
    handlers = replace(
        default_graph_node_handlers(),
        round_1_specialist=build_round_1_specialist_handler(
            InvalidFormalBlockerModel()
        ),
    )

    result = run_bidded_graph_shell(_ready_state(), handlers=handlers)

    assert result.visited_nodes[:2] == (
        GraphRouteNode.PREFLIGHT,
        GraphRouteNode.EVIDENCE_SCOUT,
    )
    assert set(result.visited_nodes[2:6]) == {
        GraphRouteNode.ROUND_1_COMPLIANCE,
        GraphRouteNode.ROUND_1_WIN_STRATEGIST,
        GraphRouteNode.ROUND_1_DELIVERY_CFO,
        GraphRouteNode.ROUND_1_RED_TEAM,
    }
    assert result.visited_nodes[-3:] == (
        GraphRouteNode.ROUND_1_JOIN,
        GraphRouteNode.FAILED,
        GraphRouteNode.END,
    )
    assert result.state.status is AgentRunStatus.FAILED
    assert result.state.retry_counts == {
        GraphRouteNode.ROUND_1_WIN_STRATEGIST.value: 2
    }
    assert result.state.motions == {}
    assert not any(
        output.round_name == "round_1_motion"
        for output in result.state.agent_outputs
    )
    assert result.state.validation_errors
    assert "formal_blockers" in result.state.validation_errors[-1].message


def test_financial_proof_gap_cannot_be_compliance_formal_blocker() -> None:
    handlers = replace(
        default_graph_node_handlers(),
        round_1_specialist=build_round_1_specialist_handler(
            FinancialProofFormalBlockerModel()
        ),
    )

    result = run_bidded_graph_shell(
        _state_with_financial_requirement(),
        handlers=handlers,
    )

    assert result.state.status is AgentRunStatus.FAILED
    assert result.state.motions == {}
    assert not any(
        output.round_name == "round_1_motion"
        for output in result.state.agent_outputs
    )
    assert result.state.validation_errors
    assert "formal_blockers" in result.state.validation_errors[-1].field_path
    assert "exclusion_ground or qualification_requirement" in (
        result.state.validation_errors[-1].message
    )


def _financial_ref() -> dict[str, str]:
    return {
        "evidence_key": "TENDER-FINANCIAL-001",
        "source_type": "tender_document",
        "evidence_id": str(FINANCIAL_EVIDENCE_ID),
    }
