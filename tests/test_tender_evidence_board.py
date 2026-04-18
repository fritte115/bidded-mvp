from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

from bidded.agents import RequirementType
from bidded.evidence.tender_document import (
    TenderEvidenceCandidate,
    build_tender_evidence_candidates,
    build_tender_evidence_items,
    get_tender_evidence_item_by_key,
    upsert_tender_evidence_items,
)
from bidded.retrieval import RetrievedDocumentChunk

DOCUMENT_ID = UUID("55555555-5555-4555-8555-555555555555")
CHUNK_ID = UUID("66666666-6666-4666-8666-666666666666")


def _retrieved_chunk(
    text: str,
    *,
    source_label: str = "Tender.pdf",
) -> RetrievedDocumentChunk:
    return RetrievedDocumentChunk(
        chunk_id=str(CHUNK_ID),
        document_id=DOCUMENT_ID,
        page_start=3,
        page_end=3,
        chunk_index=0,
        text=text,
        metadata={"source_label": source_label},
    )


def test_retrieved_chunks_propose_tender_evidence_candidates() -> None:
    chunks = [
        _retrieved_chunk(
            "Supplier must provide ISO 27001 certification. "
            "The agreement starts with a kickoff workshop."
        )
    ]

    candidates = build_tender_evidence_candidates(chunks)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.source_type == "tender_document"
    assert candidate.document_id == DOCUMENT_ID
    assert candidate.chunk_id == CHUNK_ID
    assert candidate.page_start == 3
    assert candidate.page_end == 3
    assert candidate.category == "mandatory_requirement"
    assert candidate.requirement_type is RequirementType.SHALL_REQUIREMENT
    assert candidate.source_label == "Tender.pdf"
    assert candidate.excerpt == "Supplier must provide ISO 27001 certification."
    assert "ISO 27001 certification" in candidate.normalized_meaning


def test_tender_evidence_extraction_classifies_clear_requirement_types() -> None:
    chunks = [
        _retrieved_chunk(
            "Supplier shall hold ISO 27001 certification. "
            "Bidders must provide three comparable public sector references. "
            "Suppliers in bankruptcy are excluded. "
            "Bidders must demonstrate stable financial standing. "
            "The solution must comply with GDPR Article 28. "
            "Supplier shall maintain a quality management system. "
            "Submission must include a signed data processing agreement. "
            "During the contract term, supplier shall meet SLA response times."
        )
    ]

    candidates = build_tender_evidence_candidates(chunks)

    assert [candidate.requirement_type for candidate in candidates] == [
        RequirementType.SHALL_REQUIREMENT,
        RequirementType.QUALIFICATION_REQUIREMENT,
        RequirementType.EXCLUSION_GROUND,
        RequirementType.FINANCIAL_STANDING,
        RequirementType.LEGAL_OR_REGULATORY_REFERENCE,
        RequirementType.QUALITY_MANAGEMENT,
        RequirementType.SUBMISSION_DOCUMENT,
        RequirementType.CONTRACT_OBLIGATION,
    ]
    assert [candidate.category for candidate in candidates] == [
        "mandatory_requirement",
        "qualification_requirement",
        "exclusion_ground",
        "financial_standing",
        "legal_or_regulatory_reference",
        "quality_management",
        "submission_document",
        "contract_obligation",
    ]


def test_tender_evidence_extraction_classifies_swedish_procurement_terms() -> None:
    chunks = [
        _retrieved_chunk(
            "Anbudsgivaren ska kunna uppvisa kreditupplysning. "
            "Leverantören ska ha en stabil ekonomisk bas. "
            "Leverantören får inte vara i konkurs. "
            "Leverantören får inte vara föremål för tvångslikvidation. "
            "Leverantören får inte ha ingått ackord med borgenärer. "
            "Anbudsgivaren får inte vara dömd för brott avseende yrkesutövning. "
            "Insatsen ska följa SOSFS 2011:9. "
            "Leverantören ska ha ett dokumenterat ledningssystem för kvalitet.",
            source_label="Upphandling.pdf",
        )
    ]

    candidates = build_tender_evidence_candidates(chunks)
    items = build_tender_evidence_items(candidates)

    assert [candidate.requirement_type for candidate in candidates] == [
        RequirementType.FINANCIAL_STANDING,
        RequirementType.FINANCIAL_STANDING,
        RequirementType.EXCLUSION_GROUND,
        RequirementType.EXCLUSION_GROUND,
        RequirementType.EXCLUSION_GROUND,
        RequirementType.EXCLUSION_GROUND,
        RequirementType.LEGAL_OR_REGULATORY_REFERENCE,
        RequirementType.QUALITY_MANAGEMENT,
    ]
    assert [item["requirement_type"] for item in items] == [
        "financial_standing",
        "financial_standing",
        "exclusion_ground",
        "exclusion_ground",
        "exclusion_ground",
        "exclusion_ground",
        "legal_or_regulatory_reference",
        "quality_management",
    ]
    assert {item["source_metadata"]["source_label"] for item in items} == {
        "Upphandling.pdf"
    }


