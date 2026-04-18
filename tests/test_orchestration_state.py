from __future__ import annotations

from uuid import UUID

import pytest

from bidded.orchestration import (
    AgentOutputState,
    AgentRunStatus,
    BidRunState,
    DocumentChunkState,
    EvidenceItemState,
    EvidenceRef,
    EvidenceSourceType,
    FinalDecisionState,
    GraphNodeName,
    RebuttalState,
    ScoutFindingState,
    ScoutOutputState,
    SpecialistMotionState,
    SpecialistRole,
    StateOwnershipError,
    ValidationIssueState,
    Verdict,
)

RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
COMPANY_ID = UUID("22222222-2222-4222-8222-222222222222")
TENDER_ID = UUID("33333333-3333-4333-8333-333333333333")
DOCUMENT_ID = UUID("44444444-4444-4444-8444-444444444444")
CHUNK_ID = UUID("55555555-5555-4555-8555-555555555555")
EVIDENCE_ID = UUID("66666666-6666-4666-8666-666666666666")
SECOND_EVIDENCE_ID = UUID("77777777-7777-4777-8777-777777777777")


def _evidence_ref() -> EvidenceRef:
    return EvidenceRef(
        evidence_id=EVIDENCE_ID,
        evidence_key="TENDER-REQ-001",
        source_type=EvidenceSourceType.TENDER_DOCUMENT,
    )


def _evidence_item(
    evidence_key: str = "TENDER-REQ-001",
    evidence_id: UUID = EVIDENCE_ID,
    excerpt: str = "The supplier must provide ISO 27001 certification.",
) -> EvidenceItemState:
    return EvidenceItemState(
        evidence_id=evidence_id,
        evidence_key=evidence_key,
        source_type=EvidenceSourceType.TENDER_DOCUMENT,
        excerpt=excerpt,
        normalized_meaning="ISO 27001 certification is mandatory.",
        category="shall_requirement",
        confidence=0.94,
        source_metadata={"source_label": "Tender page 1"},
        document_id=DOCUMENT_ID,
        chunk_id=CHUNK_ID,
        page_start=1,
        page_end=1,
    )


def _motion(
    role: SpecialistRole,
    verdict: Verdict = Verdict.CONDITIONAL_BID,
) -> SpecialistMotionState:
    return SpecialistMotionState(
        agent_role=role,
        verdict=verdict,
        confidence=0.71,
        summary=f"{role.value} summary.",
        evidence_refs=[_evidence_ref()],
        findings=["Tender requires ISO 27001."],
    )


def _rebuttal(role: SpecialistRole, target: SpecialistRole) -> RebuttalState:
    return RebuttalState(
        agent_role=role,
        target_motion_role=target,
        summary=f"{role.value} rebuttal.",
        challenged_claims=["Delivery capacity is proven."],
        evidence_refs=[_evidence_ref()],
    )


def _final_decision(verdict: Verdict = Verdict.CONDITIONAL_BID) -> FinalDecisionState:
    return FinalDecisionState(
        verdict=verdict,
        confidence=0.72,
        rationale="The opportunity is defensible with explicit follow-up actions.",
        vote_summary={"conditional_bid": 3, "no_bid": 1},
        cited_memo="Proceed only after certificate validity is confirmed.",
        evidence_ids=[EVIDENCE_ID],
        evidence_refs=[_evidence_ref()],
    )


def _agent_output(output_type: str = "motion") -> AgentOutputState:
    return AgentOutputState(
        agent_role=SpecialistRole.COMPLIANCE.value,
        round_name="round_1",
        output_type=output_type,
        payload={"summary": "Validated output payload."},
        evidence_refs=[_evidence_ref()],
    )


