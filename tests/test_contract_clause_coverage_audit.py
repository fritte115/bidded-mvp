from __future__ import annotations

from uuid import UUID

from bidded.agents import AgentRole
from bidded.evidence.tender_document import (
    build_tender_evidence_candidates,
    build_tender_evidence_items,
)
from bidded.orchestration import (
    BidRunState,
    DocumentChunkState,
    EvidenceItemState,
    EvidenceSourceType,
    RebuttalState,
    ScoutOutputState,
    SpecialistMotionState,
    SpecialistRole,
    Verdict,
)
from bidded.orchestration.contract_clause_audit import (
    audit_contract_clause_coverage,
)
from bidded.orchestration.evidence_scout import build_evidence_scout_request
from bidded.orchestration.judge import build_judge_decision_request
from bidded.orchestration.specialist_motions import (
    build_round_1_specialist_request,
)
from bidded.requirements import RequirementType
from bidded.retrieval import RetrievedDocumentChunk

RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
COMPANY_ID = UUID("22222222-2222-4222-8222-222222222222")
TENDER_ID = UUID("33333333-3333-4333-8333-333333333333")
DOCUMENT_ID = UUID("44444444-4444-4444-8444-444444444444")
CHUNK_ID = UUID("55555555-5555-4555-8555-555555555555")
EVIDENCE_ID = UUID("66666666-6666-4666-8666-666666666666")


def _chunk(
    text: str,
    *,
    chunk_id: UUID = CHUNK_ID,
    page_start: int = 1,
    chunk_index: int = 0,
) -> DocumentChunkState:
    return DocumentChunkState(
        chunk_id=chunk_id,
        document_id=DOCUMENT_ID,
        chunk_index=chunk_index,
        page_start=page_start,
        page_end=page_start,
        text=text,
        metadata={"source_label": f"Tender page {page_start}"},
    )


def _retrieved_chunk(text: str) -> RetrievedDocumentChunk:
    return RetrievedDocumentChunk(
        chunk_id=str(CHUNK_ID),
        document_id=DOCUMENT_ID,
        chunk_index=0,
        page_start=1,
        page_end=1,
        text=text,
        metadata={"source_label": "Tender page 1"},
    )


def _evidence_item(
    *,
    evidence_key: str = "TENDER-REQ-001",
    evidence_id: UUID = EVIDENCE_ID,
    excerpt: str = "Supplier shall provide ISO 27001 certification.",
    requirement_type: RequirementType | None = RequirementType.SHALL_REQUIREMENT,
    metadata: dict[str, object] | None = None,
) -> EvidenceItemState:
    return EvidenceItemState(
        evidence_id=evidence_id,
        evidence_key=evidence_key,
        source_type=EvidenceSourceType.TENDER_DOCUMENT,
        excerpt=excerpt,
        normalized_meaning=f"Tender states: {excerpt}",
        category=(
            requirement_type.value
            if requirement_type is not None
            else "contract_obligation"
        ),
        requirement_type=requirement_type,
        confidence=0.91,
        source_metadata={"source_label": "Tender page 1"},
        document_id=DOCUMENT_ID,
        chunk_id=CHUNK_ID,
        page_start=1,
        page_end=1,
        metadata=dict(metadata or {}),
    )


def _state(
    *,
    chunks: list[DocumentChunkState],
    evidence_board: list[EvidenceItemState] | None = None,
) -> BidRunState:
    return BidRunState(
        run_id=RUN_ID,
        company_id=COMPANY_ID,
        tender_id=TENDER_ID,
        document_ids=[DOCUMENT_ID],
        chunks=chunks,
        evidence_board=evidence_board or [_evidence_item()],
    )


def test_contract_clause_audit_flags_heading_with_missing_body_text() -> None:
    warnings = audit_contract_clause_coverage(
        chunks=[
            _chunk(
                "5. Insurance\n"
                "6. Confidentiality\n"
                "Supplier shall protect confidential information."
            )
        ],
        evidence_board=[
            _evidence_item(
                excerpt="Supplier shall protect confidential information.",
                metadata={"contract_clause_ids": ["confidentiality"]},
            )
        ],
    )

    insurance_warnings = [
        warning for warning in warnings if warning.contract_clause_id == "insurance"
    ]
    assert len(insurance_warnings) == 1
    assert insurance_warnings[0].severity == "warning"
    assert insurance_warnings[0].evidence_state == "missing_clause_body"
    assert insurance_warnings[0].heading == "Insurance"
    assert "Insurance" in insurance_warnings[0].missing_info


def test_contract_clause_audit_flags_known_signals_without_evidence_tags() -> None:
    warnings = audit_contract_clause_coverage(
        chunks=[
            _chunk(
                "The contract covers insurance, confidentiality, GDPR data "
                "processing agreement, subcontractors, penalties, liability cap, "
                "gross negligence, public access, termination, and monthly report."
            )
        ],
        evidence_board=[],
    )

    missing_tag_ids = {
        warning.contract_clause_id
        for warning in warnings
        if warning.evidence_state == "missing_from_evidence_board"
    }
    assert missing_tag_ids >= {
        "insurance",
        "confidentiality",
        "gdpr_dpa",
        "subcontractors",
        "penalties_liquidated_damages",
        "liability_caps",
        "gross_negligence_wilful_misconduct",
        "public_access",
        "termination",
        "reporting",
    }
    assert all(warning.severity == "warning" for warning in warnings)


