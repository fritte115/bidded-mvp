from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

from bidded.agents import RequirementType
from bidded.evidence.contract_clause_classifier import MockContractClauseClassifier
from bidded.evidence.tender_document import (
    TenderEvidenceCandidate,
    build_tender_clause_segments,
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
    chunk_id: UUID = CHUNK_ID,
    page_start: int = 3,
    page_end: int | None = None,
    chunk_index: int = 0,
) -> RetrievedDocumentChunk:
    return RetrievedDocumentChunk(
        chunk_id=str(chunk_id),
        document_id=DOCUMENT_ID,
        page_start=page_start,
        page_end=page_end if page_end is not None else page_start,
        chunk_index=chunk_index,
        text=text,
        metadata={"source_label": source_label},
    )


def test_clause_segmentation_detects_numbered_headings_and_wrapped_text() -> None:
    second_chunk_id = UUID("77777777-7777-4777-8777-777777777777")
    chunks = [
        _retrieved_chunk(
            "1. General conditions\nSupplier shall attend the kickoff meeting.",
            page_start=1,
            chunk_index=0,
        ),
        _retrieved_chunk(
            "2.1 Ansvarsbegränsning\n"
            "Leverantörens ansvar ska vara begränsat.\n\n"
            "3. Limitation of\n"
            "liability\n"
            "Supplier shall maintain\n"
            "professional liability insurance.",
            chunk_id=second_chunk_id,
            page_start=2,
            chunk_index=1,
        ),
    ]

    segments = build_tender_clause_segments(chunks)

    assert [segment.section_number for segment in segments] == [
        "1",
        "2.1",
        "3",
    ]
    assert [segment.heading for segment in segments] == [
        "General conditions",
        "Ansvarsbegränsning",
        "Limitation of liability",
    ]
    assert segments[0].page_start == 1
    assert segments[0].page_end == 1
    assert segments[0].chunk_ids == (CHUNK_ID,)
    assert segments[1].page_start == 2
    assert segments[2].page_end == 2
    assert segments[2].chunk_ids == (second_chunk_id,)
    assert segments[2].body_text == (
        "Supplier shall maintain professional liability insurance."
    )


def test_clause_segmentation_detects_heading_only_sections() -> None:
    chunks = [
        _retrieved_chunk(
            "Confidentiality\n"
            "Supplier must protect confidential information. "
            "The obligation shall survive termination.\n\n"
            "Underleverantörer\n"
            "Leverantören ska ansvara för underleverantörer.",
            page_start=4,
        )
    ]

    segments = build_tender_clause_segments(chunks)

    assert [segment.section_number for segment in segments] == [None, None]
    assert [segment.heading for segment in segments] == [
        "Confidentiality",
        "Underleverantörer",
    ]
    assert segments[0].body_text == (
        "Supplier must protect confidential information. "
        "The obligation shall survive termination."
    )
    assert segments[1].body_text == ("Leverantören ska ansvara för underleverantörer.")


def test_tender_evidence_items_include_clause_section_metadata() -> None:
    chunks = [
        _retrieved_chunk(
            "4. Insurance\nSupplier shall maintain\nprofessional liability insurance.",
            page_start=6,
        )
    ]

    candidates = build_tender_evidence_candidates(chunks)
    items = build_tender_evidence_items(candidates)

    assert len(items) == 1
    item = items[0]
    assert item["source_metadata"] == {"source_label": "Tender.pdf"}
    assert item["excerpt"] == (
        "Supplier shall maintain professional liability insurance."
    )
    assert item["metadata"]["clause_section"] == {
        "section_number": "4",
        "heading": "Insurance",
        "page_start": 6,
        "page_end": 6,
        "chunk_ids": [str(CHUNK_ID)],
        "body_text": "Supplier shall maintain professional liability insurance.",
    }


def test_tender_evidence_extraction_uses_sentence_fallback_without_headings() -> None:
    chunks = [_retrieved_chunk("Supplier must provide ISO 27001 certification.")]

    segments = build_tender_clause_segments(chunks)
    candidates = build_tender_evidence_candidates(chunks)
    item = build_tender_evidence_items(candidates)[0]

    assert segments == []
    assert candidates[0].excerpt == "Supplier must provide ISO 27001 certification."
    assert "clause_section" not in item["metadata"]


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
        RequirementType.QUALITY_MANAGEMENT,
        RequirementType.QUALITY_MANAGEMENT,
    ]
    assert [item["requirement_type"] for item in items] == [
        "financial_standing",
        "financial_standing",
        "exclusion_ground",
        "exclusion_ground",
        "exclusion_ground",
        "exclusion_ground",
        "quality_management",
        "quality_management",
    ]
    assert {item["source_metadata"]["source_label"] for item in items} == {
        "Upphandling.pdf"
    }


