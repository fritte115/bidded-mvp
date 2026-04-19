from __future__ import annotations

import json
from pathlib import Path

import pytest

from bidded.evals.golden_runner import (
    EvidenceCitationRequirement,
    EvidenceCoverageClaim,
    EvidenceCoverageClaimType,
    GoldenActualOutcome,
    GoldenCaseEvalResult,
    GoldenEvalError,
    GoldenEvalReport,
    recorded_golden_outcome,
    run_golden_evals,
    write_golden_eval_json,
    write_golden_eval_markdown,
)
from bidded.fixtures.golden_cases import GoldenDemoCase
from bidded.orchestration import EvidenceSourceType, Verdict


def test_golden_eval_runner_passes_all_recorded_cases() -> None:
    report = run_golden_evals()

    assert report.total_count == 6
    assert report.failed_count == 0
    assert report.passed
    assert {result.case_id for result in report.results} == {
        "obvious_bid",
        "hard_compliance_no_bid",
        "conditional_bid_next_actions",
        "conflicting_evidence_needs_review",
        "missing_company_evidence",
        "unsupported_agent_claim_rejection",
    }
    assert all(result.evidence_coverage.passed for result in report.results)


def test_golden_eval_runner_selects_adversarial_fixture_group() -> None:
    report = run_golden_evals(fixture_group="adversarial")

    assert report.total_count == 6
    assert report.failed_count == 0
    assert report.passed
    assert {result.case_id for result in report.results} == {
        "near_miss_certification",
        "hidden_shall_requirement",
        "stale_company_evidence",
        "conflicting_deadlines",
        "weak_margin",
        "red_team_blocker_challenge",
    }


@pytest.mark.parametrize(
    ("case_id", "expected_failure"),
    [
        ("near_miss_certification", "bid_not_allowed"),
        ("hidden_shall_requirement", "bid_not_allowed"),
        ("stale_company_evidence", "bid_not_allowed"),
        ("conflicting_deadlines", "human_review_required"),
        ("weak_margin", "missing_commercial_action"),
        ("red_team_blocker_challenge", "unsupported_blocker_challenged"),
    ],
)
def test_golden_eval_catches_adversarial_failure_examples(
    case_id: str,
    expected_failure: str,
) -> None:
    report = run_golden_evals(
        case_id=case_id,
        fixture_group="adversarial",
        outcome_provider=_adversarial_failure_outcome,
    )

    result = report.results[0]
    assert not report.passed
    assert not result.passed
    if expected_failure == "bid_not_allowed":
        assert result.verdict_regression_failures == (
            "actual verdict bid not in allowed set: conditional_bid",
        )
    elif expected_failure == "human_review_required":
        assert result.verdict_regression_failures == (
            "actual verdict conditional_bid not in allowed set: needs_human_review",
        )
    elif expected_failure == "missing_commercial_action":
        assert result.missing_required_recommended_actions == (
            "Have Delivery/CFO approve the margin or identify lower-cost "
            "staffing before bid submission.",
        )
    else:
        assert result.verdict_regression_failures == (
            "actual verdict no_bid not in allowed set: conditional_bid",
        )
        assert result.unexpected_hard_blockers == (
            "Missing ISO 14001 is a formal exclusion blocker.",
        )
        assert result.missing_expected_unsupported_claim_rejections == (
            "Missing ISO 14001 is a formal exclusion blocker.",
        )


def test_golden_eval_scores_full_evidence_coverage() -> None:
    def covered_outcome(case: GoldenDemoCase) -> GoldenActualOutcome:
        return _expected_outcome_with_claim(
            case,
            EvidenceCoverageClaim(
                claim_type=EvidenceCoverageClaimType.JUDGE_DECISION,
                claim="The tender requirement is matched by company proof.",
                citation_requirement=(
                    EvidenceCitationRequirement.TENDER_AND_COMPANY_WHEN_AVAILABLE
                ),
                evidence_refs=case.expected.required_evidence_refs,
            ),
            EvidenceCoverageClaim(
                claim_type=EvidenceCoverageClaimType.RECOMMENDED_ACTION,
                claim="Proceed with the bid using the cited matched proof.",
                citation_requirement=(
                    EvidenceCitationRequirement.TENDER_AND_COMPANY_WHEN_AVAILABLE
                ),
                evidence_refs=case.expected.required_evidence_refs,
            ),
        )

    report = run_golden_evals(
        case_id="obvious_bid",
        outcome_provider=covered_outcome,
    )

    result = report.results[0]
    assert report.passed
    assert result.evidence_coverage.passed
    assert result.evidence_coverage.score == 1.0
    assert result.evidence_coverage.threshold == 1.0
    assert result.evidence_coverage.material_claim_count == 2
    assert result.evidence_coverage.covered_claim_count == 2
    assert result.evidence_coverage.unsupported_claim_count == 0
    assert result.evidence_coverage.missing_citation_details == ()