def test_empty_bid_run_state_round_trips_and_classifies_fields() -> None:
    state = BidRunState(
        run_id=RUN_ID,
        company_id=COMPANY_ID,
        tender_id=TENDER_ID,
        document_ids=[],
    )

    assert state.status is AgentRunStatus.PENDING
    assert state.run_context == {}
    assert state.chunks == []
    assert state.evidence_board == []
    assert state.scout_output is None
    assert state.motions == {}
    assert state.rebuttals == {}
    assert state.validation_errors == []
    assert state.agent_outputs == []
    assert state.retry_counts == {}
    assert state.final_decision is None

    assert {status.value for status in AgentRunStatus} == {
        "pending",
        "running",
        "succeeded",
        "failed",
        "needs_human_review",
    }
    assert BidRunState.runtime_control_fields() == frozenset(
        {
            "status",
            "current_step",
            "retry_counts",
            "last_error",
            "working_retrieval_results",
        }
    )
    assert BidRunState.persisted_audit_fields() == frozenset(
        {
            "evidence_board",
            "scout_output",
            "motions",
            "rebuttals",
            "validation_errors",
            "agent_outputs",
            "final_decision",
        }
    )
    assert BidRunState.runtime_control_fields().isdisjoint(
        BidRunState.persisted_audit_fields()
    )

    payload = state.model_dump(mode="json")
    assert payload["run_id"] == str(RUN_ID)
    assert payload["status"] == "pending"
    assert BidRunState.model_validate(payload) == state


def test_graph_node_contracts_document_reads_and_owned_writes() -> None:
    contracts = BidRunState.node_contracts()

    assert set(contracts) == set(GraphNodeName)
    for contract in contracts.values():
        assert contract.read_fields
        assert contract.owned_write_fields
        assert contract.read_fields <= BidRunState.known_fields()
        assert contract.owned_write_fields <= BidRunState.known_fields()

    round_1_contract = contracts[GraphNodeName.ROUND_1_SPECIALIST]
    assert "evidence_board" in round_1_contract.read_fields
    assert "motions" in round_1_contract.owned_write_fields
    assert "final_decision" not in round_1_contract.owned_write_fields

    judge_contract = contracts[GraphNodeName.JUDGE]
    assert "motions" in judge_contract.read_fields
    assert "rebuttals" in judge_contract.read_fields
    assert "final_decision" in judge_contract.owned_write_fields


def test_node_update_rejects_writes_outside_owned_fields() -> None:
    state = BidRunState(
        run_id=RUN_ID,
        company_id=COMPANY_ID,
        tender_id=TENDER_ID,
        document_ids=[DOCUMENT_ID],
    )

    with pytest.raises(StateOwnershipError, match="does not own"):
        state.apply_node_update(
            GraphNodeName.ROUND_1_SPECIALIST,
            {"final_decision": _final_decision()},
        )


def test_append_only_artifacts_are_extended_not_replaced() -> None:
    initial_evidence = _evidence_item()
    new_evidence = _evidence_item(
        evidence_key="TENDER-REQ-002",
        evidence_id=SECOND_EVIDENCE_ID,
        excerpt="The supplier must submit a project plan.",
    )
    validation_issue = ValidationIssueState(
        source="evidence_scout",
        message="A requirement could not be linked to company evidence.",
    )
    state = BidRunState(
        run_id=RUN_ID,
        company_id=COMPANY_ID,
        tender_id=TENDER_ID,
        document_ids=[DOCUMENT_ID],
        evidence_board=[initial_evidence],
        validation_errors=[validation_issue],
        agent_outputs=[_agent_output("scout")],
    )

    updated = state.apply_node_update(
        GraphNodeName.EVIDENCE_SCOUT,
        {
            "evidence_board": [new_evidence],
            "validation_errors": [
                ValidationIssueState(
                    source="evidence_scout",
                    message="Company certificate expiry date is missing.",
                )
            ],
            "agent_outputs": [_agent_output("scout_retry")],
        },
    )

    assert [item.evidence_key for item in updated.evidence_board] == [
        "TENDER-REQ-001",
        "TENDER-REQ-002",
    ]
    assert [issue.message for issue in updated.validation_errors] == [
        "A requirement could not be linked to company evidence.",
        "Company certificate expiry date is missing.",
    ]
    assert [output.output_type for output in updated.agent_outputs] == [
        "scout",
        "scout_retry",
    ]


