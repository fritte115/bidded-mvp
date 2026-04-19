from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bidded.evidence.contract_clause_classifier import (
    DEFAULT_MIN_CLASSIFIER_CONFIDENCE,
    ContractClauseClassificationOutput,
    ContractClauseClassificationRequest,
    ContractClauseClassifier,
    ContractClauseProvenance,
    classify_contract_clause,
    contract_clause_classification_metadata,
)
from bidded.evidence.contract_clause_tags import (
    ContractClauseTagMatch,
    match_contract_clause_tags,
)
from bidded.evidence.contract_terms import extract_contract_terms
from bidded.evidence.regulatory_glossary import (
    RegulatoryGlossaryMatch,
    match_regulatory_glossary,
)
from bidded.requirements import RequirementType
from bidded.retrieval import RetrievedDocumentChunk

_CATEGORY_BY_REQUIREMENT_TYPE: dict[RequirementType, str] = {
    RequirementType.SHALL_REQUIREMENT: "mandatory_requirement",
    RequirementType.QUALIFICATION_REQUIREMENT: "qualification_requirement",
    RequirementType.EXCLUSION_GROUND: "exclusion_ground",
    RequirementType.FINANCIAL_STANDING: "financial_standing",
    RequirementType.LEGAL_OR_REGULATORY_REFERENCE: "legal_or_regulatory_reference",
    RequirementType.QUALITY_MANAGEMENT: "quality_management",
    RequirementType.SUBMISSION_DOCUMENT: "submission_document",
    RequirementType.CONTRACT_OBLIGATION: "contract_obligation",
}

_REQUIREMENT_TYPE_KEYWORDS: tuple[tuple[RequirementType, tuple[str, ...]], ...] = (
    (
        RequirementType.EXCLUSION_GROUND,
        (
            "bankrupt",
            "bankruptcy",
            "excluded",
            "exclusion ground",
            "insolvency",
            "compulsory liquidation",
            "composition with creditors",
            "criminal professional conduct",
            "konkurs",
            "tvångslikvidation",
            "tvangslikvidation",
            "ackord",
            "brott avseende yrkesutövning",
            "brott avseende yrkesutovning",
        ),
    ),
    (
        RequirementType.FINANCIAL_STANDING,
        (
            "credit report",
            "credit check",
            "financial standing",
            "financial capacity",
            "economic standing",
            "stable financial base",
            "annual turnover",
            "kreditupplysning",
            "stabil ekonomisk bas",
            "ekonomisk ställning",
            "ekonomisk stallning",
            "finansiell ställning",
            "finansiell stallning",
            "omsättning",
            "omsattning",
        ),
    ),
    (
        RequirementType.LEGAL_OR_REGULATORY_REFERENCE,
        (
            "gdpr",
            "article 28",
            "regulation",
            "statutory",
            "legal",
            "law",
            "sosfs",
            "sosfs 2011:9",
            "föreskrift",
            "foreskrift",
            "förordning",
            "forordning",
            "enligt lag",
        ),
    ),
    (
        RequirementType.QUALITY_MANAGEMENT,
        (
            "quality management system",
            "quality system",
            "management system",
            "iso 9001",
            "ledningssystem",
            "kvalitetsledningssystem",
            "systematiskt kvalitetsarbete",
        ),
    ),
    (
        RequirementType.SUBMISSION_DOCUMENT,
        (
            "submission must include",
            "must include",
            "shall include",
            "include a signed",
            "submitted document",
            "documents must be submitted",
            "signed data processing agreement",
            "anbudet ska innehålla",
            "anbudet skall innehålla",
            "ska bifoga",
            "skall bifoga",
            "bifoga",
            "bilaga",
            "undertecknad",
            "handlingar",
            "ska lämnas in",
            "ska lamnas in",
        ),
    ),
    (
        RequirementType.CONTRACT_OBLIGATION,
        (
            "contract term",
            "during the contract",
            "agreement period",
            "service level",
            "sla",
            "liability",
            "penalty",
            "penalties",
            "liquidated damages",
            "under avtalstiden",
            "avtalsperiod",
            "servicenivå",
            "serviceniva",
            "vite",
        ),
    ),
    (
        RequirementType.QUALIFICATION_REQUIREMENT,
        (
            "qualification",
            "qualified",
            "references",
            "reference assignments",
            "public sector references",
            "demonstrate",
            "experience",
            "referenser",
            "referensuppdrag",
            "kvalificeringskrav",
            "kompetens",
            "erfarenhet",
            "kapacitet",
        ),
    ),
    (
        RequirementType.SHALL_REQUIREMENT,
        (
            "must",
            "shall",
            "mandatory",
            "required",
            "ska",
            "skall",
            "måste",
            "maste",
            "obligatorisk",
            "krävs",
            "kravs",
        ),
    ),
)