def test_tender_evidence_extraction_uses_regulatory_glossary_terms() -> None:
    chunks = [
        _retrieved_chunk(
            "The supplier may be rejected for professional misconduct. "
            "The engagement must follow SOSFS 2011:9."
        )
    ]

    candidates = build_tender_evidence_candidates(chunks)
    items = build_tender_evidence_items(candidates)

    assert [candidate.requirement_type for candidate in candidates] == [
        RequirementType.EXCLUSION_GROUND,
        RequirementType.QUALITY_MANAGEMENT,
    ]
    assert [candidate.category for candidate in candidates] == [
        "exclusion_ground",
        "quality_management",
    ]
    assert [item["metadata"]["regulatory_glossary_ids"][0] for item in items] == [
        "professional_misconduct",
        "quality_management_sosfs",
    ]


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


def test_tender_evidence_items_include_regulatory_glossary_metadata() -> None:
    candidate = TenderEvidenceCandidate(
        document_id=DOCUMENT_ID,
        chunk_id=CHUNK_ID,
        page_start=5,
        page_end=5,
        excerpt=(
            "Supplier shall provide a credit report and submit quarterly reports "
            "during the contract."
        ),
        source_label="Tender.pdf",
        category="financial_standing",
        requirement_type=RequirementType.FINANCIAL_STANDING,
        normalized_meaning=(
            "The tender requires financial proof and contract reporting."
        ),
    )

    item = build_tender_evidence_items([candidate])[0]

    assert item["source_type"] == "tender_document"
    assert item["source_metadata"] == {"source_label": "Tender.pdf"}
    assert item["metadata"]["source"] == "tender_evidence_board"
    assert item["metadata"]["regulatory_glossary_ids"] == [
        "financial_standing",
        "contract_reporting_obligations",
    ]

    glossary_matches = item["metadata"]["regulatory_glossary"]
    assert glossary_matches == [
        {
            "id": "financial_standing",
            "display_label": "Financial standing",
            "requirement_type": "financial_standing",
            "matched_patterns": ["credit report"],
            "reference_hint": (
                "Check tender language on economic and financial capacity."
            ),
            "suggested_proof_action": (
                "Prepare current credit report and financial capacity evidence."
            ),
            "blocker_hint": (
                "Missing financial standing proof can block qualification."
            ),
        },
        {
            "id": "contract_reporting_obligations",
            "display_label": "Contract reporting obligations",
            "requirement_type": "contract_obligation",
            "matched_patterns": ["quarterly report", "during the contract"],
            "reference_hint": "Check reporting duties that apply after contract award.",
            "suggested_proof_action": (
                "Confirm delivery team can produce the required contract reports."
            ),
            "blocker_hint": (
                "Reporting duties are delivery risks unless marked mandatory."
            ),
        },
    ]


def test_tender_evidence_items_include_contract_clause_tag_metadata() -> None:
    candidate = TenderEvidenceCandidate(
        document_id=DOCUMENT_ID,
        chunk_id=CHUNK_ID,
        page_start=7,
        page_end=7,
        excerpt=(
            "Supplier accepts liquidated damages while liability cap remains "
            "limited to annual fees."
        ),
        source_label="Tender.pdf",
        category="contract_obligation",
        requirement_type=RequirementType.CONTRACT_OBLIGATION,
        normalized_meaning=(
            "The tender includes penalties and liability-cap contract terms."
        ),
    )

    item = build_tender_evidence_items([candidate])[0]

    assert item["requirement_type"] == "contract_obligation"
    assert item["metadata"]["contract_clause_ids"] == [
        "penalties_liquidated_damages",
        "liability_caps",
    ]
    assert item["metadata"]["contract_clause_matches"][0] == {
        "id": "penalties_liquidated_damages",
        "display_label": "Penalties and liquidated damages",
        "matched_patterns": ["liquidated damages"],
        "risk_lens": (
            "Check whether monetary sanctions are capped and operationally fair."
        ),
        "suggested_proof_action": (
            "Model likely service-credit exposure and confirm delivery controls."
        ),
        "blocker_review_hint": (
            "Escalate uncapped or disproportionate penalties for review."
        ),
    }
    assert set(item["metadata"]["contract_clause_matches"][1]) == {
        "id",
        "display_label",
        "matched_patterns",
        "risk_lens",
        "suggested_proof_action",
        "blocker_review_hint",
    }