def test_ambiguous_tender_evidence_keeps_category_without_requirement_type() -> None:
    chunks = [_retrieved_chunk("Award evaluation may value delivery method and price.")]

    candidates = build_tender_evidence_candidates(chunks)
    item = build_tender_evidence_items(candidates)[0]

    assert len(candidates) == 1
    assert candidates[0].category == "award_criterion"
    assert candidates[0].requirement_type is None
    assert item["category"] == "award_criterion"
    assert item["requirement_type"] is None


def test_tender_evidence_candidate_validation_requires_tender_provenance() -> None:
    candidate = TenderEvidenceCandidate(
        document_id=DOCUMENT_ID,
        chunk_id=CHUNK_ID,
        page_start=2,
        page_end=2,
        excerpt="Bidders shall submit three public-sector references.",
        source_label="Tender.pdf",
        category="qualification_requirement",
        normalized_meaning=(
            "The tender requires three public-sector references from bidders."
        ),
    )

    assert candidate.source_type == "tender_document"
    assert candidate.document_id == DOCUMENT_ID
    assert candidate.chunk_id == CHUNK_ID

    with pytest.raises(ValidationError, match="Input should be 'tender_document'"):
        TenderEvidenceCandidate.model_validate(
            {
                "source_type": "company_profile",
                "document_id": str(DOCUMENT_ID),
                "chunk_id": str(CHUNK_ID),
                "page_start": 2,
                "page_end": 2,
                "excerpt": "Bidders shall submit references.",
                "source_label": "Tender.pdf",
                "category": "qualification_requirement",
                "normalized_meaning": "The tender requires bidder references.",
            }
        )

    with pytest.raises(ValidationError, match="source_label"):
        TenderEvidenceCandidate(
            document_id=DOCUMENT_ID,
            chunk_id=CHUNK_ID,
            page_start=2,
            page_end=2,
            excerpt="Bidders shall submit references.",
            source_label="",
            category="qualification_requirement",
            normalized_meaning="The tender requires bidder references.",
        )


def test_tender_evidence_items_get_stable_keys_and_prevent_duplicates() -> None:
    candidate = TenderEvidenceCandidate(
        document_id=DOCUMENT_ID,
        chunk_id=CHUNK_ID,
        page_start=5,
        page_end=5,
        excerpt="Supplier must hold ISO 27001 certification.",
        source_label="Tender.pdf",
        category="mandatory_requirement",
        requirement_type=RequirementType.SHALL_REQUIREMENT,
        normalized_meaning="The supplier must hold ISO 27001 certification.",
        confidence=0.91,
    )

    first_items = build_tender_evidence_items([candidate, candidate])
    second_items = build_tender_evidence_items([candidate])

    assert first_items == second_items
    assert len(first_items) == 1

    item = first_items[0]
    assert item["tenant_key"] == "demo"
    assert item["source_type"] == "tender_document"
    assert item["evidence_key"].startswith("TENDER-P5-MANDATORY-REQUIREMENT-")
    assert "ISO-27001-CERTIFICATION" in item["evidence_key"]
    assert item["document_id"] == str(DOCUMENT_ID)
    assert item["chunk_id"] == str(CHUNK_ID)
    assert item["page_start"] == 5
    assert item["page_end"] == 5
    assert item["source_metadata"] == {"source_label": "Tender.pdf"}
    assert item["category"] == "mandatory_requirement"
    assert item["requirement_type"] == "shall_requirement"
    assert item["metadata"]["source"] == "tender_evidence_board"


