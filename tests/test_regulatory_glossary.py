from __future__ import annotations

from bidded.agents import RequirementType
from bidded.evidence.regulatory_glossary import (
    REGULATORY_GLOSSARY,
    match_regulatory_glossary,
)


def test_regulatory_glossary_entries_cover_initial_procurement_phrases() -> None:
    entries_by_id = {entry.entry_id: entry for entry in REGULATORY_GLOSSARY}

    assert set(entries_by_id) == {
        "financial_standing",
        "exclusion_grounds",
        "professional_misconduct",
        "quality_management_sosfs",
        "submission_documents",
        "contract_reporting_obligations",
    }
    assert entries_by_id["financial_standing"].requirement_type is (
        RequirementType.FINANCIAL_STANDING
    )
    assert entries_by_id["exclusion_grounds"].requirement_type is (
        RequirementType.EXCLUSION_GROUND
    )
    assert entries_by_id["professional_misconduct"].requirement_type is (
        RequirementType.EXCLUSION_GROUND
    )
    assert entries_by_id["quality_management_sosfs"].requirement_type is (
        RequirementType.QUALITY_MANAGEMENT
    )
    assert entries_by_id["submission_documents"].requirement_type is (
        RequirementType.SUBMISSION_DOCUMENT
    )
    assert entries_by_id["contract_reporting_obligations"].requirement_type is (
        RequirementType.CONTRACT_OBLIGATION
    )

    for entry in REGULATORY_GLOSSARY:
        assert entry.entry_id
        assert entry.match_patterns
        assert entry.display_label
        assert entry.reference_hint
        assert entry.suggested_proof_action
        assert entry.blocker_hint


def test_regulatory_glossary_matches_normalized_swedish_diacritics() -> None:
    matches = match_regulatory_glossary(
        "Anbudsgivaren ska uppvisa KREDITUPPLYSNING for ekonomisk ställning."
    )

    assert [match.entry_id for match in matches] == ["financial_standing"]
    assert matches[0].requirement_type is RequirementType.FINANCIAL_STANDING
    assert matches[0].matched_patterns == (
        "kreditupplysning",
        "ekonomisk ställning",
    )


def test_regulatory_glossary_returns_empty_tuple_for_no_match() -> None:
    assert match_regulatory_glossary(
        "The kickoff workshop introduces project roles and contact details."
    ) == ()


def test_regulatory_glossary_multiple_matches_follow_curated_precedence() -> None:
    matches = match_regulatory_glossary(
        "During the contract, the supplier shall include a quarterly report."
    )

    assert [match.entry_id for match in matches] == [
        "submission_documents",
        "contract_reporting_obligations",
    ]
