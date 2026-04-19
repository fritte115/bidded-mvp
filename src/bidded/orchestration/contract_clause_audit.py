from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bidded.evidence.contract_clause_tags import CONTRACT_CLAUSE_TAGS
from bidded.evidence.tender_document import build_tender_clause_segments
from bidded.orchestration.state import (
    DocumentChunkState,
    EvidenceItemState,
    EvidenceSourceType,
)
from bidded.retrieval import RetrievedDocumentChunk

AUDITED_CONTRACT_CLAUSE_TAG_IDS: tuple[str, ...] = (
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
)

_TAG_BY_ID = {tag.tag_id: tag for tag in CONTRACT_CLAUSE_TAGS}
_EXTRA_SIGNAL_PATTERNS: dict[str, tuple[str, ...]] = {
    "liability_caps": (
        "liability",
        "ansvar",
        "ansvarsbegränsning",
        "ansvarsbegransning",
    ),
    "penalties_liquidated_damages": (
        "penalties",
        "förseningsvite",
        "forseningsvite",
    ),
    "gdpr_dpa": (
        "data protection",
        "dataskydd",
    ),
}
_PAYMENT_DEADLINE_PATTERNS = (
    "payment",
    "invoice",
    "betalning",
    "faktura",
)
_EXPECTED_TERMS_BY_TAG: dict[str, tuple[str, ...]] = {
    "penalties_liquidated_damages": ("penalty_amount", "recurrence"),
    "liability_caps": ("liability_cap", "recurrence"),
}


