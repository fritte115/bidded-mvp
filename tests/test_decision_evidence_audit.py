from __future__ import annotations

from uuid import UUID

from bidded.orchestration.decision_evidence_audit import (
    audit_decision_evidence,
)
from bidded.orchestration.state import (
    BidRunState,
    DocumentChunkState,
    EvidenceItemState,
    EvidenceSourceType,
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


def test_supported_judge_blocker_builds_claim_evidence_graph() -> None:
    audit = audit_decision_evidence(
        _state(),
        _decision_payload(
            compliance_blockers=[
                {
                    "claim": "A confirmed qualification failure blocks submission.",
                    "requirement_type": "qualification_requirement",
                    "evidence_refs": [_tender_ref()],
                }
            ],
        ),
    )

    assert audit.graph.claims[0].claim_type == "compliance_blocker"
    assert audit.graph.claims[0].text == (
        "A confirmed qualification failure blocks submission."
    )
    assert audit.graph.evidence[0].evidence_key == "TENDER-QUALIFICATION-001"
    assert audit.graph.edges[0].claim_id == audit.graph.claims[0].claim_id
    assert audit.graph.edges[0].evidence_key == "TENDER-QUALIFICATION-001"
    assert audit.supported_claim_count == 1
    assert audit.invalid_hard_blocker_count == 0


def test_unsupported_material_claim_is_flagged() -> None:
    audit = audit_decision_evidence(
        _state(),
        _decision_payload(
            potential_blockers=[
                {
                    "claim": "Named delivery staff are confirmed.",
                    "evidence_refs": [],
                }
            ],
        ),
    )

    assert audit.unsupported_claim_count == 1
    assert _finding_kinds(audit) == {"unsupported_claim", "overconfident_decision"}


def test_tender_company_comparison_missing_company_evidence_is_mismatch() -> None:
    audit = audit_decision_evidence(
        _state(),
        _decision_payload(
            compliance_matrix=[
                {
                    "requirement": "ISO 27001 certification",
                    "status": "met",
                    "assessment": "Tender requirement is matched by company proof.",
                    "evidence_refs": [_tender_ref()],
                }
            ],
        ),
    )

    assert audit.source_type_mismatch_count == 1
    assert "source_type_mismatch" in _finding_kinds(audit)
    assert audit.graph.claims[0].required_source_types == (
        EvidenceSourceType.TENDER_DOCUMENT,
        EvidenceSourceType.COMPANY_PROFILE,
    )


def test_formal_blocker_with_wrong_requirement_type_is_rejected_by_audit() -> None:
    audit = audit_decision_evidence(
        _state(),
        _decision_payload(
            compliance_blockers=[
                {
                    "claim": "Missing credit report is treated as a hard blocker.",
                    "requirement_type": "financial_standing",
                    "evidence_refs": [_financial_ref()],
                }
            ],
        ),
    )

    assert audit.gate_verdict == "rejected"
    assert audit.invalid_hard_blocker_count == 1
    assert "invalid_hard_blocker" in _finding_kinds(audit)


def test_tender_source_excerpt_must_be_present_in_loaded_chunk_text() -> None:
    state = _state(chunk_text="This chunk is about a different requirement.")

    audit = audit_decision_evidence(
        state,
        _decision_payload(
            risk_register=[
                {
                    "risk": "Qualification proof may be stale.",
                    "severity": "medium",
                    "mitigation": "Confirm before submission.",
                    "evidence_refs": [_tender_ref()],
                }
            ],
        ),
    )

    assert audit.source_unverified_count == 1
    assert "source_unverified" in _finding_kinds(audit)


def test_high_confidence_low_structural_support_is_flagged() -> None:
    audit = audit_decision_evidence(
        _state(chunk_text="This chunk is about a different requirement."),
        _decision_payload(
            confidence=0.95,
            compliance_matrix=[
                {
                    "requirement": "ISO 27001 certification",
                    "status": "met",
                    "assessment": "Tender requirement is matched by company proof.",
                    "evidence_refs": [_tender_ref()],
                }
            ],
        ),
    )

    assert audit.gate_verdict == "flagged"
    assert audit.overconfident_decision is True
    assert audit.structural_score < audit.judge_confidence


def _state(
    *,
    chunk_text: str = "Supplier must prove ISO 27001 certification for qualification.",
) -> BidRunState:
    return BidRunState(
        run_id=RUN_ID,
        company_id=COMPANY_ID,
        tender_id=TENDER_ID,
        document_ids=[DOCUMENT_ID],
        run_context={"tenant_key": "demo"},
        chunks=[
            DocumentChunkState(
                chunk_id=CHUNK_ID,
                document_id=DOCUMENT_ID,
                chunk_index=0,
                page_start=1,
                page_end=1,
                text=chunk_text,
                metadata={"source_label": "Tender page 1"},
            )
        ],
        evidence_board=[
            EvidenceItemState(
                evidence_id=TENDER_EVIDENCE_ID,
                evidence_key="TENDER-QUALIFICATION-001",
                source_type=EvidenceSourceType.TENDER_DOCUMENT,
                excerpt=(
                    "Supplier must prove ISO 27001 certification for qualification."
                ),
                normalized_meaning="ISO 27001 proof is a qualification requirement.",
                category="qualification_requirement",
                requirement_type=RequirementType.QUALIFICATION_REQUIREMENT,
                confidence=0.92,
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
                normalized_meaning="Company profile cites ISO 27001.",
                category="certification",
                confidence=0.9,
                source_metadata={"source_label": "Company profile"},
                company_id=COMPANY_ID,
                field_path="certifications.iso_27001",
            ),
            EvidenceItemState(
                evidence_id=FINANCIAL_EVIDENCE_ID,
                evidence_key="TENDER-FINANCIAL-001",
                source_type=EvidenceSourceType.TENDER_DOCUMENT,
                excerpt="Supplier must submit a current credit report.",
                normalized_meaning="Financial standing proof is required.",
                category="financial_standing",
                requirement_type=RequirementType.FINANCIAL_STANDING,
                confidence=0.9,
                source_metadata={"source_label": "Tender page 2"},
                document_id=DOCUMENT_ID,
                chunk_id=CHUNK_ID,
                page_start=2,
                page_end=2,
            ),
        ],
    )


def _decision_payload(
    *,
    confidence: float = 0.82,
    compliance_matrix: list[dict[str, object]] | None = None,
    compliance_blockers: list[dict[str, object]] | None = None,
    potential_blockers: list[dict[str, object]] | None = None,
    risk_register: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "verdict": "conditional_bid",
        "confidence": confidence,
        "cited_memo": "The Judge cites the evidence graph.",
        "evidence_refs": [],
        "compliance_matrix": compliance_matrix or [],
        "compliance_blockers": compliance_blockers or [],
        "potential_blockers": potential_blockers or [],
        "risk_register": risk_register or [],
        "missing_info_details": [],
        "recommended_action_details": [],
    }


def _tender_ref() -> dict[str, str]:
    return {
        "evidence_key": "TENDER-QUALIFICATION-001",
        "source_type": "tender_document",
        "evidence_id": str(TENDER_EVIDENCE_ID),
    }


def _financial_ref() -> dict[str, str]:
    return {
        "evidence_key": "TENDER-FINANCIAL-001",
        "source_type": "tender_document",
        "evidence_id": str(FINANCIAL_EVIDENCE_ID),
    }


def _finding_kinds(audit: object) -> set[str]:
    return {finding.kind for finding in audit.findings}
