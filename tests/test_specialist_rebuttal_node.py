from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import UUID

from bidded.agents import AgentRole
from bidded.orchestration import (
    AgentRunStatus,
    BidRunState,
    DocumentChunkState,
    EvidenceItemState,
    EvidenceSourceType,
    GraphRouteNode,
    SpecialistMotionState,
    SpecialistRole,
    Verdict,
    default_graph_node_handlers,
    run_bidded_graph_shell,
)
from bidded.orchestration.specialist_rebuttals import (
    Round2RebuttalRequest,
    build_round_2_rebuttal_handler,
)

RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
COMPANY_ID = UUID("22222222-2222-4222-8222-222222222222")
TENDER_ID = UUID("33333333-3333-4333-8333-333333333333")
DOCUMENT_ID = UUID("44444444-4444-4444-8444-444444444444")
CHUNK_ID = UUID("55555555-5555-4555-8555-555555555555")
TENDER_EVIDENCE_ID = UUID("66666666-6666-4666-8666-666666666666")
COMPANY_EVIDENCE_ID = UUID("77777777-7777-4777-8777-777777777777")
UNKNOWN_EVIDENCE_ID = UUID("88888888-8888-4888-8888-888888888888")


class RecordingRound2Model:
    def __init__(self) -> None:
        self.requests: list[Round2RebuttalRequest] = []

    def draft_rebuttal(self, request: Round2RebuttalRequest) -> dict[str, Any]:
        self.requests.append(request)
        tender_ref = {
            "evidence_key": "TENDER-SHALL-001",
            "source_type": "tender_document",
            "evidence_id": str(TENDER_EVIDENCE_ID),
        }

        if request.agent_role is AgentRole.RED_TEAM:
            target_roles = [AgentRole.WIN_STRATEGIST, AgentRole.DELIVERY_CFO]
            target_role = AgentRole.WIN_STRATEGIST
            disputed_claim = request.motions[AgentRole.WIN_STRATEGIST].summary
            revised_stance = "no_bid"
        else:
            target_roles = [AgentRole.RED_TEAM]
            target_role = AgentRole.RED_TEAM
            disputed_claim = request.motions[AgentRole.RED_TEAM].summary
            revised_stance = "conditional_bid"

        return {
            "agent_role": request.agent_role.value,
            "target_roles": [role.value for role in target_roles],
            "targeted_disagreements": [
                {
                    "target_role": target_role.value,
                    "disputed_claim": disputed_claim,
                    "rebuttal": (
                        "The cited evidence does not resolve the material "
                        "submission risk."
                    ),
                    "evidence_refs": [tender_ref],
                }
            ],
            "unsupported_claims": [
                {
                    "target_role": target_role.value,
                    "claim": "Named delivery staff are confirmed.",
                    "reason": "No evidence item cites named consultant availability.",
                }
            ],
            "blocker_challenges": [],
            "revised_stance": revised_stance,
            "confidence": 0.68,
            "evidence_refs": [tender_ref],
            "missing_info": ["Named consultant availability remains unproven."],
            "recommended_actions": ["Resolve the staffing evidence gap."],
        }


class InvalidEvidenceRound2Model(RecordingRound2Model):
    def draft_rebuttal(self, request: Round2RebuttalRequest) -> dict[str, Any]:
        payload = super().draft_rebuttal(request)
        if request.agent_role is AgentRole.RED_TEAM:
            # Fully hallucinated ref: both evidence_id AND evidence_key are
            # unknown so the canonicalizer has nothing to rescue. The drop-pass
            # will strip this ref, leaving the rebuttal with zero refs on the
            # targeted_disagreement — which Pydantic will reject because the
            # schema requires min_length=1 on evidence_refs.
            ref = payload["targeted_disagreements"][0]["evidence_refs"][0]
            ref["evidence_id"] = str(UNKNOWN_EVIDENCE_ID)
            ref["evidence_key"] = "TENDER-HALLUCINATED-DOES-NOT-EXIST"
        return payload


class MissingConfidenceRound2Model(RecordingRound2Model):
    def draft_rebuttal(self, request: Round2RebuttalRequest) -> dict[str, Any]:
        payload = super().draft_rebuttal(request)
        payload.pop("confidence", None)
        return payload


