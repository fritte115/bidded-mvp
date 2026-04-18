from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from bidded.orchestration.state import EvidenceItemState, EvidenceSourceType
from bidded.requirements import RequirementType


class RequirementEvidenceContext(BaseModel):
    """Compact requirement-focused view of evidence passed to reasoning agents."""

    model_config = ConfigDict(extra="forbid")

    evidence_key: str = Field(min_length=1)
    source_type: EvidenceSourceType
    evidence_id: UUID | None = None
    source_label: str = Field(min_length=1)
    requirement_type: RequirementType | None = None
    regulatory_glossary_ids: tuple[str, ...] = ()
    regulatory_glossary: tuple[dict[str, Any], ...] = ()


def build_requirement_context(
    evidence_board: Sequence[EvidenceItemState],
) -> tuple[RequirementEvidenceContext, ...]:
    """Build the requirement and glossary context agents need for reasoning."""

    contexts: list[RequirementEvidenceContext] = []
    for evidence in evidence_board:
        glossary_ids = _string_tuple(
            evidence.source_metadata.get("regulatory_glossary_ids", ())
        )
        glossary = _dict_tuple(evidence.source_metadata.get("regulatory_glossary", ()))
        if evidence.requirement_type is None and not glossary_ids and not glossary:
            continue

        contexts.append(
            RequirementEvidenceContext(
                evidence_key=evidence.evidence_key,
                source_type=evidence.source_type,
                evidence_id=evidence.evidence_id,
                source_label=str(evidence.source_metadata["source_label"]),
                requirement_type=evidence.requirement_type,
                regulatory_glossary_ids=glossary_ids,
                regulatory_glossary=glossary,
            )
        )
    return tuple(contexts)


def _string_tuple(raw_values: object) -> tuple[str, ...]:
    if not isinstance(raw_values, (list, tuple)):
        return ()
    return tuple(str(value) for value in raw_values if str(value))


def _dict_tuple(raw_values: object) -> tuple[dict[str, Any], ...]:
    if not isinstance(raw_values, (list, tuple)):
        return ()
    return tuple(dict(value) for value in raw_values if isinstance(value, dict))


__all__ = [
    "RequirementEvidenceContext",
    "build_requirement_context",
]
