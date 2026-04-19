from __future__ import annotations

import re
import unicodedata
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from bidded.evidence.regulatory_glossary import match_regulatory_glossary
from bidded.orchestration.state import (
    DocumentChunkState,
    EvidenceItemState,
    EvidenceSourceType,
)
from bidded.requirements import RequirementType

RECALL_AUDIT_REQUIREMENT_TYPES: tuple[RequirementType, ...] = (
    RequirementType.SUBMISSION_DOCUMENT,
    RequirementType.QUALIFICATION_REQUIREMENT,
    RequirementType.FINANCIAL_STANDING,
    RequirementType.EXCLUSION_GROUND,
    RequirementType.QUALITY_MANAGEMENT,
)
_RECALL_REQUIREMENT_KEYWORDS: dict[RequirementType, tuple[str, ...]] = {
    RequirementType.SUBMISSION_DOCUMENT: (
        "submission must include",
        "documents must be submitted",
        "shall include",
        "signed data processing agreement",
        "anbudet ska innehalla",
        "ska bifoga",
        "undertecknad",
        "bilaga",
    ),
    RequirementType.QUALIFICATION_REQUIREMENT: (
        "qualification",
        "qualified",
        "public sector references",
        "reference assignments",
        "comparable references",
        "demonstrate experience",
        "kvalificeringskrav",
        "referensuppdrag",
        "kompetens",
        "kapacitet",
    ),
    RequirementType.FINANCIAL_STANDING: (
        "credit report",
        "credit check",
        "financial standing",
        "financial capacity",
        "economic standing",
        "annual turnover",
        "kreditupplysning",
        "ekonomisk stallning",
        "finansiell stallning",
        "omsattning",
    ),
    RequirementType.EXCLUSION_GROUND: (
        "bankrupt",
        "bankruptcy",
        "excluded",
        "exclusion ground",
        "insolvency",
        "compulsory liquidation",
        "composition with creditors",
        "konkurs",
        "tvangslikvidation",
        "ackord",
        "uteslutningsgrund",
    ),
    RequirementType.QUALITY_MANAGEMENT: (
        "quality management system",
        "quality system",
        "iso 9001",
        "sosfs 2011:9",
        "ledningssystem",
        "kvalitetsledningssystem",
        "systematiskt kvalitetsarbete",
    ),
}


class EvidenceRecallWarning(BaseModel):
    """Structured warning for important tender signals missing from evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement_type: RequirementType
    severity: Literal["warning"] = "warning"
    evidence_state: Literal["missing_from_evidence_board"] = (
        "missing_from_evidence_board"
    )
    missing_info: str = Field(min_length=1)
    source_label: str = Field(min_length=1)
    document_id: UUID
    chunk_id: UUID
    page_start: int = Field(gt=0)
    page_end: int = Field(gt=0)
    matched_text: str = Field(min_length=1)
    glossary_ids: tuple[str, ...] = ()


def audit_evidence_recall(
    *,
    chunks: list[DocumentChunkState],
    evidence_board: list[EvidenceItemState],
) -> tuple[EvidenceRecallWarning, ...]:
    """Find important tender requirement signals absent from tender evidence."""

    covered_requirement_types = {
        item.requirement_type
        for item in evidence_board
        if item.source_type is EvidenceSourceType.TENDER_DOCUMENT
        and item.requirement_type is not None
    }
    missing_requirement_types = set(RECALL_AUDIT_REQUIREMENT_TYPES).difference(
        covered_requirement_types
    )
    warnings: list[EvidenceRecallWarning] = []
    warned_types: set[RequirementType] = set()

    for chunk in chunks:
        for signal in _chunk_requirement_signals(chunk):
            if signal.requirement_type not in missing_requirement_types:
                continue
            if signal.requirement_type in warned_types:
                continue

            warnings.append(
                EvidenceRecallWarning(
                    requirement_type=signal.requirement_type,
                    missing_info=(
                        "Evidence recall found tender text suggesting "
                        f"{signal.requirement_type.value}, but no tender "
                        "evidence item with that requirement_type is present."
                    ),
                    source_label=str(
                        chunk.metadata.get("source_label") or "tender document"
                    ),
                    document_id=chunk.document_id,
                    chunk_id=chunk.chunk_id,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    matched_text=signal.matched_text,
                    glossary_ids=signal.glossary_ids,
                )
            )
            warned_types.add(signal.requirement_type)

    return tuple(warnings)


class _RequirementSignal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement_type: RequirementType
    matched_text: str = Field(min_length=1)
    glossary_ids: tuple[str, ...] = ()


def _chunk_requirement_signals(
    chunk: DocumentChunkState,
) -> tuple[_RequirementSignal, ...]:
    glossary_matches = match_regulatory_glossary(chunk.text)
    signals: list[_RequirementSignal] = []
    seen_types: set[RequirementType] = set()
    for match in glossary_matches:
        if match.requirement_type not in RECALL_AUDIT_REQUIREMENT_TYPES:
            continue
        if match.requirement_type in seen_types:
            continue

        signals.append(
            _RequirementSignal(
                requirement_type=match.requirement_type,
                matched_text=", ".join(match.matched_patterns),
                glossary_ids=(match.entry_id,),
            )
        )
        seen_types.add(match.requirement_type)

    normalized_text = _normalize_for_matching(chunk.text)
    for requirement_type, keywords in _RECALL_REQUIREMENT_KEYWORDS.items():
        if requirement_type in seen_types:
            continue
        matched_keyword = next(
            (
                keyword
                for keyword in keywords
                if _normalize_for_matching(keyword) in normalized_text
            ),
            None,
        )
        if matched_keyword is None:
            continue

        signals.append(
            _RequirementSignal(
                requirement_type=requirement_type,
                matched_text=matched_keyword,
            )
        )
        seen_types.add(requirement_type)

    return tuple(signals)


def _normalize_for_matching(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_diacritics = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    return re.sub(r"\s+", " ", without_diacritics).strip()


__all__ = [
    "EvidenceRecallWarning",
    "RECALL_AUDIT_REQUIREMENT_TYPES",
    "audit_evidence_recall",
]
