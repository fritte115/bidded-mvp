from __future__ import annotations

import json
from pathlib import Path

import pytest

from bidded.evals.golden_runner import (
    GoldenActualOutcome,
    GoldenEvalError,
    run_golden_evals,
    write_golden_eval_json,
)
from bidded.fixtures.golden_cases import GoldenDemoCase
from bidded.orchestration import Verdict


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
