from __future__ import annotations

import json
from pathlib import Path

from bidded.evals.golden_runner import (
    EvidenceCitationRequirement,
    EvidenceCoverageClaim,
    EvidenceCoverageClaimType,
    GoldenActualOutcome,
)
from bidded.evals.live_comparison import (
    AnthropicGoldenEvalOutcomeProvider,
    LiveGoldenEvalObservation,
    render_live_golden_eval_comparison_markdown,
    run_live_golden_eval_comparison,
    write_live_golden_eval_comparison_json,
    write_live_golden_eval_comparison_markdown,
)
from bidded.fixtures.golden_cases import GoldenDemoCase, golden_demo_cases
from bidded.orchestration import Verdict


def test_live_golden_comparison_highlights_material_differences() -> None:
    def live_outcome(case: GoldenDemoCase) -> LiveGoldenEvalObservation:
        return LiveGoldenEvalObservation(
            actual=GoldenActualOutcome(
                verdict=Verdict.NO_BID,
                validation_errors=("schema_error",),
                evidence_refs=(),
                coverage_claims=(
                    EvidenceCoverageClaim(
                        claim_type=EvidenceCoverageClaimType.JUDGE_DECISION,
                        claim="Reject the bid without cited evidence.",
                        citation_requirement=(
                            EvidenceCitationRequirement.ANY_EVIDENCE
                        ),
                        evidence_refs=(),
                    ),
                ),
            ),
            latency_ms=432,
            input_tokens=1200,
            output_tokens=300,
            estimated_cost_usd=0.042,
        )

    report = run_live_golden_eval_comparison(
        case_id="obvious_bid",
        live_outcome_provider=live_outcome,
    )

    assert not report.passed
    assert report.status == "failed"
    assert report.total_count == 1
    assert report.difference_count == 1
    comparison = report.case_comparisons[0]
    assert comparison.case_id == "obvious_bid"
    assert comparison.mock_result.actual_verdict is Verdict.BID
    assert comparison.live_result is not None
    assert comparison.live_result.actual_verdict is Verdict.NO_BID
    assert comparison.verdict_changed
    assert comparison.validation_errors_changed
    assert comparison.mock_validation_errors == ()
    assert comparison.live_validation_errors == ("schema_error",)
    assert comparison.evidence_coverage_delta == -1.0
    assert comparison.latency_ms == 432
    assert comparison.input_tokens == 1200
    assert comparison.output_tokens == 300
    assert comparison.estimated_cost_usd == 0.042


def test_live_golden_comparison_reports_unavailable_live_mode() -> None:
    report = run_live_golden_eval_comparison(
        case_id="obvious_bid",
        live_unavailable_reason="ANTHROPIC_API_KEY is required for live evals.",
    )

    assert not report.passed
    assert report.status == "unavailable"
    assert report.total_count == 1
    assert report.compared_count == 0
    assert report.unavailable_count == 1
    assert report.difference_count == 0
    assert report.mock_report.passed
    comparison = report.case_comparisons[0]
    assert comparison.case_id == "obvious_bid"
    assert comparison.mock_result.actual_verdict is Verdict.BID
    assert comparison.live_result is None
    assert comparison.live_unavailable_reason == (
        "ANTHROPIC_API_KEY is required for live evals."
    )


def test_live_golden_comparison_captures_live_validation_failure() -> None:
    def invalid_live_outcome(_case: GoldenDemoCase) -> LiveGoldenEvalObservation:
        raise ValueError("live response did not match GoldenActualOutcome")

    report = run_live_golden_eval_comparison(
        case_id="obvious_bid",
        live_outcome_provider=invalid_live_outcome,
    )

    assert not report.passed
    assert report.status == "failed"
    assert report.validation_failure_count == 1
    assert report.difference_count == 1
    comparison = report.case_comparisons[0]
    assert comparison.live_result is None
    assert comparison.live_validation_failure == (
        "live response did not match GoldenActualOutcome"
    )
    assert comparison.validation_errors_changed