_NUMBERED_HEADING_RE = re.compile(
    r"^(?P<section>\d+(?:\.\d+)*)(?:[.)])?\s+(?P<heading>.+?)\s*$"
)
_SECTION_LABEL_HEADING_RE = re.compile(
    r"^(?:section|clause|avsnitt|kapitel)\s+"
    r"(?P<section>\d+(?:\.\d+)*)(?:[.:)\-\s]+)(?P<heading>.+?)\s*$",
    re.IGNORECASE,
)
_SWEDISH_SECTION_HEADING_RE = re.compile(
    r"^§\s*(?P<section>\d+(?:\.\d+)*)(?:[.:)\-\s]+)(?P<heading>.+?)\s*$"
)
_HEADING_CONTINUATION_ENDINGS = frozenset(
    {
        "and",
        "for",
        "of",
        "on",
        "or",
        "regarding",
        "with",
        "av",
        "för",
        "gällande",
        "gallande",
        "med",
        "och",
        "om",
        "samt",
    }
)
_UNNUMBERED_CLAUSE_HEADINGS = frozenset(
    {
        "ansvar",
        "ansvarsbegränsning",
        "ansvarsbegransning",
        "confidentiality",
        "data protection",
        "dataskydd",
        "försäkring",
        "forsakring",
        "gdpr",
        "insurance",
        "liability",
        "limitation of liability",
        "personuppgifter",
        "penalties",
        "penalty",
        "sekretess",
        "subcontracting",
        "subcontractors",
        "underleverantörer",
        "underleverantorer",
        "vite",
    }
)
_UNNUMBERED_CLAUSE_HEADING_KEYWORDS = (
    "ansvar",
    "confidential",
    "data protection",
    "dataskydd",
    "forsakring",
    "försäkring",
    "gdpr",
    "insurance",
    "liability",
    "penalt",
    "personuppgift",
    "sekretess",
    "subcontract",
    "underleverant",
    "vite",
)


class SupabaseTenderEvidenceQuery(Protocol):
    def select(self, columns: str) -> SupabaseTenderEvidenceQuery: ...

    def eq(self, column: str, value: object) -> SupabaseTenderEvidenceQuery: ...

    def upsert(
        self,
        payload: list[dict[str, Any]],
        *,
        on_conflict: str | None = None,
    ) -> SupabaseTenderEvidenceQuery: ...

    def execute(self) -> Any: ...


class SupabaseTenderEvidenceClient(Protocol):
    def table(self, table_name: str) -> SupabaseTenderEvidenceQuery: ...


@dataclass(frozen=True)
class TenderEvidenceUpsertResult:
    evidence_count: int
    evidence_keys: tuple[str, ...]
    rows_returned: int


@dataclass(frozen=True)
class _TenderClauseLine:
    chunk: RetrievedDocumentChunk
    text: str


@dataclass(frozen=True)
class _DetectedTenderHeading:
    section_number: str | None
    heading: str
    consumed_line_count: int


class TenderClauseSegment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: UUID
    section_number: str | None = None
    heading: str = Field(min_length=1)
    page_start: int = Field(gt=0)
    page_end: int = Field(gt=0)
    chunk_ids: tuple[UUID, ...] = Field(min_length=1)
    body_text: str = ""

    @model_validator(mode="after")
    def validate_clause_segment(self) -> TenderClauseSegment:
        if self.page_end < self.page_start:
            raise ValueError("page_end must be greater than or equal to page_start")
        return self


class TenderEvidenceCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_type: Literal["tender_document"] = "tender_document"
    document_id: UUID
    chunk_id: UUID
    page_start: int = Field(gt=0)
    page_end: int = Field(gt=0)
    excerpt: str = Field(min_length=1)
    source_label: str = Field(min_length=1)
    category: str = Field(min_length=1)
    requirement_type: RequirementType | None = None
    normalized_meaning: str = Field(min_length=1)
    confidence: float = Field(default=0.8, ge=0, le=1)
    clause_section: TenderClauseSegment | None = None

    @model_validator(mode="after")
    def validate_page_range(self) -> TenderEvidenceCandidate:
        if self.page_end < self.page_start:
            raise ValueError("page_end must be greater than or equal to page_start")
        return self


def build_tender_clause_segments(
    chunks: list[RetrievedDocumentChunk],
) -> list[TenderClauseSegment]:
    """Group parsed tender chunks into deterministic numbered clause sections."""

    lines = _tender_clause_lines(chunks)
    segments: list[TenderClauseSegment] = []
    current_document_id: UUID | None = None
    current_section_number: str | None = None
    current_heading: str | None = None
    current_page_start: int | None = None
    current_page_end: int | None = None
    current_chunk_ids: list[UUID] = []
    current_body_lines: list[str] = []

    def add_provenance(line: _TenderClauseLine) -> None:
        nonlocal current_page_start, current_page_end
        chunk_id = UUID(line.chunk.chunk_id)
        if chunk_id not in current_chunk_ids:
            current_chunk_ids.append(chunk_id)
        if current_page_start is None or line.chunk.page_start < current_page_start:
            current_page_start = line.chunk.page_start
        if current_page_end is None or line.chunk.page_end > current_page_end:
            current_page_end = line.chunk.page_end

    def finalize_current() -> None:
        nonlocal current_document_id, current_section_number, current_heading
        nonlocal current_page_start, current_page_end, current_chunk_ids
        nonlocal current_body_lines
        if (
            current_document_id is None
            or current_heading is None
            or current_page_start is None
            or current_page_end is None
            or not current_chunk_ids
        ):
            return

        segments.append(
            TenderClauseSegment(
                document_id=current_document_id,
                section_number=current_section_number,
                heading=current_heading,
                page_start=current_page_start,
                page_end=current_page_end,
                chunk_ids=tuple(current_chunk_ids),
                body_text=_inline_text(" ".join(current_body_lines)),
            )
        )
        current_document_id = None
        current_section_number = None
        current_heading = None
        current_page_start = None
        current_page_end = None
        current_chunk_ids = []
        current_body_lines = []

    index = 0
    while index < len(lines):
        line = lines[index]
        if (
            current_document_id is not None
            and line.chunk.document_id != current_document_id
        ):
            finalize_current()

        detected_heading = _detect_clause_heading(lines, index)
        if detected_heading is not None:
            finalize_current()
            current_document_id = line.chunk.document_id
            current_section_number = detected_heading.section_number
            current_heading = detected_heading.heading
            for consumed_line in lines[
                index : index + detected_heading.consumed_line_count
            ]:
                add_provenance(consumed_line)
            index += detected_heading.consumed_line_count
            continue

        if current_heading is not None:
            current_body_lines.append(line.text)
            add_provenance(line)
        index += 1

    finalize_current()
    return segments


def build_tender_evidence_candidates(
    chunks: list[RetrievedDocumentChunk],
) -> list[TenderEvidenceCandidate]:
    """Propose excerpt-level tender evidence from retrieved document chunks."""

    clause_segments = build_tender_clause_segments(chunks)
    if clause_segments:
        return _build_clause_scoped_evidence_candidates(chunks, clause_segments)

    candidates: list[TenderEvidenceCandidate] = []
    for chunk in chunks:
        source_label = str(chunk.metadata.get("source_label") or "tender document")
        for sentence in _sentences(chunk.text):
            category = _category_for_sentence(sentence)
            if category is None:
                continue

            candidates.append(
                TenderEvidenceCandidate(
                    document_id=chunk.document_id,
                    chunk_id=UUID(chunk.chunk_id),
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    excerpt=sentence,
                    source_label=source_label,
                    category=category,
                    requirement_type=_requirement_type_for_sentence(sentence),
                    normalized_meaning=f"Tender states: {sentence}",
                )
            )

    return candidates