def test_golden_eval_reports_missing_tender_citation() -> None:
    def missing_tender_outcome(case: GoldenDemoCase) -> GoldenActualOutcome:
        return _expected_outcome_with_claim(
            case,
            EvidenceCoverageClaim(
                claim_type=EvidenceCoverageClaimType.MATERIAL_FINDING,
                claim="Company certification satisfies a tender requirement.",
                citation_requirement=EvidenceCitationRequirement.TENDER_DOCUMENT,
                evidence_refs=(_first_ref(case, EvidenceSourceType.COMPANY_PROFILE),),
            ),
        )

    report = run_golden_evals(
        case_id="obvious_bid",
        outcome_provider=missing_tender_outcome,
    )

    result = report.results[0]
    detail = result.evidence_coverage.missing_citation_details[0]
    assert not report.passed
    assert result.evidence_coverage.score == 0.0
    assert detail.missing_source_types == (EvidenceSourceType.TENDER_DOCUMENT,)
    assert detail.present_source_types == (EvidenceSourceType.COMPANY_PROFILE,)


def test_golden_eval_reports_missing_company_citation_for_comparison_claim() -> None:
    def missing_company_outcome(case: GoldenDemoCase) -> GoldenActualOutcome:
        return _expected_outcome_with_claim(
            case,
            EvidenceCoverageClaim(
                claim_type=EvidenceCoverageClaimType.BLOCKER,
                claim="The tender exclusion is confirmed by the company profile.",
                citation_requirement=(
                    EvidenceCitationRequirement.TENDER_AND_COMPANY_WHEN_AVAILABLE
                ),
                evidence_refs=(_first_ref(case, EvidenceSourceType.TENDER_DOCUMENT),),
            ),
        )

    report = run_golden_evals(
        case_id="hard_compliance_no_bid",
        outcome_provider=missing_company_outcome,
    )

    result = report.results[0]
    detail = result.evidence_coverage.missing_citation_details[0]
    assert not report.passed
    assert detail.missing_source_types == (EvidenceSourceType.COMPANY_PROFILE,)
    assert detail.present_source_types == (EvidenceSourceType.TENDER_DOCUMENT,)


def test_golden_eval_counts_unsupported_material_claims_separately() -> None:
    def unsupported_outcome(case: GoldenDemoCase) -> GoldenActualOutcome:
        return _expected_outcome_with_claim(
            case,
            EvidenceCoverageClaim(
                claim_type=EvidenceCoverageClaimType.RISK_REGISTER_ENTRY,
                claim="Subcontractor bench can cover delivery surge.",
                citation_requirement=EvidenceCitationRequirement.ANY_EVIDENCE,
                evidence_refs=(),
            ),
        )

    report = run_golden_evals(
        case_id="unsupported_agent_claim_rejection",
        outcome_provider=unsupported_outcome,
    )

    result = report.results[0]
    assert not report.passed
    assert result.evidence_coverage.material_claim_count == 1
    assert result.evidence_coverage.covered_claim_count == 0
    assert result.evidence_coverage.unsupported_claim_count == 1
    assert result.evidence_coverage.missing_citation_details[0].reason == (
        "unsupported_material_claim"
    )