def test_write_once_artifacts_cannot_be_overwritten() -> None:
    state = BidRunState(
        run_id=RUN_ID,
        company_id=COMPANY_ID,
        tender_id=TENDER_ID,
        document_ids=[DOCUMENT_ID],
    )

    decided = state.apply_node_update(
        GraphNodeName.JUDGE,
        {"final_decision": _final_decision()},
    )

    with pytest.raises(StateOwnershipError, match="final_decision"):
        decided.apply_node_update(
            GraphNodeName.JUDGE,
            {"final_decision": _final_decision(Verdict.NO_BID)},
        )


def test_runtime_control_fields_can_be_overwritten() -> None:
    state = BidRunState(
        run_id=RUN_ID,
        company_id=COMPANY_ID,
        tender_id=TENDER_ID,
        document_ids=[DOCUMENT_ID],
        status=AgentRunStatus.PENDING,
        current_step="queued",
        retry_counts={"preflight": 1},
    )

    running = state.apply_node_update(
        GraphNodeName.PREFLIGHT,
        {
            "status": AgentRunStatus.RUNNING,
            "current_step": "preflight",
            "retry_counts": {"preflight": 2},
            "working_retrieval_results": [_evidence_ref()],
        },
    )
    failed = running.apply_node_update(
        GraphNodeName.PREFLIGHT,
        {
            "status": AgentRunStatus.FAILED,
            "current_step": "failed",
            "retry_counts": {"preflight": 3},
            "working_retrieval_results": [],
        },
    )

    assert failed.status is AgentRunStatus.FAILED
    assert failed.current_step == "failed"
    assert failed.retry_counts == {"preflight": 3}
    assert failed.working_retrieval_results == []


def test_role_keyed_reducers_merge_parallel_specialist_outputs() -> None:
    state = BidRunState(
        run_id=RUN_ID,
        company_id=COMPANY_ID,
        tender_id=TENDER_ID,
        document_ids=[DOCUMENT_ID],
    )

    with_compliance = state.apply_node_update(
        GraphNodeName.ROUND_1_SPECIALIST,
        {"motions": {SpecialistRole.COMPLIANCE: _motion(SpecialistRole.COMPLIANCE)}},
    )
    with_red_team = with_compliance.apply_node_update(
        GraphNodeName.ROUND_1_SPECIALIST,
        {"motions": {SpecialistRole.RED_TEAM: _motion(SpecialistRole.RED_TEAM)}},
    )

    assert set(with_red_team.motions) == {
        SpecialistRole.COMPLIANCE,
        SpecialistRole.RED_TEAM,
    }

    with pytest.raises(StateOwnershipError, match="already has motions"):
        with_red_team.apply_node_update(
            GraphNodeName.ROUND_1_SPECIALIST,
            {
                "motions": {
                    SpecialistRole.COMPLIANCE: _motion(
                        SpecialistRole.COMPLIANCE,
                        Verdict.BID,
                    )
                }
            },
        )

    with_rebuttal = with_red_team.apply_node_update(
        GraphNodeName.ROUND_2_REBUTTAL,
        {
            "rebuttals": {
                SpecialistRole.COMPLIANCE: _rebuttal(
                    SpecialistRole.COMPLIANCE,
                    SpecialistRole.RED_TEAM,
                )
            }
        },
    )
    with_second_rebuttal = with_rebuttal.apply_node_update(
        GraphNodeName.ROUND_2_REBUTTAL,
        {
            "rebuttals": {
                SpecialistRole.RED_TEAM: _rebuttal(
                    SpecialistRole.RED_TEAM,
                    SpecialistRole.WIN_STRATEGIST,
                )
            }
        },
    )

    assert set(with_second_rebuttal.rebuttals) == {
        SpecialistRole.COMPLIANCE,
        SpecialistRole.RED_TEAM,
    }

    with pytest.raises(StateOwnershipError, match="already has rebuttals"):
        with_second_rebuttal.apply_node_update(
            GraphNodeName.ROUND_2_REBUTTAL,
            {
                "rebuttals": {
                    SpecialistRole.RED_TEAM: _rebuttal(
                        SpecialistRole.RED_TEAM,
                        SpecialistRole.COMPLIANCE,
                    )
                }
            },
        )