def _build_clause_scoped_evidence_candidates(
    chunks: list[RetrievedDocumentChunk],
    clause_segments: list[TenderClauseSegment],
) -> list[TenderEvidenceCandidate]:
    candidates: list[TenderEvidenceCandidate] = []
    chunks_by_id = {UUID(chunk.chunk_id): chunk for chunk in chunks}
    for segment in clause_segments:
        if not segment.body_text:
            continue
        for sentence in _sentences(segment.body_text):
            category = _category_for_sentence(sentence)
            if category is None:
                continue
            chunk = _chunk_for_clause_sentence(
                sentence,
                segment=segment,
                chunks_by_id=chunks_by_id,
            )
            source_label = str(
                chunk.metadata.get("source_label") or "tender document"
            )
            candidates.append(
                TenderEvidenceCandidate(
                    document_id=segment.document_id,
                    chunk_id=UUID(chunk.chunk_id),
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    excerpt=sentence,
                    source_label=source_label,
                    category=category,
                    requirement_type=_requirement_type_for_sentence(sentence),
                    normalized_meaning=f"Tender states: {sentence}",
                    clause_section=segment,
                )
            )

    return candidates


def build_tender_evidence_items(
    candidates: list[TenderEvidenceCandidate | Mapping[str, Any]],
    *,
    tenant_key: str = "demo",
    clause_classifier: ContractClauseClassifier | None = None,
    classifier_min_confidence: float = DEFAULT_MIN_CLASSIFIER_CONFIDENCE,
) -> list[dict[str, Any]]:
    """Validate candidates and convert them to evidence_items payloads."""

    evidence_items: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for raw_candidate in candidates:
        candidate = TenderEvidenceCandidate.model_validate(raw_candidate)
        evidence_key = _evidence_key(candidate)
        if evidence_key in seen_keys:
            continue
        seen_keys.add(evidence_key)
        metadata = _metadata_for_candidate(candidate)
        if clause_classifier is not None:
            classification_request = _classification_request_for_candidate(
                candidate,
                evidence_key=evidence_key,
                metadata=metadata,
            )
            classification = classify_contract_clause(
                classification_request,
                clause_classifier,
                min_confidence=classifier_min_confidence,
            )
            _apply_contract_clause_classification(metadata, classification)
        evidence_items.append(
            {
                "tenant_key": tenant_key,
                "evidence_key": evidence_key,
                "source_type": "tender_document",
                "excerpt": candidate.excerpt,
                "normalized_meaning": candidate.normalized_meaning,
                "category": candidate.category,
                "requirement_type": (
                    candidate.requirement_type.value
                    if candidate.requirement_type is not None
                    else None
                ),
                "confidence": candidate.confidence,
                "source_metadata": {"source_label": candidate.source_label},
                "document_id": str(candidate.document_id),
                "chunk_id": str(candidate.chunk_id),
                "page_start": candidate.page_start,
                "page_end": candidate.page_end,
                "metadata": metadata,
            }
        )

    return evidence_items


def upsert_tender_evidence_items(
    client: SupabaseTenderEvidenceClient,
    candidates: list[TenderEvidenceCandidate | Mapping[str, Any]],
    *,
    tenant_key: str = "demo",
    clause_classifier: ContractClauseClassifier | None = None,
    classifier_min_confidence: float = DEFAULT_MIN_CLASSIFIER_CONFIDENCE,
) -> TenderEvidenceUpsertResult:
    evidence_items = build_tender_evidence_items(
        candidates,
        tenant_key=tenant_key,
        clause_classifier=clause_classifier,
        classifier_min_confidence=classifier_min_confidence,
    )
    response = (
        client.table("evidence_items")
        .upsert(evidence_items, on_conflict="tenant_key,evidence_key")
        .execute()
    )
    data = getattr(response, "data", [])
    rows_returned = len(data) if isinstance(data, list) else 0

    return TenderEvidenceUpsertResult(
        evidence_count=len(evidence_items),
        evidence_keys=tuple(item["evidence_key"] for item in evidence_items),
        rows_returned=rows_returned,
    )