def test_tender_evidence_clause_metadata_uses_clause_context_for_tags() -> None:
    chunks = [
        _retrieved_chunk(
            "8. Liability cap\n"
            "During the contract, damages are capped at 2 Mkr per claim.",
            page_start=8,
        )
    ]

    item = build_tender_evidence_items(build_tender_evidence_candidates(chunks))[0]

    assert item["excerpt"] == (
        "During the contract, damages are capped at 2 Mkr per claim."
    )
    assert item["requirement_type"] == "contract_obligation"
    assert item["metadata"]["clause_section"]["heading"] == "Liability cap"
    assert item["metadata"]["contract_clause_ids"] == ["liability_caps"]
    assert item["metadata"]["contract_clause_matches"] == [
        {
            "id": "liability_caps",
            "display_label": "Liability caps",
            "matched_patterns": ["liability cap"],
            "risk_lens": (
                "Check total liability exposure against deal value and insurance."
            ),
            "suggested_proof_action": (
                "Confirm proposed cap and carve-outs with legal and commercial owners."
            ),
            "blocker_review_hint": (
                "Escalate unlimited or unusually high liability exposure."
            ),
        }
    ]
    assert item["metadata"]["extracted_terms"]["money_amounts"] == [
        {
            "raw_text": "2 Mkr",
            "amount": 2,
            "currency": "SEK",
            "unit": "Mkr",
            "normalized_amount_sek": 2_000_000,
            "context": "liability_cap",
        }
    ]
    assert item["metadata"]["extracted_terms"]["recurrence_or_cap_phrases"] == [
        {
            "raw_text": "per claim",
            "normalized_unit": "claim",
            "scope_type": "claim",
        }
    ]
    assert item["source_metadata"] == {"source_label": "Tender.pdf"}


def test_tender_evidence_items_apply_mocked_clause_classifier_metadata() -> None:
    chunks = [
        _retrieved_chunk(
            "8. Commercial exposure\n"
            "During the contract, the supplier's aggregate financial exposure "
            "is limited to twelve months of fees.",
            page_start=8,
        )
    ]
    classifier = MockContractClauseClassifier(
        tag_id="liability_caps",
        confidence=0.83,
        rationale="The clause uses document-specific wording for a liability cap.",
    )

    item = build_tender_evidence_items(
        build_tender_evidence_candidates(chunks),
        clause_classifier=classifier,
    )[0]

    assert classifier.requests[0].evidence_key == item["evidence_key"]
    assert classifier.requests[0].clause_provenance is not None
    assert classifier.requests[0].clause_provenance.heading == "Commercial exposure"
    assert classifier.requests[0].deterministic_tag_ids == ()
    assert item["metadata"]["contract_clause_ids"] == ["liability_caps"]
    assert item["metadata"]["contract_clause_classification"] == {
        "tag_id": "liability_caps",
        "confidence": 0.83,
        "rationale": ("The clause uses document-specific wording for a liability cap."),
        "evidence_key": item["evidence_key"],
        "clause_provenance": None,
        "missing_info": [],
        "review_warnings": [],
    }


