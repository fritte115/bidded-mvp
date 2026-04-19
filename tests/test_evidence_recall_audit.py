from __future__ import annotations

from uuid import UUID

from bidded.orchestration import (
    DocumentChunkState,
    EvidenceItemState,
    EvidenceSourceType,
    RequirementType,
)
from bidded.orchestration.evidence_recall import (
    RECALL_AUDIT_REQUIREMENT_TYPES,
    audit_evidence_recall,
)

DOCUMENT_ID = UUID("44444444-4444-4444-8444-444444444444")
CHUNK_ID = UUID("55555555-5555-4555-8555-555555555555")
EVIDENCE_ID = UUID("66666666-6666-4666-8666-666666666666")


def _chunk(text: str) -> DocumentChunkState:
    return DocumentChunkState(
        chunk_id=CHUNK_ID,
        document_id=DOCUMENT_ID,
        chunk_index=0,
        page_start=1,
        page_end=1,
        text=text,
        metadata={"source_label": "Tender page 1"},
    )


def _evidence_item(
    *,
    requirement_type: RequirementType,
    evidence_key: str = "TENDER-SHALL-001",
    excerpt: str = "The supplier shall provide ISO 27001 certification.",
) -> EvidenceItemState:
    return EvidenceItemState(
        evidence_id=EVIDENCE_ID,
        evidence_key=evidence_key,
        source_type=EvidenceSourceType.TENDER_DOCUMENT,
        excerpt=excerpt,
        normalized_meaning=f"Tender states: {excerpt}",
        category=requirement_type.value,
        requirement_type=requirement_type,
        confidence=0.93,
        source_metadata={"source_label": "Tender page 1"},
        document_id=DOCUMENT_ID,
        chunk_id=CHUNK_ID,
        page_start=1,
        page_end=1,
    )


def test_evidence_recall_is_empty_when_important_types_are_covered() -> None:
    chunks = [
        _chunk(
            "Submission must include a signed data processing agreement. "
            "Bidders must provide three comparable public sector references. "
            "Suppliers in bankruptcy are excluded. "
            "Bidders must submit a current credit report. "
            "Supplier shall maintain a quality management system."
        )
    ]
    evidence_board = [
        _evidence_item(
            evidence_key=f"TENDER-{requirement_type.value}",
            requirement_type=requirement_type,
        )
        for requirement_type in RECALL_AUDIT_REQUIREMENT_TYPES
    ]

    assert audit_evidence_recall(chunks=chunks, evidence_board=evidence_board) == ()


def test_evidence_recall_can_flag_all_important_requirement_types() -> None:
    warnings = audit_evidence_recall(
        chunks=[
            _chunk(
                "Submission must include a signed data processing agreement. "
                "Bidders must provide three comparable public sector references. "
                "Suppliers in bankruptcy are excluded. "
                "Bidders must submit a current credit report. "
                "Supplier shall maintain a quality management system."
            )
        ],
        evidence_board=[],
    )

    assert {warning.requirement_type for warning in warnings} == set(
        RECALL_AUDIT_REQUIREMENT_TYPES
    )
    assert all(warning.severity == "warning" for warning in warnings)


def test_evidence_recall_flags_missing_submission_document_coverage() -> None:
    warnings = audit_evidence_recall(
        chunks=[
            _chunk(
                "The supplier shall provide ISO 27001 certification. "
                "Submission must include a signed data processing agreement."
            )
        ],
        evidence_board=[
            _evidence_item(
                requirement_type=RequirementType.QUALIFICATION_REQUIREMENT
            )
        ],
    )

    assert len(warnings) == 1
    warning = warnings[0]
    assert warning.requirement_type is RequirementType.SUBMISSION_DOCUMENT
    assert warning.severity == "warning"
    assert warning.document_id == DOCUMENT_ID
    assert warning.chunk_id == CHUNK_ID
    assert warning.page_start == 1
    assert warning.page_end == 1
    assert warning.source_label == "Tender page 1"
    assert warning.evidence_state == "missing_from_evidence_board"
    assert "submission_document" in warning.missing_info


def test_evidence_recall_flags_missing_financial_standing_coverage() -> None:
    warnings = audit_evidence_recall(
        chunks=[_chunk("Bidders must submit a current credit report.")],
        evidence_board=[
            _evidence_item(
                requirement_type=RequirementType.QUALIFICATION_REQUIREMENT
            )
        ],
    )

    assert [warning.requirement_type for warning in warnings] == [
        RequirementType.FINANCIAL_STANDING
    ]
    assert "credit report" in warnings[0].matched_text


def test_evidence_recall_flags_glossary_signal_mismatch() -> None:
    warnings = audit_evidence_recall(
        chunks=[_chunk("Supplier shall maintain SOSFS 2011:9 quality management.")],
        evidence_board=[
            _evidence_item(
                requirement_type=RequirementType.QUALIFICATION_REQUIREMENT,
                excerpt="Supplier shall maintain SOSFS 2011:9 quality management.",
            )
        ],
    )

    assert [warning.requirement_type for warning in warnings] == [
        RequirementType.QUALITY_MANAGEMENT
    ]
    assert warnings[0].glossary_ids == ("quality_management_sosfs",)