def get_tender_evidence_item_by_key(
    client: SupabaseTenderEvidenceClient,
    evidence_key: str,
    *,
    tenant_key: str = "demo",
) -> dict[str, Any] | None:
    response = (
        client.table("evidence_items")
        .select("*")
        .eq("tenant_key", tenant_key)
        .eq("source_type", "tender_document")
        .eq("evidence_key", evidence_key)
        .execute()
    )
    data = getattr(response, "data", None)
    if not isinstance(data, list):
        return None
    first_row = next((row for row in data if isinstance(row, Mapping)), None)
    return dict(first_row) if first_row is not None else None


def _evidence_key(candidate: TenderEvidenceCandidate) -> str:
    readable_slug = _slug(candidate.excerpt)
    digest = sha256(
        "|".join(
            [
                str(candidate.document_id),
                str(candidate.chunk_id),
                str(candidate.page_start),
                str(candidate.page_end),
                candidate.category,
                candidate.excerpt,
                candidate.normalized_meaning,
            ]
        ).encode("utf-8")
    ).hexdigest()[:8].upper()
    return (
        f"TENDER-P{candidate.page_start}-"
        f"{_slug(candidate.category)}-{readable_slug[:80].strip('-')}-{digest}"
    )


def _metadata_for_candidate(candidate: TenderEvidenceCandidate) -> dict[str, Any]:
    metadata: dict[str, Any] = {"source": "tender_evidence_board"}
    if candidate.clause_section is not None:
        metadata["clause_section"] = _clause_section_metadata(
            candidate.clause_section
        )
    contract_clause_tag_matches = match_contract_clause_tags(
        _contract_clause_context(candidate)
    )
    if contract_clause_tag_matches:
        metadata["contract_clause_ids"] = [
            match.tag_id for match in contract_clause_tag_matches
        ]
        metadata["contract_clause_matches"] = [
            _contract_clause_tag_match_metadata(match)
            for match in contract_clause_tag_matches
        ]

    extracted_terms = extract_contract_terms(candidate.excerpt)
    if extracted_terms.has_terms:
        metadata["extracted_terms"] = extracted_terms.as_metadata()

    glossary_matches = match_regulatory_glossary(candidate.excerpt)
    if not glossary_matches:
        return metadata

    metadata["regulatory_glossary_ids"] = [
        match.entry_id for match in glossary_matches
    ]
    metadata["regulatory_glossary"] = [
        _glossary_match_metadata(match) for match in glossary_matches
    ]
    return metadata


def _clause_section_metadata(segment: TenderClauseSegment) -> dict[str, Any]:
    return {
        "section_number": segment.section_number,
        "heading": segment.heading,
        "page_start": segment.page_start,
        "page_end": segment.page_end,
        "chunk_ids": [str(chunk_id) for chunk_id in segment.chunk_ids],
        "body_text": segment.body_text,
    }


def _contract_clause_context(candidate: TenderEvidenceCandidate) -> str:
    if candidate.clause_section is None:
        return candidate.excerpt
    return _inline_text(
        " ".join(
            [
                candidate.clause_section.heading,
                candidate.clause_section.body_text or candidate.excerpt,
            ]
        )
    )


def _contract_clause_tag_match_metadata(
    match: ContractClauseTagMatch,
) -> dict[str, Any]:
    return {
        "id": match.tag_id,
        "display_label": match.display_label,
        "matched_patterns": list(match.matched_patterns),
        "risk_lens": match.risk_lens,
        "suggested_proof_action": match.suggested_proof_action,
        "blocker_review_hint": match.blocker_review_hint,
    }