@pytest.mark.parametrize(
    "claim_type",
    [
        EvidenceCoverageClaimType.ASSUMPTION,
        EvidenceCoverageClaimType.MISSING_INFO,
        EvidenceCoverageClaimType.POTENTIAL_EVIDENCE_GAP,
    ],
)
def test_golden_eval_allows_uncited_gap_and_assumption_notes(
    claim_type: EvidenceCoverageClaimType,
) -> None:
    def allowed_gap_outcome(case: GoldenDemoCase) -> GoldenActualOutcome:
        return _expected_outcome_with_claim(
            case,
            EvidenceCoverageClaim(
                claim_type=claim_type,
                claim="Current audited turnover evidence is missing.",
                citation_requirement=EvidenceCitationRequirement.ANY_EVIDENCE,
                evidence_refs=(),
            ),
        )

    report = run_golden_evals(
        case_id="missing_company_evidence",
        outcome_provider=allowed_gap_outcome,
    )

    result = report.results[0]
    assert report.passed
    assert result.evidence_coverage.passed
    assert result.evidence_coverage.score == 1.0
    assert result.evidence_coverage.material_claim_count == 0
    assert result.evidence_coverage.unsupported_claim_count == 0
    assert result.evidence_coverage.missing_citation_details == ()


def test_golden_eval_runner_selects_one_case_by_id() -> None:
    report = run_golden_evals(case_id="hard_compliance_no_bid")

    assert report.total_count == 1
    assert report.passed
    assert [result.case_id for result in report.results] == [
        "hard_compliance_no_bid"
    ]


def test_golden_eval_runner_rejects_unknown_case_id() -> None:
    with pytest.raises(GoldenEvalError, match="Unknown golden case ID"):
        run_golden_evals(case_id="not_a_case")


def test_golden_eval_runner_reports_failed_expectations() -> None:
    def bad_outcome(_case: GoldenDemoCase) -> GoldenActualOutcome:
        return GoldenActualOutcome(
            verdict=Verdict.BID,
            blockers=("Unexpected hard blocker.",),
            validation_errors=("schema_error",),
            evidence_refs=(),
            coverage_claims=(
                EvidenceCoverageClaim(
                    claim_type=EvidenceCoverageClaimType.BLOCKER,
                    claim="Unexpected hard blocker.",
                    citation_requirement=EvidenceCitationRequirement.ANY_EVIDENCE,
                    evidence_refs=(),
                ),
            ),
        )

    report = run_golden_evals(
        case_id="hard_compliance_no_bid",
        outcome_provider=bad_outcome,
    )

    result = report.results[0]
    assert not report.passed
    assert report.failed_count == 1
    assert result.expected_verdict is Verdict.NO_BID
    assert result.actual_verdict is Verdict.BID
    assert result.missing_required_blockers == (
        "Confirmed insolvency exclusion ground blocks submission.",
    )
    assert result.unexpected_hard_blockers == ("Unexpected hard blocker.",)
    assert result.unexpected_validation_errors == ("schema_error",)
    assert result.evidence_reference_failures == (
        "missing required evidence ref: "
        "GOLDEN-HARD-COMPLIANCE-NO-BID-TENDER-INSOLVENCY-EXCLUSION",
        "missing required evidence ref: "
        "GOLDEN-HARD-COMPLIANCE-NO-BID-COMPANY-ACTIVE-INSOLVENCY",
    )


def test_golden_eval_allows_missing_evidence_human_review_outcome() -> None:
    def human_review_outcome(case: GoldenDemoCase) -> GoldenActualOutcome:
        return GoldenActualOutcome(
            verdict=Verdict.NEEDS_HUMAN_REVIEW,
            missing_info=case.expected.missing_info,
            recommended_actions=case.expected.recommended_actions,
            evidence_refs=case.expected.required_evidence_refs,
        )

    report = run_golden_evals(
        case_id="missing_company_evidence",
        outcome_provider=human_review_outcome,
    )

    result = report.results[0]
    assert report.passed
    assert result.actual_verdict is Verdict.NEEDS_HUMAN_REVIEW
    assert result.allowed_verdicts == (
        Verdict.CONDITIONAL_BID,
        Verdict.NEEDS_HUMAN_REVIEW,
    )


def test_golden_eval_fails_verdict_outside_allowed_set() -> None:
    def no_bid_outcome(case: GoldenDemoCase) -> GoldenActualOutcome:
        return GoldenActualOutcome(
            verdict=Verdict.NO_BID,
            missing_info=case.expected.missing_info,
            recommended_actions=case.expected.recommended_actions,
            evidence_refs=case.expected.required_evidence_refs,
        )

    report = run_golden_evals(
        case_id="missing_company_evidence",
        outcome_provider=no_bid_outcome,
    )

    result = report.results[0]
    assert not report.passed
    assert result.verdict_regression_failures == (
        "actual verdict no_bid not in allowed set: "
        "conditional_bid, needs_human_review",
    )


