from __future__ import annotations

from typing import Any
from uuid import UUID

from bidded.orchestration.fit_gap import (
    FitGapMatchStatus,
    build_requirement_fit_gap_board,
    ensure_requirement_fit_gaps_for_run,
    list_requirement_fit_gaps_for_run,
)
from bidded.orchestration.state import (
    BidRunState,
    EvidenceItemState,
    EvidenceSourceType,
    RequirementType,
)

RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
COMPANY_ID = UUID("22222222-2222-4222-8222-222222222222")
TENDER_ID = UUID("33333333-3333-4333-8333-333333333333")
DOCUMENT_ID = UUID("44444444-4444-4444-8444-444444444444")
CHUNK_ID = UUID("55555555-5555-4555-8555-555555555555")
TENDER_EVIDENCE_ID = UUID("66666666-6666-4666-8666-666666666666")
COMPANY_EVIDENCE_ID = UUID("77777777-7777-4777-8777-777777777777")


class RecordingFitGapQuery:
    def __init__(self, client: RecordingFitGapClient, table_name: str) -> None:
        self.client = client
        self.table_name = table_name
        self.filters: list[tuple[str, str]] = []
        self.insert_payload: Any | None = None

    def select(self, _columns: str) -> RecordingFitGapQuery:
        return self

    def eq(self, column: str, value: object) -> RecordingFitGapQuery:
        self.filters.append((column, str(value)))
        return self

    def insert(self, payload: Any) -> RecordingFitGapQuery:
        self.insert_payload = payload
        return self

    def execute(self) -> object:
        if self.insert_payload is not None:
            rows = (
                self.insert_payload
                if isinstance(self.insert_payload, list)
                else [self.insert_payload]
            )
            self.client.inserts.setdefault(self.table_name, []).append(rows)
            self.client.rows.setdefault(self.table_name, []).extend(
                dict(row) for row in rows
            )
            return type("Response", (), {"data": rows})()

        rows = [
            row
            for row in self.client.rows.get(self.table_name, [])
            if all(str(row.get(column)) == value for column, value in self.filters)
        ]
        return type("Response", (), {"data": rows})()


class RecordingFitGapClient:
    def __init__(self) -> None:
        self.rows: dict[str, list[dict[str, Any]]] = {"requirement_fit_gaps": []}
        self.inserts: dict[str, list[list[dict[str, Any]]]] = {}

    def table(self, table_name: str) -> RecordingFitGapQuery:
        return RecordingFitGapQuery(self, table_name)


def test_fit_gap_exact_certification_match() -> None:
    state = _state(
        tender=[
            _tender_evidence(
                excerpt="Supplier must hold active ISO 27001 certification.",
                requirement_type=RequirementType.QUALIFICATION_REQUIREMENT,
            )
        ],
        company=[
            _company_evidence(
                evidence_key="COMPANY-ISO-27001",
                excerpt="ISO 27001: information security management; status active.",
                category="certification",
                field_path="certifications[0]",
            )
        ],
    )

    board = build_requirement_fit_gap_board(state)

    assert len(board) == 1
    assert board[0].match_status is FitGapMatchStatus.MATCHED
    assert board[0].risk_level == "low"
    assert board[0].company_evidence_refs[0].evidence_key == "COMPANY-ISO-27001"
    assert board[0].recommended_actions == ()


def test_fit_gap_partial_reference_count_match() -> None:
    state = _state(
        tender=[
            _tender_evidence(
                excerpt=(
                    "Supplier must provide three comparable public sector references."
                ),
                requirement_type=RequirementType.QUALIFICATION_REQUIREMENT,
            )
        ],
        company=[
            _company_evidence(
                evidence_key="COMPANY-REFERENCE-001",
                excerpt="One public sector reference for a municipal digital service.",
                category="reference",
                field_path="reference_projects[0]",
            )
        ],
    )

    item = build_requirement_fit_gap_board(state)[0]

    assert item.match_status is FitGapMatchStatus.PARTIAL_MATCH
    assert item.risk_level == "medium"
    assert "Additional proof is needed" in item.missing_info[0]
    assert "Attach supporting company evidence" in item.recommended_actions[0]


