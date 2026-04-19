from __future__ import annotations

from bidded.evidence.contract_clause_tags import (
    CONTRACT_CLAUSE_TAGS,
    match_contract_clause_tags,
)


def test_contract_clause_tag_taxonomy_covers_initial_tags() -> None:
    tags_by_id = {tag.tag_id: tag for tag in CONTRACT_CLAUSE_TAGS}

    assert tuple(tags_by_id) == (
        "penalties_liquidated_damages",
        "liability_caps",
        "gdpr_dpa",
        "subprocessors",
        "confidentiality",
        "insurance",
        "gross_negligence_wilful_misconduct",
        "public_access",
        "reporting",
        "termination",
        "subcontractors",
        "unknown_contract_clause",
    )

    for tag in CONTRACT_CLAUSE_TAGS:
        assert tag.display_label
        assert tag.match_patterns
        assert tag.risk_lens
        assert tag.suggested_proof_action
        assert tag.blocker_review_hint


def test_contract_clause_tags_match_normalized_swedish_diacritics() -> None:
    matches = match_contract_clause_tags(
        "Leverantören accepterar ANSVARSBEGRÄNSNING och ansvarsförsäkring."
    )

    assert [match.tag_id for match in matches] == ["liability_caps", "insurance"]
    assert matches[0].matched_patterns == ("ansvarsbegränsning",)
    assert matches[1].matched_patterns == (
        "försäkring",
        "ansvarsförsäkring",
    )


def test_contract_clause_tags_return_empty_tuple_for_no_match() -> None:
    assert match_contract_clause_tags(
        "The kickoff workshop introduces project roles and contact details."
    ) == ()


def test_contract_clause_tags_multiple_matches_follow_curated_precedence() -> None:
    matches = match_contract_clause_tags(
        "The contract has a liability cap and liquidated damages for delay."
    )

    assert [match.tag_id for match in matches] == [
        "penalties_liquidated_damages",
        "liability_caps",
    ]


def test_contract_clause_tags_distinguish_subprocessors_from_subcontractors() -> None:
    matches = match_contract_clause_tags(
        "The DPA requires approval for subprocessors and named subcontractors."
    )

    assert [match.tag_id for match in matches] == [
        "gdpr_dpa",
        "subprocessors",
        "subcontractors",
    ]