def test_golden_eval_requires_no_bid_for_hard_compliance_blocker() -> None:
    def vote_drift_outcome(case: GoldenDemoCase) -> GoldenActualOutcome:
        return GoldenActualOutcome(
            verdict=Verdict.CONDITIONAL_BID,
            specialist_votes=(
                Verdict.BID,
                Verdict.BID,
                Verdict.CONDITIONAL_BID,
            ),
            blockers=case.expected.blockers,
            evidence_refs=case.expected.required_evidence_refs,
        )

    report = run_golden_evals(
        case_id="hard_compliance_no_bid",
        outcome_provider=vote_drift_outcome,
    )

    result = report.results[0]
    assert not report.passed
    assert result.allowed_verdicts == (Verdict.NO_BID,)
    assert result.verdict_regression_failures == (
        "formal compliance blocker requires no_bid",
    )


def test_golden_eval_runner_requires_unsupported_claim_rejections() -> None:
    def incomplete_outcome(case: GoldenDemoCase) -> GoldenActualOutcome:
        return GoldenActualOutcome(
            verdict=case.expected.verdict,
            missing_info=case.expected.missing_info,
            recommended_actions=case.expected.recommended_actions,
            validation_errors=case.expected.validation_errors,
            evidence_refs=case.expected.required_evidence_refs,
        )

    report = run_golden_evals(
        case_id="unsupported_agent_claim_rejection",
        outcome_provider=incomplete_outcome,
    )

    result = report.results[0]
    assert not report.passed
    assert result.missing_expected_unsupported_claim_rejections == (
        "Unverified subcontractor bench can cover delivery surge.",
    )


def test_golden_eval_runner_writes_stable_json(tmp_path: Path) -> None:
    report = run_golden_evals(case_id="obvious_bid")
    json_path = tmp_path / "evals" / "golden.json"

    write_golden_eval_json(report, json_path)

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["total_count"] == 1
    assert payload["results"][0]["case_id"] == "obvious_bid"
    assert payload["results"][0]["expected_verdict"] == "bid"
    assert payload["results"][0]["actual_verdict"] == "bid"
    assert payload["results"][0]["evidence_coverage"]["passed"] is True


def test_golden_eval_runner_exports_report_json_schema(tmp_path: Path) -> None:
    report = run_golden_evals(case_id="obvious_bid")
    json_path = tmp_path / "evals" / "golden-report.json"

    write_golden_eval_json(report, json_path)

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "2026-04-19.golden-eval-report.v1"
    assert payload["runtime_summary"] == {
        "failed_case_ids": [],
        "failed_count": 0,
        "pass_rate": 1.0,
        "passed_count": 1,
        "total_count": 1,
    }
    assert payload["failed_cases"] == []
    assert payload["results"][0]["status"] == "passed"
    assert payload["results"][0]["case_id"] == "obvious_bid"
    assert payload["results"][0]["expected_verdict"] == "bid"
    assert payload["results"][0]["actual_verdict"] == "bid"
    assert payload["results"][0]["evidence_coverage"]["score"] == 1.0
    assert payload["results"][0]["evidence_coverage"]["unsupported_claim_count"] == 0
    assert payload["results"][0]["validation_errors"] == []


def test_golden_eval_runner_writes_readable_markdown_report(
    tmp_path: Path,
) -> None:
    report = run_golden_evals(case_id="obvious_bid")
    markdown_path = tmp_path / "evals" / "golden-report.md"

    write_golden_eval_markdown(report, markdown_path)

    markdown = markdown_path.read_text(encoding="utf-8")
    assert markdown.startswith("# Golden Eval Report\n")
    assert "Status: PASS" in markdown
    assert "Pass rate: 100.00% (1/1)" in markdown
    assert "Failed cases: none" in markdown
    assert "prompt_version=bidded_prompt_v1" in markdown
    assert (
        "| obvious_bid | PASS | bid | bid | 1.00 | 0 | none |"
        in markdown
    )