def test_tender_evidence_requirement_type_is_nullable_and_validated() -> None:
    legacy_candidate = TenderEvidenceCandidate(
        document_id=DOCUMENT_ID,
        chunk_id=CHUNK_ID,
        page_start=6,
        page_end=6,
        excerpt="Tender responses are evaluated on quality and price.",
        source_label="Tender.pdf",
        category="award_criterion",
        normalized_meaning="The tender uses quality and price award criteria.",
    )

    legacy_item = build_tender_evidence_items([legacy_candidate])[0]

    assert legacy_candidate.requirement_type is None
    assert legacy_item["requirement_type"] is None
    assert legacy_item["category"] == "award_criterion"

    with pytest.raises(ValidationError, match="Input should be"):
        TenderEvidenceCandidate.model_validate(
            {
                "document_id": str(DOCUMENT_ID),
                "chunk_id": str(CHUNK_ID),
                "page_start": 6,
                "page_end": 6,
                "excerpt": "Supplier should include optional case studies.",
                "source_label": "Tender.pdf",
                "category": "nice_to_have",
                "requirement_type": "nice_to_have",
                "normalized_meaning": "Optional case studies are requested.",
            }
        )


class RecordingEvidenceQuery:
    def __init__(self, client: RecordingSupabaseClient, table_name: str) -> None:
        self.client = client
        self.table_name = table_name
        self.selected_columns: str | None = None
        self.filters: list[tuple[str, str]] = []
        self.upsert_payload: list[dict[str, object]] | None = None
        self.on_conflict: str | None = None

    def select(self, columns: str) -> RecordingEvidenceQuery:
        self.selected_columns = columns
        return self

    def eq(self, column: str, value: object) -> RecordingEvidenceQuery:
        self.filters.append((column, str(value)))
        return self

    def upsert(
        self,
        payload: list[dict[str, object]],
        *,
        on_conflict: str | None = None,
    ) -> RecordingEvidenceQuery:
        self.upsert_payload = payload
        self.on_conflict = on_conflict
        return self

    def execute(self) -> object:
        if self.upsert_payload is not None:
            self.client.upserts.append((self.upsert_payload, self.on_conflict))
            self.client.rows[self.table_name] = list(self.upsert_payload)
            return type("Response", (), {"data": self.upsert_payload})()

        self.client.selects.append(
            (self.table_name, self.selected_columns, self.filters)
        )
        rows = self.client.rows.get(self.table_name, [])
        filtered_rows = [
            row
            for row in rows
            if all(str(row.get(column)) == value for column, value in self.filters)
        ]
        return type("Response", (), {"data": filtered_rows})()


class RecordingSupabaseClient:
    def __init__(self) -> None:
        self.rows: dict[str, list[dict[str, object]]] = {"evidence_items": []}
        self.upserts: list[tuple[list[dict[str, object]], str | None]] = []
        self.selects: list[
            tuple[str, str | None, list[tuple[str, str]]]
        ] = []
        self.table_names: list[str] = []

    def table(self, table_name: str) -> RecordingEvidenceQuery:
        self.table_names.append(table_name)
        assert table_name == "evidence_items"
        return RecordingEvidenceQuery(self, table_name)


def test_orchestrator_persists_tender_evidence_and_looks_up_by_key() -> None:
    client = RecordingSupabaseClient()
    candidate = TenderEvidenceCandidate(
        document_id=DOCUMENT_ID,
        chunk_id=CHUNK_ID,
        page_start=7,
        page_end=7,
        excerpt="Submission must include a signed data processing agreement.",
        source_label="Tender.pdf",
        category="submission_document",
        normalized_meaning=(
            "The tender requires a signed data processing agreement in submission."
        ),
    )

    result = upsert_tender_evidence_items(client, [candidate, candidate])
    evidence_key = result.evidence_keys[0]
    looked_up = get_tender_evidence_item_by_key(client, evidence_key)

    assert result.evidence_count == 1
    assert result.rows_returned == 1
    assert client.upserts[0][1] == "tenant_key,evidence_key"
    assert client.upserts[0][0][0]["evidence_key"] == evidence_key
    assert looked_up is not None
    assert looked_up["evidence_key"] == evidence_key
    assert looked_up["source_type"] == "tender_document"
    assert client.selects[-1][2] == [
        ("tenant_key", "demo"),
        ("source_type", "tender_document"),
        ("evidence_key", evidence_key),
    ]