def test_tender_evidence_items_extract_structured_contract_terms() -> None:
    chunks = [
        _retrieved_chunk(
            "7. Vite\n"
            "Leverantören ska betala vite om 5 000 SEK per week. "
            "Vite är maximalt 25 000 SEK per month per claim.\n\n"
            "8. Liability cap\n"
            "Supplier liability cap is 10 Mkr per year, with GDPR damages "
            "capped at 2 Mkr per claim.\n\n"
            "9. Payment\n"
            "Payment shall be made within trettio (30) dagar from invoice date. "
            "Supplier must also accept payment within 30 days.",
            page_start=8,
        )
    ]

    items = build_tender_evidence_items(build_tender_evidence_candidates(chunks))
    terms_by_excerpt = {
        item["excerpt"]: item["metadata"]["extracted_terms"]
        for item in items
        if "extracted_terms" in item["metadata"]
    }

    penalty_terms = terms_by_excerpt[
        "Leverantören ska betala vite om 5 000 SEK per week."
    ]
    assert penalty_terms["money_amounts"] == [
        {
            "raw_text": "5 000 SEK",
            "amount": 5000,
            "currency": "SEK",
            "unit": "SEK",
            "normalized_amount_sek": 5000,
            "context": "penalty_amount",
        }
    ]
    assert penalty_terms["recurrence_or_cap_phrases"] == [
        {
            "raw_text": "per week",
            "normalized_unit": "week",
            "scope_type": "period",
        }
    ]
    assert penalty_terms["day_deadlines"] == []

    recurring_cap_terms = terms_by_excerpt[
        "Vite är maximalt 25 000 SEK per month per claim."
    ]
    assert recurring_cap_terms["money_amounts"] == [
        {
            "raw_text": "25 000 SEK",
            "amount": 25000,
            "currency": "SEK",
            "unit": "SEK",
            "normalized_amount_sek": 25000,
            "context": "penalty_amount",
        }
    ]
    assert recurring_cap_terms["recurrence_or_cap_phrases"] == [
        {
            "raw_text": "per month",
            "normalized_unit": "month",
            "scope_type": "period",
        },
        {
            "raw_text": "per claim",
            "normalized_unit": "claim",
            "scope_type": "claim",
        },
    ]

    cap_terms = terms_by_excerpt[
        "Supplier liability cap is 10 Mkr per year, with GDPR damages "
        "capped at 2 Mkr per claim."
    ]
    assert cap_terms["money_amounts"] == [
        {
            "raw_text": "10 Mkr",
            "amount": 10,
            "currency": "SEK",
            "unit": "Mkr",
            "normalized_amount_sek": 10_000_000,
            "context": "liability_cap",
        },
        {
            "raw_text": "2 Mkr",
            "amount": 2,
            "currency": "SEK",
            "unit": "Mkr",
            "normalized_amount_sek": 2_000_000,
            "context": "liability_cap",
        },
    ]
    assert cap_terms["recurrence_or_cap_phrases"] == [
        {
            "raw_text": "per year",
            "normalized_unit": "year",
            "scope_type": "period",
        },
        {
            "raw_text": "per claim",
            "normalized_unit": "claim",
            "scope_type": "claim",
        },
    ]

    assert terms_by_excerpt[
        "Payment shall be made within trettio (30) dagar from invoice date."
    ]["day_deadlines"] == [
        {
            "raw_text": "trettio (30) dagar",
            "days": 30,
            "unit": "days",
            "context": "payment_deadline",
        }
    ]
    assert terms_by_excerpt["Supplier must also accept payment within 30 days."][
        "day_deadlines"
    ] == [
        {
            "raw_text": "30 days",
            "days": 30,
            "unit": "days",
            "context": "payment_deadline",
        }
    ]


def test_tender_evidence_items_omit_regulatory_glossary_metadata_for_no_match() -> None:
    candidate = TenderEvidenceCandidate(
        document_id=DOCUMENT_ID,
        chunk_id=CHUNK_ID,
        page_start=6,
        page_end=6,
        excerpt="Tender responses are evaluated on quality and price.",
        source_label="Tender.pdf",
        category="award_criterion",
        normalized_meaning="The tender uses quality and price award criteria.",
    )

    item = build_tender_evidence_items([candidate])[0]

    assert item["metadata"] == {"source": "tender_evidence_board"}


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
            if self.client.fail_requirement_type_once and any(
                "requirement_type" in row for row in self.upsert_payload
            ):
                self.client.fail_requirement_type_once = False
                raise RuntimeError(
                    "Could not find the 'requirement_type' column of "
                    "'evidence_items' in the schema cache"
                )
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
        self.selects: list[tuple[str, str | None, list[tuple[str, str]]]] = []
        self.table_names: list[str] = []
        self.fail_requirement_type_once = False

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


def test_tender_evidence_upsert_falls_back_without_requirement_type() -> None:
    client = RecordingSupabaseClient()
    client.fail_requirement_type_once = True
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

    result = upsert_tender_evidence_items(client, [candidate])

    assert result.evidence_count == 1
    assert len(client.upserts) == 1
    assert "requirement_type" not in client.upserts[0][0][0]
