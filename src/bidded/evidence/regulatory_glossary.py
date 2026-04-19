from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from bidded.requirements import RequirementType


@dataclass(frozen=True)
class RegulatoryGlossaryEntry:
    entry_id: str
    match_patterns: tuple[str, ...]
    requirement_type: RequirementType
    display_label: str
    reference_hint: str
    suggested_proof_action: str
    blocker_hint: str


@dataclass(frozen=True)
class RegulatoryGlossaryMatch:
    entry_id: str
    requirement_type: RequirementType
    display_label: str
    reference_hint: str
    suggested_proof_action: str
    blocker_hint: str
    matched_patterns: tuple[str, ...]


REGULATORY_GLOSSARY: tuple[RegulatoryGlossaryEntry, ...] = (
    RegulatoryGlossaryEntry(
        entry_id="financial_standing",
        match_patterns=(
            "credit report",
            "credit check",
            "financial standing",
            "economic standing",
            "annual turnover",
            "kreditupplysning",
            "ekonomisk ställning",
            "finansiell ställning",
            "omsättning",
        ),
        requirement_type=RequirementType.FINANCIAL_STANDING,
        display_label="Financial standing",
        reference_hint="Check tender language on economic and financial capacity.",
        suggested_proof_action=(
            "Prepare current credit report and financial capacity evidence."
        ),
        blocker_hint="Missing financial standing proof can block qualification.",
    ),
    RegulatoryGlossaryEntry(
        entry_id="exclusion_grounds",
        match_patterns=(
            "bankrupt",
            "bankruptcy",
            "insolvency",
            "compulsory liquidation",
            "composition with creditors",
            "exclusion grounds",
            "konkurs",
            "tvångslikvidation",
            "ackord",
            "uteslutningsgrund",
        ),
        requirement_type=RequirementType.EXCLUSION_GROUND,
        display_label="Exclusion grounds",
        reference_hint="Check whether the tender names mandatory exclusion grounds.",
        suggested_proof_action=(
            "Confirm no exclusion ground applies and prepare standard declarations."
        ),
        blocker_hint="Confirmed exclusion grounds can block bid submission.",
    ),
    RegulatoryGlossaryEntry(
        entry_id="professional_misconduct",
        match_patterns=(
            "professional misconduct",
            "grave professional misconduct",
            "criminal professional conduct",
            "professional conduct",
            "brott avseende yrkesutövning",
            "allvarligt fel i yrkesutövningen",
            "yrkesutövning",
        ),
        requirement_type=RequirementType.EXCLUSION_GROUND,
        display_label="Professional misconduct",
        reference_hint=(
            "Check misconduct language separately from financial exclusion grounds."
        ),
        suggested_proof_action=(
            "Confirm legal status and prepare declarations on professional conduct."
        ),
        blocker_hint="Unresolved professional misconduct can block qualification.",
    ),
    RegulatoryGlossaryEntry(
        entry_id="quality_management_sosfs",
        match_patterns=(
            "quality management system",
            "quality system",
            "iso 9001",
            "sosfs 2011:9",
            "ledningssystem",
            "kvalitetsledningssystem",
            "systematiskt kvalitetsarbete",
        ),
        requirement_type=RequirementType.QUALITY_MANAGEMENT,
        display_label="Quality management / SOSFS",
        reference_hint="Check quality-system requirements, including SOSFS references.",
        suggested_proof_action=(
            "Prepare quality management certificates, routines, and ownership proof."
        ),
        blocker_hint="Missing mandatory quality-system proof can block qualification.",
    ),
    RegulatoryGlossaryEntry(
        entry_id="submission_documents",
        match_patterns=(
            "submission must include",
            "documents must be submitted",
            "shall include",
            "signed data processing agreement",
            "anbudet ska innehålla",
            "anbudet skall innehålla",
            "ska bifoga",
            "skall bifoga",
            "undertecknad",
            "bilaga",
            "ska lämnas in",
        ),
        requirement_type=RequirementType.SUBMISSION_DOCUMENT,
        display_label="Submission documents",
        reference_hint="Check required forms, attachments, signatures, and deadlines.",
        suggested_proof_action=(
            "Create a submission checklist with all required signed attachments."
        ),
        blocker_hint="Missing required submission documents can make the bid invalid.",
    ),
    RegulatoryGlossaryEntry(
        entry_id="contract_reporting_obligations",
        match_patterns=(
            "contract reporting",
            "reporting obligations",
            "monthly report",
            "quarterly report",
            "during the contract",
            "agreement period",
            "under avtalstiden",
            "avtalsrapportering",
            "månadsrapport",
            "kvartalsrapport",
            "rapportera",
        ),
        requirement_type=RequirementType.CONTRACT_OBLIGATION,
        display_label="Contract reporting obligations",
        reference_hint="Check reporting duties that apply after contract award.",
        suggested_proof_action=(
            "Confirm delivery team can produce the required contract reports."
        ),
        blocker_hint="Reporting duties are delivery risks unless marked mandatory.",
    ),
)


def match_regulatory_glossary(text: str) -> tuple[RegulatoryGlossaryMatch, ...]:
    normalized_text = _normalize_for_matching(text)
    matches: list[RegulatoryGlossaryMatch] = []
    for entry in REGULATORY_GLOSSARY:
        matched_patterns = tuple(
            pattern
            for pattern in entry.match_patterns
            if _normalize_for_matching(pattern) in normalized_text
        )
        if not matched_patterns:
            continue
        matches.append(
            RegulatoryGlossaryMatch(
                entry_id=entry.entry_id,
                requirement_type=entry.requirement_type,
                display_label=entry.display_label,
                reference_hint=entry.reference_hint,
                suggested_proof_action=entry.suggested_proof_action,
                blocker_hint=entry.blocker_hint,
                matched_patterns=matched_patterns,
            )
        )
    return tuple(matches)


def _normalize_for_matching(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_diacritics = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return re.sub(r"\s+", " ", without_diacritics).strip()


__all__ = [
    "REGULATORY_GLOSSARY",
    "RegulatoryGlossaryEntry",
    "RegulatoryGlossaryMatch",
    "match_regulatory_glossary",
]