def test_contract_clause_audit_flags_missing_expected_extracted_terms() -> None:
    warnings = audit_contract_clause_coverage(
        chunks=[
            _chunk(
                "Penalties apply for missed milestones. "
                "Supplier liability cap applies to direct damages. "
                "Payment follows approved invoice."
            )
        ],
        evidence_board=[
            _evidence_item(
                evidence_key="TENDER-PENALTY-001",
                excerpt="Penalties apply for missed milestones.",
                requirement_type=RequirementType.CONTRACT_OBLIGATION,
                metadata={"contract_clause_ids": ["penalties_liquidated_damages"]},
            ),
            _evidence_item(
                evidence_key="TENDER-LIABILITY-001",
                evidence_id=UUID("66666666-6666-4666-8666-666666666667"),
                excerpt="Supplier liability cap applies to direct damages.",
                requirement_type=RequirementType.CONTRACT_OBLIGATION,
                metadata={"contract_clause_ids": ["liability_caps"]},
            ),
            _evidence_item(
                evidence_key="TENDER-PAYMENT-001",
                evidence_id=UUID("66666666-6666-4666-8666-666666666668"),
                excerpt="Payment follows approved invoice.",
                requirement_type=RequirementType.CONTRACT_OBLIGATION,
            ),
        ],
    )

    term_warnings = {
        warning.evidence_key: warning
        for warning in warnings
        if warning.evidence_state == "missing_expected_terms"
    }
    assert term_warnings["TENDER-PENALTY-001"].missing_terms == (
        "penalty_amount",
        "recurrence",
    )
    assert term_warnings["TENDER-LIABILITY-001"].missing_terms == (
        "liability_cap",
        "recurrence",
    )
    assert term_warnings["TENDER-PAYMENT-001"].missing_terms == ("payment_deadline",)


def test_contract_clause_audit_handles_provided_swedish_contract_snippet() -> None:
    snippet = (
        "7. Vite\n"
        "Leverantören ska betala vite vid försening.\n\n"
        "8. Ansvarsbegränsning\n"
        "Leverantörens ansvar är begränsat till direkta skador.\n\n"
        "9. Betalning\n"
        "Faktura betalas efter godkänd leverans."
    )
    evidence_rows = build_tender_evidence_items(
        build_tender_evidence_candidates([_retrieved_chunk(snippet)])
    )

    warnings = audit_contract_clause_coverage(
        chunks=[_chunk(snippet)],
        evidence_board=[
            _evidence_item(
                evidence_key=str(row["evidence_key"]),
                excerpt=str(row["excerpt"]),
                requirement_type=RequirementType(row["requirement_type"]),
                metadata=dict(row["metadata"]),
            )
            for row in evidence_rows
        ],
    )

    missing_term_names = {
        missing_term
        for warning in warnings
        if warning.evidence_state == "missing_expected_terms"
        for missing_term in warning.missing_terms
    }
    assert {
        "penalty_amount",
        "liability_cap",
        "recurrence",
        "payment_deadline",
    } <= missing_term_names


def test_clause_audit_warnings_flow_to_agent_requests_without_hard_gate() -> None:
    state = _state(
        chunks=[
            _chunk("Public access rules may require disclosure of supplier material.")
        ]
    )

    scout_request = build_evidence_scout_request(state, top_k_per_category=1)
    round_1_state = state.model_copy(update={"scout_output": ScoutOutputState()})
    round_1_requests = [
        build_round_1_specialist_request(round_1_state, role) for role in SpecialistRole
    ]
    judge_request = build_judge_decision_request(_judge_ready_state(round_1_state))

    assert [
        warning.contract_clause_id
        for warning in scout_request.contract_clause_audit_warnings
    ] == ["public_access"]
    assert {
        request.agent_role
        for request in round_1_requests
        if request.contract_clause_audit_warnings
    } == {
        AgentRole.COMPLIANCE_OFFICER,
        AgentRole.WIN_STRATEGIST,
        AgentRole.DELIVERY_CFO,
        AgentRole.RED_TEAM,
    }
    assert [
        warning.contract_clause_id
        for warning in judge_request.contract_clause_audit_warnings
    ] == ["public_access"]
    assert judge_request.formal_compliance_blockers == ()


def _judge_ready_state(state: BidRunState) -> BidRunState:
    return state.model_copy(
        update={
            "motions": {role: _motion(role) for role in SpecialistRole},
            "rebuttals": {role: _rebuttal(role) for role in SpecialistRole},
        }
    )


def _motion(role: SpecialistRole) -> SpecialistMotionState:
    return SpecialistMotionState(
        agent_role=role,
        verdict=Verdict.BID,
        confidence=0.82,
        summary=f"{role.value} supports a bid.",
        findings=["Baseline evidence is present."],
    )


def _rebuttal(role: SpecialistRole) -> RebuttalState:
    target_role = (
        SpecialistRole.COMPLIANCE
        if role is not SpecialistRole.COMPLIANCE
        else SpecialistRole.RED_TEAM
    )
    return RebuttalState(
        agent_role=role,
        target_motion_role=target_role,
        summary=f"{role.value} has no blocking rebuttal.",
    )
