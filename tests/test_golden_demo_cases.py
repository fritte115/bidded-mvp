from __future__ import annotations

from bidded.fixtures.golden_cases import (
    GoldenDemoCase,
    golden_demo_cases,
)
from bidded.orchestration import EvidenceSourceType, Verdict


def test_golden_demo_cases_cover_core_decision_behaviors() -> None:
    cases = golden_demo_cases()

    assert {case.case_id for case in cases} == {
        "obvious_bid",
        "hard_compliance_no_bid",
        "conditional_bid_next_actions",
        "conflicting_evidence_needs_review",
        "missing_company_evidence",
        "unsupported_agent_claim_rejection",
    }
    assert {case.case_id: case.expected.verdict for case in cases} == {
        "obvious_bid": Verdict.BID,
        "hard_compliance_no_bid": Verdict.NO_BID,
        "conditional_bid_next_actions": Verdict.CONDITIONAL_BID,
        "conflicting_evidence_needs_review": Verdict.NEEDS_HUMAN_REVIEW,
        "missing_company_evidence": Verdict.CONDITIONAL_BID,
        "unsupported_agent_claim_rejection": Verdict.CONDITIONAL_BID,
    }


def test_golden_demo_cases_are_typed_unique_and_evidence_backed() -> None:
    cases = golden_demo_cases()

    assert cases
    assert len({case.case_id for case in cases}) == len(cases)
    for case in cases:
        assert isinstance(case, GoldenDemoCase)
        assert case.tender_evidence
        assert case.expected.required_evidence_refs
        assert len({item.evidence_key for item in case.evidence_board}) == len(
            case.evidence_board
        )

        evidence_by_key = {item.evidence_key: item for item in case.evidence_board}
        for evidence_ref in case.expected.required_evidence_refs:
            cited_item = evidence_by_key[evidence_ref.evidence_key]
            assert cited_item.source_type is evidence_ref.source_type
            assert cited_item.evidence_id == evidence_ref.evidence_id


def test_golden_demo_cases_keep_missing_company_evidence_non_gating() -> None:
    case = _case("missing_company_evidence")

    assert case.expected.verdict is Verdict.CONDITIONAL_BID
    assert case.expected.allowed_verdicts == (
        Verdict.CONDITIONAL_BID,
        Verdict.NEEDS_HUMAN_REVIEW,
    )
    assert case.expected.blockers == ()
    assert case.company_evidence == ()
    assert case.expected.missing_info
    assert case.expected.recommended_actions
    assert {
        evidence_ref.source_type
        for evidence_ref in case.expected.required_evidence_refs
    } == {EvidenceSourceType.TENDER_DOCUMENT}


def test_golden_demo_cases_define_verdict_regression_expectations() -> None:
    hard_blocker = _case("hard_compliance_no_bid")

    for case in golden_demo_cases():
        assert case.expected.verdict in case.expected.allowed_verdicts

    assert hard_blocker.expected.allowed_verdicts == (Verdict.NO_BID,)
    assert hard_blocker.expected.blockers == (
        "Confirmed insolvency exclusion ground blocks submission.",
    )


def test_golden_demo_cases_document_decision_rules_not_domain_guesswork() -> None:
    for case in golden_demo_cases():
        assert case.expected.rationale
        assert case.expected.decision_rules
        assert any(
            evidence_ref.evidence_key in case.expected.rationale
            for evidence_ref in case.expected.required_evidence_refs
        )


def test_golden_demo_cases_capture_unsupported_claim_rejection() -> None:
    case = _case("unsupported_agent_claim_rejection")

    assert case.expected.unsupported_claims_rejected == (
        "Unverified subcontractor bench can cover delivery surge.",
    )
    assert case.expected.validation_errors == ("unsupported_claim",)
    assert "subcontractor" not in " ".join(
        evidence_ref.evidence_key.lower()
        for evidence_ref in case.expected.required_evidence_refs
    )


def _case(case_id: str) -> GoldenDemoCase:
    return next(case for case in golden_demo_cases() if case.case_id == case_id)