def test_golden_eval_runner_exports_mixed_pass_report(
    tmp_path: Path,
) -> None:
    def mixed_outcome(case: GoldenDemoCase) -> GoldenActualOutcome:
        if case.case_id != "hard_compliance_no_bid":
            return recorded_golden_outcome(case)
        return GoldenActualOutcome(
            verdict=Verdict.BID,
            blockers=("Unexpected hard blocker.",),
            validation_errors=("schema_error",),
            evidence_refs=(),
            coverage_claims=(
                EvidenceCoverageClaim(
                    claim_type=EvidenceCoverageClaimType.BLOCKER,
                    claim="Unexpected hard blocker.",
                    citation_requirement=EvidenceCitationRequirement.ANY_EVIDENCE,
                    evidence_refs=(),
                ),
            ),
        )

    report = run_golden_evals(outcome_provider=mixed_outcome)
    json_path = tmp_path / "evals" / "mixed-report.json"
    markdown_path = tmp_path / "evals" / "mixed-report.md"

    write_golden_eval_json(report, json_path)
    write_golden_eval_markdown(report, markdown_path)

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = markdown_path.read_text(encoding="utf-8")
    assert payload["runtime_summary"]["failed_case_ids"] == [
        "hard_compliance_no_bid"
    ]
    assert payload["failed_cases"][0]["case_id"] == "hard_compliance_no_bid"
    assert payload["failed_cases"][0]["status"] == "failed"
    assert payload["failed_cases"][0]["validation_errors"] == ["schema_error"]
    assert payload["failed_cases"][0]["evidence_coverage"]["score"] == 0.0
    assert payload["failed_cases"][0]["evidence_coverage"][
        "unsupported_claim_count"
    ] == 1
    assert "Status: FAIL" in markdown
    assert "Failed cases: hard_compliance_no_bid" in markdown
    assert "## Failure Details" in markdown
    assert "### hard_compliance_no_bid" in markdown
    assert "Validation errors: schema_error" in markdown


def test_golden_eval_runner_exports_reports_deterministically(
    tmp_path: Path,
) -> None:
    report = run_golden_evals()
    first_json_path = tmp_path / "first" / "golden.json"
    second_json_path = tmp_path / "second" / "golden.json"
    first_markdown_path = tmp_path / "first" / "golden.md"
    second_markdown_path = tmp_path / "second" / "golden.md"

    write_golden_eval_json(report, first_json_path)
    write_golden_eval_json(report, second_json_path)
    write_golden_eval_markdown(report, first_markdown_path)
    write_golden_eval_markdown(report, second_markdown_path)

    assert first_json_path.read_text(encoding="utf-8") == (
        second_json_path.read_text(encoding="utf-8")
    )
    assert first_markdown_path.read_text(encoding="utf-8") == (
        second_markdown_path.read_text(encoding="utf-8")
    )


def test_golden_eval_runner_includes_version_metadata_in_json(
    tmp_path: Path,
) -> None:
    report = run_golden_evals(case_id="obvious_bid")
    json_path = tmp_path / "evals" / "golden-with-versions.json"

    write_golden_eval_json(report, json_path)

    expected_metadata = {
        "prompt_version": "bidded_prompt_v1",
        "schema_version": "bidded_agent_output_schema_v1",
        "retrieval_version": "bidded_hybrid_retrieval_v1",
        "model_name": "mocked_graph_shell",
        "eval_fixture_version": "golden_demo_cases_v1",
    }
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["version_metadata"] == expected_metadata
    assert payload["version_warnings"] == []
    assert payload["results"][0]["version_metadata"] == expected_metadata
    assert payload["results"][0]["version_warnings"] == []


def test_golden_eval_runner_includes_normalized_actual_decision_in_json(
    tmp_path: Path,
) -> None:
    report = run_golden_evals(case_id="conditional_bid_next_actions")
    json_path = tmp_path / "evals" / "golden-with-decision.json"

    write_golden_eval_json(report, json_path)

    result = json.loads(json_path.read_text(encoding="utf-8"))["results"][0]
    assert result["actual_decision"]["decision_id"] == (
        "conditional_bid_next_actions"
    )
    assert result["actual_decision"]["verdict"] == "conditional_bid"
    assert result["actual_decision"]["blockers"] == []
    assert result["actual_decision"]["missing_info"] == [
        "Named security-cleared delivery lead CV is not present.",
        "Signed data processing agreement attachment is not present.",
    ]
    assert result["actual_decision"]["recommended_actions"] == [
        "Name the delivery lead and attach that person's CV.",
        "Prepare and sign the data processing agreement attachment.",
    ]
    assert result["actual_decision"]["cited_evidence_keys"] == [
        "GOLDEN-CONDITIONAL-BID-NEXT-ACTIONS-TENDER-NAMED-LEAD",
        "GOLDEN-CONDITIONAL-BID-NEXT-ACTIONS-TENDER-SIGNED-DPA",
        "GOLDEN-CONDITIONAL-BID-NEXT-ACTIONS-COMPANY-CLEARED-LEADS",
    ]


