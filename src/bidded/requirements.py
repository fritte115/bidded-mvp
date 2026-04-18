from __future__ import annotations

from enum import StrEnum


class RequirementType(StrEnum):
    """Procurement requirement classifications shared across Bidded outputs."""

    SHALL_REQUIREMENT = "shall_requirement"
    QUALIFICATION_REQUIREMENT = "qualification_requirement"
    EXCLUSION_GROUND = "exclusion_ground"
    FINANCIAL_STANDING = "financial_standing"
    LEGAL_OR_REGULATORY_REFERENCE = "legal_or_regulatory_reference"
    QUALITY_MANAGEMENT = "quality_management"
    SUBMISSION_DOCUMENT = "submission_document"
    CONTRACT_OBLIGATION = "contract_obligation"


REQUIREMENT_TYPE_VALUES: tuple[str, ...] = tuple(
    requirement_type.value for requirement_type in RequirementType
)


__all__ = [
    "REQUIREMENT_TYPE_VALUES",
    "RequirementType",
]