def test_fit_gap_missing_company_evidence_for_thin_kb() -> None:
    state = _state(
        tender=[
            _tender_evidence(
                excerpt="Submission must include a named security-cleared lead CV.",
                requirement_type=RequirementType.SUBMISSION_DOCUMENT,
            )
        ],
        company=[],
    )

    item = build_requirement_fit_gap_board(state)[0]

    assert item.match_status is FitGapMatchStatus.MISSING_COMPANY_EVIDENCE
    assert item.company_evidence_refs == ()
    assert item.risk_level == "high"
    assert "No company evidence" in item.missing_info[0]


def test_fit_gap_conflicting_and_stale_company_evidence() -> None:
    conflict_state = _state(
        tender=[
            _tender_evidence(
                excerpt="Supplier must hold active ISO 9001 certification.",
                requirement_type=RequirementType.QUALITY_MANAGEMENT,
            )
        ],
        company=[
            _company_evidence(
                evidence_key="COMPANY-ISO-9001-EXPIRED",
                excerpt="ISO 9001 certificate expired and is not active.",
                category="certification",
                field_path="certifications[0]",
            )
        ],
    )
    stale_state = _state(
        tender=[
            _tender_evidence(
                excerpt="Supplier must show current financial standing.",
                requirement_type=RequirementType.FINANCIAL_STANDING,
            )
        ],
        company=[
            _company_evidence(
                evidence_key="COMPANY-FINANCIAL-2023",
                excerpt="Financial statement year 2023 revenue was 18 MSEK.",
                category="economics",
                field_path="financials[2023]",
                metadata={"valid_until": "2024-12-31"},
            )
        ],
    )

    assert build_requirement_fit_gap_board(conflict_state)[0].match_status is (
        FitGapMatchStatus.CONFLICTING_EVIDENCE
    )
    assert build_requirement_fit_gap_board(stale_state)[0].match_status is (
        FitGapMatchStatus.STALE_EVIDENCE
    )


def test_ensure_fit_gaps_inserts_once_and_loads_existing_rows() -> None:
    client = RecordingFitGapClient()
    state = _state(
        tender=[
            _tender_evidence(
                excerpt="Supplier must hold active ISO 27001 certification.",
                requirement_type=RequirementType.QUALIFICATION_REQUIREMENT,
            )
        ],
        company=[
            _company_evidence(
                excerpt="ISO 27001: information security management; status active.",
            )
        ],
    )

    first = ensure_requirement_fit_gaps_for_run(client, state)
    second = ensure_requirement_fit_gaps_for_run(client, state)

    assert len(first) == 1
    assert second == first
    assert len(client.inserts["requirement_fit_gaps"]) == 1
    listed = list_requirement_fit_gaps_for_run(client, run_id=RUN_ID)
    assert listed == first


def _state(
    *,
    tender: list[EvidenceItemState],
    company: list[EvidenceItemState],
) -> BidRunState:
    return BidRunState(
        run_id=RUN_ID,
        company_id=COMPANY_ID,
        tender_id=TENDER_ID,
        document_ids=[DOCUMENT_ID],
        evidence_board=[*tender, *company],
    )


def _tender_evidence(
    *,
    excerpt: str,
    requirement_type: RequirementType,
    evidence_key: str = "TENDER-REQ-001",
) -> EvidenceItemState:
    return EvidenceItemState(
        evidence_id=TENDER_EVIDENCE_ID,
        evidence_key=evidence_key,
        source_type=EvidenceSourceType.TENDER_DOCUMENT,
        excerpt=excerpt,
        normalized_meaning=excerpt,
        category=requirement_type.value,
        requirement_type=requirement_type,
        confidence=0.94,
        source_metadata={"source_label": "Tender page 1"},
        document_id=DOCUMENT_ID,
        chunk_id=CHUNK_ID,
        page_start=1,
        page_end=1,
    )


def _company_evidence(
    *,
    evidence_key: str = "COMPANY-CERT-001",
    excerpt: str = "The company maintains ISO 27001 certification.",
    category: str = "certification",
    field_path: str = "certifications[0]",
    metadata: dict[str, Any] | None = None,
) -> EvidenceItemState:
    return EvidenceItemState(
        evidence_id=COMPANY_EVIDENCE_ID,
        evidence_key=evidence_key,
        source_type=EvidenceSourceType.COMPANY_PROFILE,
        excerpt=excerpt,
        normalized_meaning=excerpt,
        category=category,
        confidence=0.91,
        source_metadata={"source_label": "Company profile"},
        metadata=metadata or {},
        company_id=COMPANY_ID,
        field_path=field_path,
    )