def test_bid_run_state_round_trips_with_evidence_and_motions() -> None:
    state = BidRunState(
        run_id=RUN_ID,
        company_id=COMPANY_ID,
        tender_id=TENDER_ID,
        document_ids=[DOCUMENT_ID],
        status=AgentRunStatus.RUNNING,
        current_step="round_1",
        run_context={
            "tenant_key": "demo",
            "language_policy": {"output_language": "en"},
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
        scout_output=ScoutOutputState(
            findings=[
                ScoutFindingState(
                    category="shall_requirement",
                    claim="ISO 27001 certification is mandatory.",
                    evidence_refs=[_evidence_ref()],
                )
            ],
            missing_info=["Submission deadline is not yet extracted."],
        ),
        motions={
            SpecialistRole.COMPLIANCE: SpecialistMotionState(
                agent_role=SpecialistRole.COMPLIANCE,
                verdict=Verdict.CONDITIONAL_BID,
                confidence=0.71,
                summary="Certification looks addressable, pending proof.",
                evidence_refs=[_evidence_ref()],
                findings=["Tender requires ISO 27001."],
                assumptions=[
                    "The seeded company profile includes a valid certificate."
                ],
                missing_info=["Certificate expiry date."],
                recommended_actions=["Confirm certificate validity."],
            )
        },
        retry_counts={"compliance_officer": 1},
    )

    restored = BidRunState.model_validate_json(state.model_dump_json())

    assert restored == state
    assert restored.evidence_board[0].source_metadata["source_label"] == (
        "Tender page 1"
    )
    assert list(restored.motions) == [SpecialistRole.COMPLIANCE]
    assert restored.motions[SpecialistRole.COMPLIANCE].verdict is (
        Verdict.CONDITIONAL_BID
    )


def test_bid_run_state_round_trips_with_final_decision_state() -> None:
    state = BidRunState(
        run_id=RUN_ID,
        company_id=COMPANY_ID,
        tender_id=TENDER_ID,
        document_ids=[DOCUMENT_ID],
        status=AgentRunStatus.NEEDS_HUMAN_REVIEW,
        rebuttals={
            SpecialistRole.RED_TEAM: RebuttalState(
                agent_role=SpecialistRole.RED_TEAM,
                target_motion_role=SpecialistRole.WIN_STRATEGIST,
                summary="The win argument depends on unresolved staffing evidence.",
                challenged_claims=["Delivery capacity is proven."],
                accepted_claims=["The tender is strategically relevant."],
                evidence_refs=[_evidence_ref()],
            )
        },
        validation_errors=[
            ValidationIssueState(
                source="judge",
                message="Critical staffing evidence is missing.",
                field_path="final_decision.missing_info",
            )
        ],
        final_decision=FinalDecisionState(
            verdict=Verdict.NEEDS_HUMAN_REVIEW,
            confidence=0.42,
            rationale="A defensible bid verdict needs staffing confirmation.",
            vote_summary={"conditional_bid": 2, "no_bid": 1, "needs_human_review": 1},
            compliance_blockers=[],
            potential_blockers=["Unconfirmed named staffing availability."],
            risk_register=["Delivery timeline may be under-resourced."],
            missing_info=["Named consultant availability."],
            recommended_actions=["Ask delivery lead to confirm staffing."],
            cited_memo="Proceed only after staffing evidence is added.",
            evidence_ids=[EVIDENCE_ID],
            evidence_refs=[_evidence_ref()],
        ),
    )

    payload = state.model_dump(mode="json")

    assert payload["status"] == "needs_human_review"
    assert payload["final_decision"]["verdict"] == "needs_human_review"
    assert payload["final_decision"]["evidence_ids"] == [str(EVIDENCE_ID)]
    assert BidRunState.model_validate(payload) == state