def test_golden_eval_warns_when_actual_version_metadata_is_missing() -> None:
    def legacy_outcome(case: GoldenDemoCase) -> GoldenActualOutcome:
        return _expected_outcome_with_claim(case)

    report = run_golden_evals(
        case_id="obvious_bid",
        outcome_provider=legacy_outcome,
    )

    expected_warning = (
        "missing version metadata: prompt_version, schema_version, "
        "retrieval_version, model_name, eval_fixture_version"
    )
    result = report.results[0]
    assert report.passed
    assert result.version_warnings == (expected_warning,)
    assert report.version_warnings == (f"obvious_bid: {expected_warning}",)
    assert result.version_metadata.prompt_version == "bidded_prompt_v1"
    assert result.version_metadata.eval_fixture_version == "golden_demo_cases_v1"


def test_golden_eval_models_load_legacy_payloads_without_version_fields() -> None:
    legacy_result = {
        "case_id": "obvious_bid",
        "title": "Obvious bid from matched proof",
        "passed": True,
        "expected_verdict": "bid",
        "actual_verdict": "bid",
    }

    result = GoldenCaseEvalResult.model_validate(legacy_result)
    report = GoldenEvalReport.model_validate(
        {
            "passed": True,
            "total_count": 1,
            "passed_count": 1,
            "failed_count": 0,
            "results": [legacy_result],
        }
    )

    assert result.version_metadata.prompt_version == "bidded_prompt_v1"
    assert result.version_warnings == ()
    assert report.version_metadata.eval_fixture_version == "golden_demo_cases_v1"
    assert report.version_warnings == ()


def _expected_outcome_with_claim(
    case: GoldenDemoCase,
    *claims: EvidenceCoverageClaim,
) -> GoldenActualOutcome:
    return GoldenActualOutcome(
        verdict=case.expected.verdict,
        blockers=case.expected.blockers,
        missing_info=case.expected.missing_info,
        recommended_actions=case.expected.recommended_actions,
        unsupported_claims_rejected=case.expected.unsupported_claims_rejected,
        validation_errors=case.expected.validation_errors,
        evidence_refs=case.expected.required_evidence_refs,
        coverage_claims=claims,
    )


def _adversarial_failure_outcome(case: GoldenDemoCase) -> GoldenActualOutcome:
    if case.adversarial_category in {
        "near_miss_certification",
        "hidden_shall_requirement",
        "stale_company_evidence",
    }:
        return GoldenActualOutcome(
            verdict=Verdict.BID,
            evidence_refs=case.expected.required_evidence_refs,
        )

    if case.adversarial_category == "conflicting_deadlines":
        return GoldenActualOutcome(
            verdict=Verdict.CONDITIONAL_BID,
            missing_info=case.expected.missing_info,
            recommended_actions=case.expected.recommended_actions,
            evidence_refs=case.expected.required_evidence_refs,
        )

    if case.adversarial_category == "weak_margin":
        return GoldenActualOutcome(
            verdict=case.expected.verdict,
            missing_info=case.expected.missing_info,
            evidence_refs=case.expected.required_evidence_refs,
        )

    return GoldenActualOutcome(
        verdict=Verdict.NO_BID,
        blockers=("Missing ISO 14001 is a formal exclusion blocker.",),
        evidence_refs=case.expected.required_evidence_refs,
    )


def _first_ref(
    case: GoldenDemoCase,
    source_type: EvidenceSourceType,
):
    return next(
        evidence_ref
        for evidence_ref in case.expected.required_evidence_refs
        if evidence_ref.source_type is source_type
    )