def _classification_request_for_candidate(
    candidate: TenderEvidenceCandidate,
    *,
    evidence_key: str,
    metadata: Mapping[str, Any],
) -> ContractClauseClassificationRequest:
    raw_tag_ids = metadata.get("contract_clause_ids", ())
    deterministic_tag_ids = (
        tuple(raw_tag_ids) if isinstance(raw_tag_ids, list | tuple) else ()
    )
    return ContractClauseClassificationRequest(
        evidence_key=evidence_key,
        document_id=candidate.document_id,
        chunk_id=candidate.chunk_id,
        page_start=candidate.page_start,
        page_end=candidate.page_end,
        excerpt=candidate.excerpt,
        source_label=candidate.source_label,
        deterministic_tag_ids=deterministic_tag_ids,
        clause_provenance=(
            _classification_provenance_for_segment(candidate.clause_section)
            if candidate.clause_section is not None
            else None
        ),
    )


def _classification_provenance_for_segment(
    segment: TenderClauseSegment,
) -> ContractClauseProvenance:
    return ContractClauseProvenance(
        document_id=segment.document_id,
        section_number=segment.section_number,
        heading=segment.heading,
        page_start=segment.page_start,
        page_end=segment.page_end,
        chunk_ids=segment.chunk_ids,
    )


def _apply_contract_clause_classification(
    metadata: dict[str, Any],
    classification: ContractClauseClassificationOutput,
) -> None:
    metadata["contract_clause_classification"] = (
        contract_clause_classification_metadata(classification)
    )
    current_tag_ids = list(metadata.get("contract_clause_ids", ()))
    if classification.tag_id not in current_tag_ids:
        current_tag_ids.append(classification.tag_id)
    metadata["contract_clause_ids"] = current_tag_ids


def _glossary_match_metadata(match: RegulatoryGlossaryMatch) -> dict[str, Any]:
    return {
        "id": match.entry_id,
        "display_label": match.display_label,
        "requirement_type": match.requirement_type.value,
        "matched_patterns": list(match.matched_patterns),
        "reference_hint": match.reference_hint,
        "suggested_proof_action": match.suggested_proof_action,
        "blocker_hint": match.blocker_hint,
    }


def _tender_clause_lines(
    chunks: list[RetrievedDocumentChunk],
) -> list[_TenderClauseLine]:
    lines: list[_TenderClauseLine] = []
    for chunk in sorted(chunks, key=_chunk_sort_key):
        for raw_line in chunk.text.replace("\r\n", "\n").split("\n"):
            line = raw_line.strip()
            if line:
                lines.append(_TenderClauseLine(chunk=chunk, text=line))
    return lines


def _chunk_sort_key(chunk: RetrievedDocumentChunk) -> tuple[str, int, int, str]:
    return (
        str(chunk.document_id),
        chunk.chunk_index,
        chunk.page_start,
        chunk.chunk_id,
    )


def _detect_clause_heading(
    lines: list[_TenderClauseLine],
    index: int,
) -> _DetectedTenderHeading | None:
    line = lines[index]
    numbered_heading = _numbered_clause_heading(line.text)
    if numbered_heading is not None:
        section_number, heading = numbered_heading
        heading_parts = [heading]
        consumed_line_count = _consume_heading_continuations(
            lines,
            index=index,
            heading_parts=heading_parts,
        )
        return _DetectedTenderHeading(
            section_number=section_number,
            heading=_inline_text(" ".join(heading_parts)),
            consumed_line_count=consumed_line_count,
        )

    if _is_unnumbered_clause_heading(line.text):
        heading_parts = [_strip_heading_suffix(line.text)]
        consumed_line_count = _consume_heading_continuations(
            lines,
            index=index,
            heading_parts=heading_parts,
        )
        return _DetectedTenderHeading(
            section_number=None,
            heading=_inline_text(" ".join(heading_parts)),
            consumed_line_count=consumed_line_count,
        )

    return None


def _numbered_clause_heading(text: str) -> tuple[str, str] | None:
    for pattern in (
        _SECTION_LABEL_HEADING_RE,
        _SWEDISH_SECTION_HEADING_RE,
        _NUMBERED_HEADING_RE,
    ):
        match = pattern.match(text)
        if match is None:
            continue
        heading = _strip_heading_suffix(match.group("heading"))
        if _looks_like_heading_title(heading):
            return match.group("section").rstrip("."), heading
    return None