def test_live_golden_comparison_writes_json_and_markdown_report(
    tmp_path: Path,
) -> None:
    def live_outcome(case: GoldenDemoCase) -> LiveGoldenEvalObservation:
        return LiveGoldenEvalObservation(
            actual=GoldenActualOutcome(
                verdict=Verdict.NO_BID,
                validation_errors=("schema_error",),
                evidence_refs=case.expected.required_evidence_refs,
                coverage_claims=(
                    EvidenceCoverageClaim(
                        claim_type=EvidenceCoverageClaimType.JUDGE_DECISION,
                        claim="Reject the bid without cited evidence.",
                        citation_requirement=(
                            EvidenceCitationRequirement.ANY_EVIDENCE
                        ),
                        evidence_refs=(),
                    ),
                ),
            ),
            latency_ms=250,
            input_tokens=100,
            output_tokens=40,
            estimated_cost_usd=0.012,
        )

    report = run_live_golden_eval_comparison(
        case_id="obvious_bid",
        live_outcome_provider=live_outcome,
    )
    json_path = tmp_path / "live-compare.json"
    markdown_path = tmp_path / "live-compare.md"

    write_live_golden_eval_comparison_json(report, json_path)
    write_live_golden_eval_comparison_markdown(report, markdown_path)

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = markdown_path.read_text(encoding="utf-8")
    assert payload["schema_version"] == "2026-04-19.live-golden-comparison.v1"
    assert payload["status"] == "failed"
    assert payload["runtime_summary"] == {
        "compared_count": 1,
        "difference_count": 1,
        "total_count": 1,
        "unavailable_count": 0,
        "validation_failure_count": 0,
    }
    assert payload["case_comparisons"][0]["case_id"] == "obvious_bid"
    assert payload["case_comparisons"][0]["mock_verdict"] == "bid"
    assert payload["case_comparisons"][0]["live_verdict"] == "no_bid"
    assert payload["case_comparisons"][0]["verdict_changed"] is True
    assert payload["case_comparisons"][0]["validation_errors_changed"] is True
    assert payload["case_comparisons"][0]["latency_ms"] == 250
    assert payload["case_comparisons"][0]["input_tokens"] == 100
    assert payload["case_comparisons"][0]["output_tokens"] == 40
    assert payload["case_comparisons"][0]["estimated_cost_usd"] == 0.012
    assert markdown == render_live_golden_eval_comparison_markdown(report)
    assert markdown.startswith("# Live vs Mock Golden Eval Report\n")
    assert "Status: FAIL" in markdown
    assert "Compared cases: 1/1" in markdown
    assert (
        "| obvious_bid | DIFF | bid | no_bid | yes | yes | 0.00 | 250 | "
        "100 | 40 | 0.012 |"
    ) in markdown


def test_anthropic_golden_eval_provider_parses_json_and_usage_metadata() -> None:
    case = golden_demo_cases()[0]
    response_payload = {
        "verdict": "bid",
        "evidence_refs": [
            evidence_ref.model_dump(mode="json")
            for evidence_ref in case.expected.required_evidence_refs
        ],
        "coverage_claims": [],
    }
    client = RecordingAnthropicClient(response_payload)
    provider = AnthropicGoldenEvalOutcomeProvider(
        client,
        model_name="claude-test-model",
    )

    observation = provider(case)

    assert observation.actual.verdict is Verdict.BID
    assert observation.actual.version_metadata is not None
    assert observation.actual.version_metadata.model_name == "claude-test-model"
    assert observation.input_tokens == 123
    assert observation.output_tokens == 45
    assert observation.estimated_cost_usd == 0.019
    assert observation.latency_ms is not None
    assert client.messages.created_kwargs["model"] == "claude-test-model"
    assert "obvious_bid" in client.messages.created_kwargs["messages"][0]["content"]


class RecordingAnthropicClient:
    def __init__(self, payload: dict[str, object]) -> None:
        self.messages = RecordingMessages(payload)


class RecordingMessages:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.created_kwargs: dict[str, object] = {}

    def create(self, **kwargs: object) -> object:
        self.created_kwargs = kwargs
        return type(
            "Response",
            (),
            {
                "content": [
                    type(
                        "TextBlock",
                        (),
                        {"text": json.dumps(self.payload)},
                    )()
                ],
                "usage": type(
                    "Usage",
                    (),
                    {
                        "input_tokens": 123,
                        "output_tokens": 45,
                    },
                )(),
                "estimated_cost_usd": 0.019,
            },
        )()
