"""Smoke tests for production evidence-derived swarm handlers (no LLM)."""

from __future__ import annotations

from uuid import UUID

from bidded.orchestration import (
    AgentRunStatus,
    BidRunState,
    DocumentChunkState,
    EvidenceItemState,
    EvidenceSourceType,
    run_bidded_graph_shell,
)
from bidded.orchestration.evidence_locked_swarm import evidence_locked_graph_handlers

RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
COMPANY_ID = UUID("22222222-2222-4222-8222-222222222222")
TENDER_ID = UUID("33333333-3333-4333-8333-333333333333")
DOCUMENT_ID = UUID("44444444-4444-4444-8444-444444444444")
CHUNK_ID = UUID("55555555-5555-4555-8555-555555555555")
TENDER_EVIDENCE_ID = UUID("66666666-6666-4666-8666-666666666666")
TENDER_EVIDENCE_ID_B = UUID("66666666-6666-4666-8666-666666666667")
COMPANY_EVIDENCE_ID = UUID("77777777-7777-4777-8777-777777777777")
DOCUMENT_ID_B = UUID("44444444-4444-4444-8444-444444444445")
CHUNK_ID_B = UUID("55555555-5555-4555-8555-555555555556")


def _minimal_evidence_state() -> BidRunState:
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
                text=(
                    "The supplier shall provide ISO 27001 certification. "
                    "Submission deadline 2026-06-01."
                ),
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


def test_evidence_locked_swarm_graph_completes() -> None:
    result = run_bidded_graph_shell(
        _minimal_evidence_state(),
        handlers=evidence_locked_graph_handlers(),
    )

    assert result.state.status is AgentRunStatus.SUCCEEDED
    assert result.state.final_decision is not None
    motion_outputs = [
        o
        for o in result.state.agent_outputs
        if o.round_name == "round_1_motion"
    ]
    assert len(motion_outputs) == 4
    assert all(o.payload.get("top_findings") for o in motion_outputs)

    rebuttal_outputs = [
        o
        for o in result.state.agent_outputs
        if o.round_name == "round_2_rebuttal"
    ]
    assert len(rebuttal_outputs) == 4
    by_r1 = {o.agent_role: o.payload["confidence"] for o in motion_outputs}
    by_r2 = {o.agent_role: o.payload["confidence"] for o in rebuttal_outputs}
    for role_key in by_r1:
        assert by_r1[role_key] != by_r2[role_key]

    by_vote = {o.agent_role: o.payload.get("vote") for o in motion_outputs}
    assert by_vote["win_strategist"] == "conditional_bid"
    assert by_vote["red_team"] == "conditional_bid"


def _two_tender_pdf_evidence_state() -> BidRunState:
    """Two tender_document items from different PDFs (document_ids)."""
    base = _minimal_evidence_state()
    second_tender = EvidenceItemState(
        evidence_id=TENDER_EVIDENCE_ID_B,
        evidence_key="TENDER-ANNEX-002",
        source_type=EvidenceSourceType.TENDER_DOCUMENT,
        excerpt="Annex B: pricing shall be submitted in step two of three.",
        normalized_meaning="Pricing step in annex.",
        category="submission_document",
        confidence=0.88,
        source_metadata={"source_label": "Annex B — pricing"},
        document_id=DOCUMENT_ID_B,
        chunk_id=CHUNK_ID_B,
        page_start=2,
        page_end=2,
    )
    extra_chunk = DocumentChunkState(
        chunk_id=CHUNK_ID_B,
        document_id=DOCUMENT_ID_B,
        chunk_index=0,
        page_start=2,
        page_end=2,
        text="Annex B: pricing shall be submitted in step two of three.",
    )
    return base.model_copy(
        update={
            "document_ids": [base.document_ids[0], DOCUMENT_ID_B],
            "chunks": [*base.chunks, extra_chunk],
            "evidence_board": [*base.evidence_board, second_tender],
            "run_context": {
                **base.run_context,
                "document_parse_statuses": {
                    str(base.document_ids[0]): "parsed",
                    str(DOCUMENT_ID_B): "parsed",
                },
            },
        }
    )


def test_round1_rotates_tender_excerpts_across_roles_when_multiple_pdfs() -> None:
    result = run_bidded_graph_shell(
        _two_tender_pdf_evidence_state(),
        handlers=evidence_locked_graph_handlers(),
    )
    assert result.state.status is AgentRunStatus.SUCCEEDED
    motion_outputs = [
        o for o in result.state.agent_outputs if o.round_name == "round_1_motion"
    ]
    claims = {
        o.payload["top_findings"][0]["claim"]
        for o in motion_outputs
        if o.payload.get("top_findings")
    }
    assert len(claims) >= 2

    win = next(
        o for o in motion_outputs if o.agent_role == "win_strategist"
    )
    assert win.payload.get("vote") == "bid"