def _looks_like_heading_title(text: str) -> bool:
    title = _strip_heading_suffix(text)
    if not title:
        return False
    if len(title) > 120:
        return False
    if len(title.split()) > 12:
        return False
    if title[-1] in ".!?;":
        return False

    lowered = f" {title.casefold()} "
    body_markers = (
        " must ",
        " shall ",
        " ska ",
        " skall ",
        " måste ",
        " maste ",
    )
    return not any(marker in lowered for marker in body_markers)


def _is_unnumbered_clause_heading(text: str) -> bool:
    if not _looks_like_heading_title(text):
        return False
    heading_key = _normalized_heading_key(text)
    return heading_key in _UNNUMBERED_CLAUSE_HEADINGS or any(
        keyword in heading_key for keyword in _UNNUMBERED_CLAUSE_HEADING_KEYWORDS
    )


def _consume_heading_continuations(
    lines: list[_TenderClauseLine],
    *,
    index: int,
    heading_parts: list[str],
) -> int:
    consumed_line_count = 1
    current_document_id = lines[index].chunk.document_id
    cursor = index + 1
    while cursor < len(lines):
        next_line = lines[cursor]
        if next_line.chunk.document_id != current_document_id:
            break
        if _numbered_clause_heading(next_line.text) is not None:
            break
        if not _is_heading_continuation(
            next_line.text,
            current_heading=_inline_text(" ".join(heading_parts)),
        ):
            break

        heading_parts.append(_strip_heading_suffix(next_line.text))
        consumed_line_count += 1
        cursor += 1

    return consumed_line_count


def _is_heading_continuation(text: str, *, current_heading: str) -> bool:
    continuation = _strip_heading_suffix(text)
    if not _looks_like_heading_title(continuation):
        return False
    if len(continuation.split()) > 4:
        return False

    first_character = continuation[0]
    last_current_word = current_heading.casefold().split()[-1]
    return (
        first_character.islower()
        or continuation.isupper()
        or last_current_word in _HEADING_CONTINUATION_ENDINGS
    )


def _strip_heading_suffix(text: str) -> str:
    return text.strip().rstrip(":").strip()


def _normalized_heading_key(text: str) -> str:
    return re.sub(r"\s+", " ", _strip_heading_suffix(text).casefold())


def _chunk_for_clause_sentence(
    sentence: str,
    *,
    segment: TenderClauseSegment,
    chunks_by_id: Mapping[UUID, RetrievedDocumentChunk],
) -> RetrievedDocumentChunk:
    sentence_text = _inline_text(sentence).casefold()
    for chunk_id in segment.chunk_ids:
        chunk = chunks_by_id[chunk_id]
        if sentence_text in _inline_text(chunk.text).casefold():
            return chunk
    return chunks_by_id[segment.chunk_ids[0]]


def _sentences(text: str) -> list[str]:
    return [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", _inline_text(text))
        if sentence.strip()
    ]


def _inline_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _category_for_sentence(sentence: str) -> str | None:
    requirement_type = _requirement_type_for_sentence(sentence)
    if requirement_type is not None:
        return _CATEGORY_BY_REQUIREMENT_TYPE[requirement_type]

    lowered = sentence.casefold()
    if any(term in lowered for term in ["must", "shall", "mandatory", "required"]):
        return "mandatory_requirement"
    if "award" in lowered or "evaluation" in lowered:
        return "award_criterion"
    if "deadline" in lowered or "submission" in lowered:
        return "submission_deadline"
    if "liability" in lowered or "penalty" in lowered:
        return "contract_risk"
    return None


def _requirement_type_for_sentence(sentence: str) -> RequirementType | None:
    glossary_matches = match_regulatory_glossary(sentence)
    if glossary_matches:
        return glossary_matches[0].requirement_type

    lowered = sentence.casefold()
    for requirement_type, keywords in _REQUIREMENT_TYPE_KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            return requirement_type
    return None


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").upper()
    return slug or "UNKNOWN"


__all__ = [
    "TenderEvidenceUpsertResult",
    "TenderClauseSegment",
    "TenderEvidenceCandidate",
    "build_tender_clause_segments",
    "build_tender_evidence_candidates",
    "build_tender_evidence_items",
    "get_tender_evidence_item_by_key",
    "upsert_tender_evidence_items",
]
