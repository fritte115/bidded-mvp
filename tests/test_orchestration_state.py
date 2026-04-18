from __future__ import annotations

from uuid import UUID

from bidded.orchestration import (
    AgentRunStatus,
    BidRunState,
    DocumentChunkState,
    EvidenceItemState,
    EvidenceRef,
    EvidenceSourceType,
    FinalDecisionState,
    RebuttalState,
    ScoutFindingState,
    ScoutOutputState,
    SpecialistMotionState,
    SpecialistRole,
    ValidationIssueState,
    Verdict,
)

RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
COMPANY_ID = UUID("22222222-2222-4222-8222-222222222222")
TENDER_ID = UUID("33333333-3333-4333-8333-333333333333")
DOCUMENT_ID = UUID("44444444-4444-4444-8444-444444444444")
CHUNK_ID = UUID("55555555-5555-4555-8555-555555555555")
EVIDENCE_ID = UUID("66666666-6666-4666-8666-666666666666")


def _evidence_ref() -> EvidenceRef:
    return EvidenceRef(
        evidence_id=EVIDENCE_ID,
        evidence_key="TENDER-REQ-001",
        source_type=EvidenceSourceType.TENDER_DOCUMENT,
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