class ContractClauseCoverageWarning(BaseModel):
    """Structured warning for missed contract-clause coverage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    severity: Literal["warning"] = "warning"
    evidence_state: Literal[
        "missing_clause_body",
        "missing_from_evidence_board",
        "missing_expected_terms",
    ]
    missing_info: str = Field(min_length=1)
    source_label: str = Field(min_length=1)
    document_id: UUID
    chunk_id: UUID
    page_start: int = Field(gt=0)
    page_end: int = Field(gt=0)
    matched_text: str = Field(min_length=1)
    contract_clause_id: str | None = None
    contract_clause_label: str | None = None
    heading: str | None = None
    section_number: str | None = None
    evidence_key: str | None = None
    expected_terms: tuple[str, ...] = ()
    missing_terms: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_page_range(self) -> ContractClauseCoverageWarning:
        if self.page_end < self.page_start:
            raise ValueError("page_end must be greater than or equal to page_start")
        return self


def audit_contract_clause_coverage(
    *,
    chunks: Sequence[DocumentChunkState],
    evidence_board: Sequence[EvidenceItemState],
) -> tuple[ContractClauseCoverageWarning, ...]:
    """Find contract-risk headings, signals, and terms missed by extraction."""

    warnings: list[ContractClauseCoverageWarning] = []
    covered_tag_ids = _covered_contract_clause_ids(evidence_board)
    heading_body_warnings = _heading_body_warnings(chunks)
    warnings.extend(heading_body_warnings)
    heading_body_tag_ids = {
        warning.contract_clause_id
        for warning in heading_body_warnings
        if warning.contract_clause_id is not None
    }

    warnings.extend(
        _missing_signal_warnings(
            chunks,
            covered_tag_ids=covered_tag_ids,
            already_warned_tag_ids=heading_body_tag_ids,
        )
    )
    warnings.extend(_missing_expected_term_warnings(evidence_board))
    warnings.extend(
        _missing_payment_deadline_signal_warnings(
            chunks,
            evidence_board=evidence_board,
        )
    )
    return tuple(warnings)


def _heading_body_warnings(
    chunks: Sequence[DocumentChunkState],
) -> tuple[ContractClauseCoverageWarning, ...]:
    warnings: list[ContractClauseCoverageWarning] = []
    for segment in build_tender_clause_segments(_retrieved_chunks_from_state(chunks)):
        if segment.body_text:
            continue
        matched_tag_ids = _audited_tag_ids_for_text(segment.heading)
        for tag_id in matched_tag_ids:
            chunk_id = segment.chunk_ids[0]
            warnings.append(
                ContractClauseCoverageWarning(
                    evidence_state="missing_clause_body",
                    missing_info=(
                        f"Contract clause heading '{segment.heading}' was detected "
                        "without body text, so clause coverage should be reviewed."
                    ),
                    source_label=_source_label_for_chunk_id(chunks, chunk_id),
                    document_id=segment.document_id,
                    chunk_id=chunk_id,
                    page_start=segment.page_start,
                    page_end=segment.page_end,
                    matched_text=segment.heading,
                    contract_clause_id=tag_id,
                    contract_clause_label=_tag_label(tag_id),
                    heading=segment.heading,
                    section_number=segment.section_number,
                )
            )
    return tuple(warnings)


def _missing_signal_warnings(
    chunks: Sequence[DocumentChunkState],
    *,
    covered_tag_ids: frozenset[str],
    already_warned_tag_ids: set[str],
) -> tuple[ContractClauseCoverageWarning, ...]:
    warnings: list[ContractClauseCoverageWarning] = []
    warned_tag_ids = set(already_warned_tag_ids)
    for chunk in sorted(chunks, key=_chunk_sort_key):
        matched_tag_ids = _audited_tag_ids_for_text(chunk.text)
        for tag_id in matched_tag_ids:
            if tag_id in covered_tag_ids or tag_id in warned_tag_ids:
                continue
            warnings.append(
                ContractClauseCoverageWarning(
                    evidence_state="missing_from_evidence_board",
                    missing_info=(
                        "Contract clause audit found tender text suggesting "
                        f"{_tag_label(tag_id)}, but no tender evidence item with "
                        "that contract clause tag is present."
                    ),
                    source_label=_source_label(chunk.metadata),
                    document_id=chunk.document_id,
                    chunk_id=chunk.chunk_id,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    matched_text=_first_matched_pattern(tag_id, chunk.text),
                    contract_clause_id=tag_id,
                    contract_clause_label=_tag_label(tag_id),
                )
            )
            warned_tag_ids.add(tag_id)
    return tuple(warnings)


def _missing_expected_term_warnings(
    evidence_board: Sequence[EvidenceItemState],
) -> tuple[ContractClauseCoverageWarning, ...]:
    warnings: list[ContractClauseCoverageWarning] = []
    for item in evidence_board:
        if item.source_type is not EvidenceSourceType.TENDER_DOCUMENT:
            continue

        expected_terms = _expected_terms_for_evidence(item)
        if not expected_terms:
            continue

        missing_terms = tuple(
            term
            for term in expected_terms
            if not _has_expected_term(item.metadata, term)
        )
        if not missing_terms:
            continue

        warnings.append(
            ContractClauseCoverageWarning(
                evidence_state="missing_expected_terms",
                missing_info=(
                    f"Contract clause evidence {item.evidence_key} is tagged or "
                    "signalled as contract-risk text but lacks expected extracted "
                    f"term(s): {', '.join(missing_terms)}."
                ),
                source_label=_source_label(item.source_metadata),
                document_id=_required_uuid(item.document_id, "document_id"),
                chunk_id=_required_uuid(item.chunk_id, "chunk_id"),
                page_start=_required_int(item.page_start, "page_start"),
                page_end=_required_int(item.page_end, "page_end"),
                matched_text=item.excerpt,
                contract_clause_id=_primary_term_tag_id(item),
                contract_clause_label=_term_warning_label(item),
                evidence_key=item.evidence_key,
                expected_terms=expected_terms,
                missing_terms=missing_terms,
            )
        )
    return tuple(warnings)


def _missing_payment_deadline_signal_warnings(
    chunks: Sequence[DocumentChunkState],
    *,
    evidence_board: Sequence[EvidenceItemState],
) -> tuple[ContractClauseCoverageWarning, ...]:
    if _payment_deadline_is_covered(evidence_board):
        return ()

    for chunk in sorted(chunks, key=_chunk_sort_key):
        matched_text = _first_matching_pattern(_PAYMENT_DEADLINE_PATTERNS, chunk.text)
        if matched_text is None:
            continue
        return (
            ContractClauseCoverageWarning(
                evidence_state="missing_expected_terms",
                missing_info=(
                    "Contract clause audit found payment or invoice language, "
                    "but no payment_deadline extracted term is present."
                ),
                source_label=_source_label(chunk.metadata),
                document_id=chunk.document_id,
                chunk_id=chunk.chunk_id,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                matched_text=matched_text,
                contract_clause_label="Payment terms",
                expected_terms=("payment_deadline",),
                missing_terms=("payment_deadline",),
            ),
        )
    return ()


def _covered_contract_clause_ids(
    evidence_board: Sequence[EvidenceItemState],
) -> frozenset[str]:
    covered: set[str] = set()
    for item in evidence_board:
        if item.source_type is not EvidenceSourceType.TENDER_DOCUMENT:
            continue
        covered.update(_evidence_contract_clause_ids(item))
    return frozenset(covered)


def _evidence_contract_clause_ids(item: EvidenceItemState) -> tuple[str, ...]:
    raw_values = item.metadata.get("contract_clause_ids", ())
    clause_ids = _string_tuple(raw_values)
    classification = item.metadata.get("contract_clause_classification")
    if isinstance(classification, Mapping):
        tag_id = classification.get("tag_id")
        if isinstance(tag_id, str) and tag_id:
            clause_ids = (*clause_ids, tag_id)
    return tuple(dict.fromkeys(clause_ids))


def _expected_terms_for_evidence(item: EvidenceItemState) -> tuple[str, ...]:
    expected_terms: list[str] = []
    for tag_id in _evidence_contract_clause_ids(item):
        expected_terms.extend(_EXPECTED_TERMS_BY_TAG.get(tag_id, ()))
    if _has_payment_signal(item.excerpt):
        expected_terms.append("payment_deadline")
    return tuple(dict.fromkeys(expected_terms))


def _primary_term_tag_id(item: EvidenceItemState) -> str | None:
    for tag_id in _evidence_contract_clause_ids(item):
        if tag_id in _EXPECTED_TERMS_BY_TAG:
            return tag_id
    return None


def _term_warning_label(item: EvidenceItemState) -> str | None:
    primary_tag_id = _primary_term_tag_id(item)
    if primary_tag_id is not None:
        return _tag_label(primary_tag_id)
    if _has_payment_signal(item.excerpt):
        return "Payment terms"
    return None


def _has_expected_term(metadata: Mapping[str, Any], expected_term: str) -> bool:
    extracted_terms = metadata.get("extracted_terms")
    if not isinstance(extracted_terms, Mapping):
        return False

    if expected_term == "recurrence":
        return bool(_mapping_sequence(extracted_terms.get("recurrence_or_cap_phrases")))

    if expected_term in {"penalty_amount", "liability_cap"}:
        return any(
            term.get("context") == expected_term
            for term in _mapping_sequence(extracted_terms.get("money_amounts"))
        )

    if expected_term == "payment_deadline":
        return any(
            term.get("context") == "payment_deadline"
            for term in _mapping_sequence(extracted_terms.get("day_deadlines"))
        )

    return False


def _payment_deadline_is_covered(
    evidence_board: Sequence[EvidenceItemState],
) -> bool:
    return any(
        item.source_type is EvidenceSourceType.TENDER_DOCUMENT
        and _has_expected_term(item.metadata, "payment_deadline")
        for item in evidence_board
    )


def _audited_tag_ids_for_text(text: str) -> tuple[str, ...]:
    normalized_text = _normalize_for_matching(text)
    matched_tag_ids: list[str] = []
    for tag_id in AUDITED_CONTRACT_CLAUSE_TAG_IDS:
        patterns = _signal_patterns_for_tag(tag_id)
        if any(
            _normalize_for_matching(pattern) in normalized_text for pattern in patterns
        ):
            matched_tag_ids.append(tag_id)
    return tuple(matched_tag_ids)


def _signal_patterns_for_tag(tag_id: str) -> tuple[str, ...]:
    tag = _TAG_BY_ID[tag_id]
    return (*tag.match_patterns, *_EXTRA_SIGNAL_PATTERNS.get(tag_id, ()))


def _first_matched_pattern(tag_id: str, text: str) -> str:
    matched_pattern = _first_matching_pattern(_signal_patterns_for_tag(tag_id), text)
    return matched_pattern or _tag_label(tag_id)


def _first_matching_pattern(patterns: Sequence[str], text: str) -> str | None:
    normalized_text = _normalize_for_matching(text)
    return next(
        (
            pattern
            for pattern in patterns
            if _normalize_for_matching(pattern) in normalized_text
        ),
        None,
    )


def _has_payment_signal(text: str) -> bool:
    return _first_matching_pattern(_PAYMENT_DEADLINE_PATTERNS, text) is not None


def _retrieved_chunks_from_state(
    chunks: Sequence[DocumentChunkState],
) -> list[RetrievedDocumentChunk]:
    return [
        RetrievedDocumentChunk(
            chunk_id=str(chunk.chunk_id),
            document_id=chunk.document_id,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            chunk_index=chunk.chunk_index,
            text=chunk.text,
            metadata=dict(chunk.metadata),
        )
        for chunk in chunks
    ]


def _source_label_for_chunk_id(
    chunks: Sequence[DocumentChunkState],
    chunk_id: UUID,
) -> str:
    for chunk in chunks:
        if chunk.chunk_id == chunk_id:
            return _source_label(chunk.metadata)
    return "tender document"


def _source_label(metadata: Mapping[str, Any]) -> str:
    return str(metadata.get("source_label") or "tender document")


def _tag_label(tag_id: str) -> str:
    return _TAG_BY_ID[tag_id].display_label


def _chunk_sort_key(chunk: DocumentChunkState) -> tuple[str, int, int, str]:
    return (
        str(chunk.document_id),
        chunk.chunk_index,
        chunk.page_start,
        str(chunk.chunk_id),
    )


def _string_tuple(raw_values: object) -> tuple[str, ...]:
    if not isinstance(raw_values, (list, tuple)):
        return ()
    return tuple(str(value) for value in raw_values if str(value))


def _mapping_sequence(raw_values: object) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(raw_values, (list, tuple)):
        return ()
    return tuple(value for value in raw_values if isinstance(value, Mapping))


def _required_uuid(value: UUID | None, field_name: str) -> UUID:
    if value is None:
        raise ValueError(f"tender evidence missing {field_name}")
    return value


def _required_int(value: int | None, field_name: str) -> int:
    if value is None:
        raise ValueError(f"tender evidence missing {field_name}")
    return value


def _normalize_for_matching(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_diacritics = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return re.sub(r"\s+", " ", without_diacritics).strip()


__all__ = [
    "AUDITED_CONTRACT_CLAUSE_TAG_IDS",
    "ContractClauseCoverageWarning",
    "audit_contract_clause_coverage",
]