class StructuredStringListsRound2Model(RecordingRound2Model):
    def draft_rebuttal(self, request: Round2RebuttalRequest) -> dict[str, Any]:
        payload = super().draft_rebuttal(request)
        payload["missing_info"] = [
            {
                "item": "Explicit confirmation of liability insurance coverage.",
                "priority": "critical",
            },
            {
                "item": "Environmental Management System certificate.",
                "priority": "high",
            },
        ]
        payload["potential_evidence_gaps"] = [
            {
                "gap": "Quality Management System evidence is not attached.",
                "priority": "high",
            }
        ]
        payload["recommended_actions"] = [
            {
                "action": "Ask the bid owner to attach insurance proof.",
                "owner": "bid_owner",
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
            "private_context": "must not reach Round 2 specialists",
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
                confidence=0.94,
                source_metadata={"source_label": "Tender page 1"},
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


def _round_1_motion(
    state: BidRunState,
    role: SpecialistRole,
) -> SpecialistMotionState:
    evidence_ref = state.evidence_board[0]
    common_kwargs = {
        "agent_role": role,
        "confidence": 0.74,
        "evidence_refs": [
            {
                "evidence_key": evidence_ref.evidence_key,
                "source_type": evidence_ref.source_type,
                "evidence_id": evidence_ref.evidence_id,
            }
        ],
        "findings": ["The tender requires ISO 27001 certification."],
        "missing_info": ["Named consultant availability."],
    }
    if role is SpecialistRole.WIN_STRATEGIST:
        return SpecialistMotionState(
            **common_kwargs,
            verdict=Verdict.BID,
            summary="The opportunity is strategically attractive.",
            risks=["Compliance proof appears manageable."],
        )
    if role is SpecialistRole.DELIVERY_CFO:
        return SpecialistMotionState(
            **common_kwargs,
            verdict=Verdict.CONDITIONAL_BID,
            summary="Delivery is feasible if named staff are confirmed.",
            risks=["Staffing evidence is incomplete."],
        )
    if role is SpecialistRole.RED_TEAM:
        return SpecialistMotionState(
            **common_kwargs,
            verdict=Verdict.NO_BID,
            summary="The bid case depends on unresolved staffing and ISO proof.",
            risks=["The tender may reject incomplete proof."],
        )
    return SpecialistMotionState(
        **common_kwargs,
        verdict=Verdict.CONDITIONAL_BID,
        summary="ISO proof must be confirmed before submission.",
        blockers=["Missing ISO certificate validity is a blocker candidate."],
    )


def test_round_2_rebuttals_read_motions_and_persist_audit_rows() -> None:
    model = RecordingRound2Model()
    handlers = replace(
        default_graph_node_handlers(),
        round_1_specialist=_round_1_motion,
        round_2_rebuttal=build_round_2_rebuttal_handler(model),
    )

    result = run_bidded_graph_shell(_ready_state(), handlers=handlers)

    assert result.state.status is AgentRunStatus.SUCCEEDED
    assert GraphRouteNode.ROUND_1_JOIN in result.visited_nodes
    assert GraphRouteNode.ROUND_2_JOIN in result.visited_nodes
    assert {request.agent_role.value for request in model.requests} == {
        role.value for role in SpecialistRole
    }

    request_fields = set(Round2RebuttalRequest.model_fields)
    assert "motions" in request_fields
    assert "evidence_board" in request_fields
    assert "rebuttals" not in request_fields
    assert "run_context" not in request_fields
    assert "private_context" not in request_fields

    expected_motion_roles = {
        AgentRole.COMPLIANCE_OFFICER,
        AgentRole.WIN_STRATEGIST,
        AgentRole.DELIVERY_CFO,
        AgentRole.RED_TEAM,
    }
    assert all(
        set(request.motions) == expected_motion_roles for request in model.requests
    )
    assert all(
        [item.evidence_key for item in request.evidence_board]
        == ["TENDER-SHALL-001", "COMPANY-CERT-001"]
        for request in model.requests
    )

    red_team_request = next(
        request
        for request in model.requests
        if request.agent_role is AgentRole.RED_TEAM
    )
    assert {point.kind for point in red_team_request.focus_points} >= {
        "strongest_bid_argument",
        "conditional_bid_logic",
    }

    assert set(result.state.rebuttals) == set(SpecialistRole)
    rebuttal_rows = [
        output
        for output in result.state.agent_outputs
        if output.round_name == "round_2_rebuttal"
    ]
    assert len(rebuttal_rows) == 4
    assert {row.agent_role for row in rebuttal_rows} == {
        role.value for role in SpecialistRole
    }
    assert all(row.output_type == "rebuttal" for row in rebuttal_rows)
    assert all(row.evidence_refs for row in rebuttal_rows)
    assert all(row.payload["targeted_disagreements"] for row in rebuttal_rows)
    assert all(row.payload["unsupported_claims"] for row in rebuttal_rows)

    red_team_row = next(
        row for row in rebuttal_rows if row.agent_role == AgentRole.RED_TEAM.value
    )
    assert red_team_row.payload["target_roles"] == [
        AgentRole.WIN_STRATEGIST.value,
        AgentRole.DELIVERY_CFO.value,
    ]
    assert red_team_row.payload["revised_stance"] == "no_bid"


def test_invalid_round_2_rebuttal_drops_hallucinated_disagreement() -> None:
    """A Round 2 rebuttal whose targeted_disagreement cites fully hallucinated
    evidence (unresolvable by key OR id) gets that disagreement dropped rather
    than failing the whole run. The rebuttal's other focus points (unsupported
    claims, blocker challenges, missing info) still satisfy the "must focus on
    something" rule, so the run proceeds.
    """
    handlers = replace(
        default_graph_node_handlers(),
        round_1_specialist=_round_1_motion,
        round_2_rebuttal=build_round_2_rebuttal_handler(InvalidEvidenceRound2Model()),
    )

    result = run_bidded_graph_shell(_ready_state(), handlers=handlers)

    assert result.state.status is AgentRunStatus.SUCCEEDED
    assert set(result.state.motions) == set(SpecialistRole)
    # Red Team's rebuttal persists, with the hallucinated disagreement dropped.
    red_team_rebuttal = next(
        output
        for output in result.state.agent_outputs
        if output.round_name == "round_2_rebuttal"
        and output.agent_role == "red_team"
    )
    hallucinated_keys = {
        ref["evidence_key"]
        for d in red_team_rebuttal.payload.get("targeted_disagreements", [])
        for ref in d.get("evidence_refs", [])
    }
    assert "TENDER-HALLUCINATED-DOES-NOT-EXIST" not in hallucinated_keys


def test_round_2_rebuttal_fills_missing_confidence_from_round_1_motion() -> None:
    handlers = replace(
        default_graph_node_handlers(),
        round_1_specialist=_round_1_motion,
        round_2_rebuttal=build_round_2_rebuttal_handler(
            MissingConfidenceRound2Model()
        ),
    )

    result = run_bidded_graph_shell(_ready_state(), handlers=handlers)

    assert result.state.status is AgentRunStatus.SUCCEEDED
    rebuttal_rows = [
        output
        for output in result.state.agent_outputs
        if output.round_name == "round_2_rebuttal"
    ]
    assert len(rebuttal_rows) == 4
    assert {row.payload["confidence"] for row in rebuttal_rows} == {0.74}
    assert all(
        row.validation_errors
        and row.validation_errors[0].field_path == "confidence"
        and "omitted confidence" in row.validation_errors[0].message
        for row in rebuttal_rows
    )


def test_round_2_rebuttal_coerces_structured_string_lists() -> None:
    handlers = replace(
        default_graph_node_handlers(),
        round_1_specialist=_round_1_motion,
        round_2_rebuttal=build_round_2_rebuttal_handler(
            StructuredStringListsRound2Model()
        ),
    )

    result = run_bidded_graph_shell(_ready_state(), handlers=handlers)

    assert result.state.status is AgentRunStatus.SUCCEEDED
    rebuttal_rows = [
        output
        for output in result.state.agent_outputs
        if output.round_name == "round_2_rebuttal"
    ]
    assert len(rebuttal_rows) == 4
    assert all(
        row.payload["missing_info"]
        == [
            "Explicit confirmation of liability insurance coverage. "
            "(priority: critical)",
            "Environmental Management System certificate. (priority: high)",
        ]
        for row in rebuttal_rows
    )
    assert all(
        row.payload["potential_evidence_gaps"]
        == ["Quality Management System evidence is not attached. (priority: high)"]
        for row in rebuttal_rows
    )
    assert all(
        row.payload["recommended_actions"]
        == ["Ask the bid owner to attach insurance proof. (owner: bid_owner)"]
        for row in rebuttal_rows
    )
