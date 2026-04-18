"""Coercion of LLM-shaped Evidence Scout JSON into strict schemas."""

from __future__ import annotations

from uuid import UUID

from bidded.orchestration.evidence_scout import validate_evidence_scout_output
from bidded.orchestration.state import EvidenceItemState, EvidenceSourceType

_EID = UUID("66666666-6666-4666-8666-666666666661")
_CHUNK = UUID("55555555-5555-4555-8555-555555555551")
_DOC = UUID("44444444-4444-4444-8444-444444444444")


def _minimal_board() -> tuple[EvidenceItemState, ...]:
    return (
        EvidenceItemState(
            evidence_id=_EID,
            evidence_key="TENDER-DEADLINE-001",
            source_type=EvidenceSourceType.TENDER_DOCUMENT,
            excerpt="Deadline text.",
            normalized_meaning="Meaning.",
            category="deadline",
            confidence=0.9,
            source_metadata={"source_label": "p1"},
            document_id=_DOC,
            chunk_id=_CHUNK,
            page_start=1,
            page_end=1,
        ),
    )


def test_validate_evidence_scout_coerces_title_detail_to_claim() -> None:
    board = _minimal_board()
    raw = {
        "agent_role": "evidence_scout",
        "findings": [
            {
                "category": "deadline",
                "title": "Submission deadline",
                "detail": "Bids close at noon.",
                "evidence_refs": [
                    {
                        "evidence_key": "TENDER-DEADLINE-001",
                        "source_type": "tender_document",
                        "evidence_id": str(_EID),
                    }
                ],
            }
        ],
        "missing_info": [],
        "potential_blockers": [],
    }
    out = validate_evidence_scout_output(raw, evidence_board=board)
    assert len(out.findings) == 1
    assert out.findings[0].claim == "Submission deadline — Bids close at noon."


def test_validate_evidence_scout_preserves_explicit_claim() -> None:
    board = _minimal_board()
    raw = {
        "agent_role": "evidence_scout",
        "findings": [
            {
                "category": "deadline",
                "claim": "Explicit claim only.",
                "title": "ignored",
                "detail": "ignored",
                "evidence_refs": [
                    {
                        "evidence_key": "TENDER-DEADLINE-001",
                        "source_type": "tender_document",
                        "evidence_id": str(_EID),
                    }
                ],
            }
        ],
        "missing_info": [],
        "potential_blockers": [],
    }
    out = validate_evidence_scout_output(raw, evidence_board=board)
    assert out.findings[0].claim == "Explicit claim only."
