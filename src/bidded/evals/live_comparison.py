from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import Field, NonNegativeFloat, NonNegativeInt

from bidded.evals.golden_runner import (
    GoldenActualOutcome,
    GoldenCaseEvalResult,
    GoldenEvalError,
    GoldenEvalReport,
    evaluate_golden_case,
    golden_eval_report_json_payload,
    run_golden_evals,
)
from bidded.fixtures.golden_cases import (
    GoldenDemoCase,
    GoldenFixtureSelection,
    golden_demo_cases,
)
from bidded.orchestration.state import StrictStateModel
from bidded.versioning import (
    DEFAULT_PROMPT_VERSION,
    DEFAULT_RETRIEVAL_VERSION,
    DEFAULT_SCHEMA_VERSION,
    GOLDEN_EVAL_FIXTURE_VERSION,
    VersionMetadata,
    default_version_metadata,
)

LIVE_GOLDEN_EVAL_COMPARISON_SCHEMA_VERSION = (
    "2026-04-19.live-golden-comparison.v1"
)


class LiveGoldenEvalStatus(StrEnum):
    """Top-level status for a live-versus-mock eval comparison."""

    PASSED = "passed"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class LiveGoldenEvalObservation(StrictStateModel):
    """One live eval observation plus runtime metadata."""

    actual: GoldenActualOutcome
    latency_ms: NonNegativeInt | None = None
    input_tokens: NonNegativeInt | None = None
    output_tokens: NonNegativeInt | None = None
    estimated_cost_usd: NonNegativeFloat | None = None


class LiveGoldenEvalCaseComparison(StrictStateModel):
    """Mock baseline and live result comparison for one golden case."""

    case_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    mock_result: GoldenCaseEvalResult
    live_result: GoldenCaseEvalResult | None = None
    live_unavailable_reason: str | None = None
    verdict_changed: bool = False
    validation_errors_changed: bool = False
    mock_validation_errors: tuple[str, ...] = ()
    live_validation_errors: tuple[str, ...] = ()
    live_validation_failure: str | None = None
    evidence_coverage_delta: float | None = None
    latency_ms: NonNegativeInt | None = None
    input_tokens: NonNegativeInt | None = None
    output_tokens: NonNegativeInt | None = None
    estimated_cost_usd: NonNegativeFloat | None = None

    @property
    def has_difference(self) -> bool:
        if self.live_validation_failure is not None:
            return True
        if self.live_result is None:
            return False
        return (
            self.verdict_changed
            or self.validation_errors_changed
            or self.evidence_coverage_delta != 0
            or not self.live_result.passed
        )


class LiveGoldenEvalComparisonReport(StrictStateModel):
    """Stable report comparing deterministic mock evals with live Claude evals."""

    status: LiveGoldenEvalStatus
    passed: bool
    total_count: NonNegativeInt
    compared_count: NonNegativeInt
    unavailable_count: NonNegativeInt = 0
    validation_failure_count: NonNegativeInt = 0
    difference_count: NonNegativeInt
    mock_report: GoldenEvalReport
    case_comparisons: tuple[LiveGoldenEvalCaseComparison, ...]
    unavailable_reason: str | None = None


LiveGoldenOutcomeProvider = Callable[[GoldenDemoCase], LiveGoldenEvalObservation]


class AnthropicGoldenEvalOutcomeProvider:
    """Minimal JSON adapter for opt-in live golden eval rehearsal."""

    def __init__(
        self,
        client: Any,
        *,
        model_name: str,
        max_tokens: int = 4096,
    ) -> None:
        self._client = client
        self._model_name = model_name
        self._max_tokens = max_tokens

    def __call__(self, case: GoldenDemoCase) -> LiveGoldenEvalObservation:
        prompt = _live_golden_eval_prompt(case)
        started = time.perf_counter()
        response = self._client.messages.create(
            model=self._model_name,
            max_tokens=self._max_tokens,
            temperature=0,
            system=(
                "You are Bidded's evidence-locked procurement decision evaluator. "
                "Return only valid JSON for the requested schema."
            ),
            messages=[
                {
                    "role": "user",
                    "content": json.dumps(prompt, default=str),
                }
            ],
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        actual = GoldenActualOutcome.model_validate(
            _parse_json_object(_anthropic_response_text(response))
        )
        if actual.version_metadata is None:
            actual = actual.model_copy(
                update={
                    "version_metadata": VersionMetadata(
                        prompt_version=DEFAULT_PROMPT_VERSION,
                        schema_version=DEFAULT_SCHEMA_VERSION,
                        retrieval_version=DEFAULT_RETRIEVAL_VERSION,
                        model_name=self._model_name,
                        eval_fixture_version=GOLDEN_EVAL_FIXTURE_VERSION,
                    )
                }
            )

        return LiveGoldenEvalObservation(
            actual=actual,
            latency_ms=latency_ms,
            input_tokens=_usage_value(response, "input_tokens"),
            output_tokens=_usage_value(response, "output_tokens"),
            estimated_cost_usd=_response_float(response, "estimated_cost_usd"),
        )


def run_live_golden_eval_comparison(
    *,
    case_id: str | None = None,
    fixture_group: GoldenFixtureSelection = "core",
    live_outcome_provider: LiveGoldenOutcomeProvider | None = None,
    live_unavailable_reason: str | None = None,
) -> LiveGoldenEvalComparisonReport:
    """Compare recorded mock golden evals with injected or live Claude outcomes."""

    if live_outcome_provider is None and live_unavailable_reason is None:
        raise GoldenEvalError(
            "live_outcome_provider or live_unavailable_reason is required."
        )
    if live_outcome_provider is not None and live_unavailable_reason is not None:
        raise GoldenEvalError(
            "Provide either live_outcome_provider or live_unavailable_reason, not both."
        )

    cases = _select_cases(case_id, fixture_group=fixture_group)
    mock_report = run_golden_evals(case_id=case_id, fixture_group=fixture_group)
    mock_by_case_id = {result.case_id: result for result in mock_report.results}
    fallback_version_metadata = default_version_metadata(
        eval_fixture_version=GOLDEN_EVAL_FIXTURE_VERSION
    )

    if live_unavailable_reason is not None:
        comparisons = tuple(
            LiveGoldenEvalCaseComparison(
                case_id=case.case_id,
                title=case.title,
                mock_result=mock_by_case_id[case.case_id],
                live_unavailable_reason=live_unavailable_reason,
            )
            for case in cases
        )
        return LiveGoldenEvalComparisonReport(
            status=LiveGoldenEvalStatus.UNAVAILABLE,
            passed=False,
            total_count=len(comparisons),
            compared_count=0,
            unavailable_count=len(comparisons),
            difference_count=0,
            mock_report=mock_report,
            case_comparisons=comparisons,
            unavailable_reason=live_unavailable_reason,
        )

    assert live_outcome_provider is not None
    comparisons_list: list[LiveGoldenEvalCaseComparison] = []
    for case in cases:
        mock_result = mock_by_case_id[case.case_id]
        try:
            observation = live_outcome_provider(case)
        except ValueError as exc:
            comparisons_list.append(
                LiveGoldenEvalCaseComparison(
                    case_id=case.case_id,
                    title=case.title,
                    mock_result=mock_result,
                    live_validation_failure=str(exc),
                    validation_errors_changed=True,
                    mock_validation_errors=mock_result.actual_validation_errors,
                )
            )
            continue
        comparisons_list.append(
            _compare_live_case(
                case,
                mock_result=mock_result,
                observation=observation,
                fallback_version_metadata=fallback_version_metadata,
            )
        )
    comparisons = tuple(comparisons_list)
    compared_count = sum(1 for comparison in comparisons if comparison.live_result)
    validation_failure_count = sum(
        1 for comparison in comparisons if comparison.live_validation_failure
    )
    difference_count = sum(1 for comparison in comparisons if comparison.has_difference)
    passed = difference_count == 0 and mock_report.passed
    return LiveGoldenEvalComparisonReport(
        status=(
            LiveGoldenEvalStatus.PASSED
            if passed
            else LiveGoldenEvalStatus.FAILED
        ),
        passed=passed,
        total_count=len(comparisons),
        compared_count=compared_count,
        unavailable_count=0,
        validation_failure_count=validation_failure_count,
        difference_count=difference_count,
        mock_report=mock_report,
        case_comparisons=comparisons,
    )


def write_live_golden_eval_comparison_json(
    report: LiveGoldenEvalComparisonReport,
    path: Path,
) -> None:
    """Write a deterministic JSON live-versus-mock comparison report."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            live_golden_eval_comparison_json_payload(report),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def write_live_golden_eval_comparison_markdown(
    report: LiveGoldenEvalComparisonReport,
    path: Path,
) -> None:
    """Write a deterministic Markdown live-versus-mock comparison report."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render_live_golden_eval_comparison_markdown(report),
        encoding="utf-8",
    )


def live_golden_eval_comparison_json_payload(
    report: LiveGoldenEvalComparisonReport,
) -> dict[str, Any]:
    """Return the stable JSON-compatible live comparison payload."""

    return {
        "schema_version": LIVE_GOLDEN_EVAL_COMPARISON_SCHEMA_VERSION,
        "status": report.status.value,
        "passed": report.passed,
        "unavailable_reason": report.unavailable_reason,
        "runtime_summary": {
            "total_count": report.total_count,
            "compared_count": report.compared_count,
            "unavailable_count": report.unavailable_count,
            "validation_failure_count": report.validation_failure_count,
            "difference_count": report.difference_count,
        },
        "mock_report": golden_eval_report_json_payload(report.mock_report),
        "case_comparisons": [
            _live_case_comparison_payload(comparison)
            for comparison in report.case_comparisons
        ],
    }


def render_live_golden_eval_comparison_markdown(
    report: LiveGoldenEvalComparisonReport,
) -> str:
    """Render a human-readable live-versus-mock comparison report."""

    lines = [
        "# Live vs Mock Golden Eval Report",
        "",
        f"Status: {_status_label(report.status)}",
        f"Compared cases: {report.compared_count}/{report.total_count}",
        f"Unavailable cases: {report.unavailable_count}",
        f"Validation failures: {report.validation_failure_count}",
        f"Differences: {report.difference_count}",
    ]
    if report.unavailable_reason:
        lines.append(f"Unavailable reason: {report.unavailable_reason}")

    lines.extend(
        [
            "",
            "## Cases",
            "",
            (
                "| Case | Status | Mock verdict | Live verdict | Verdict changed | "
                "Validation changed | Live coverage | Latency ms | Input tokens | "
                "Output tokens | Est cost USD |"
            ),
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    lines.extend(
        _live_case_comparison_markdown_row(comparison)
        for comparison in report.case_comparisons
    )

    failure_details = [
        comparison
        for comparison in report.case_comparisons
        if comparison.live_validation_failure
        or comparison.live_unavailable_reason
        or comparison.has_difference
    ]
    if failure_details:
        lines.extend(["", "## Difference Details", ""])
        for comparison in failure_details:
            lines.extend(_live_case_comparison_detail_lines(comparison))

    return "\n".join(lines) + "\n"


def _compare_live_case(
    case: GoldenDemoCase,
    *,
    mock_result: GoldenCaseEvalResult,
    observation: LiveGoldenEvalObservation,
    fallback_version_metadata: object,
) -> LiveGoldenEvalCaseComparison:
    live_result = evaluate_golden_case(
        case,
        actual=observation.actual,
        fallback_version_metadata=fallback_version_metadata,
    )
    evidence_coverage_delta = (
        live_result.evidence_coverage.score - mock_result.evidence_coverage.score
    )
    return LiveGoldenEvalCaseComparison(
        case_id=case.case_id,
        title=case.title,
        mock_result=mock_result,
        live_result=live_result,
        verdict_changed=live_result.actual_verdict is not mock_result.actual_verdict,
        validation_errors_changed=(
            live_result.actual_validation_errors
            != mock_result.actual_validation_errors
        ),
        mock_validation_errors=mock_result.actual_validation_errors,
        live_validation_errors=live_result.actual_validation_errors,
        evidence_coverage_delta=evidence_coverage_delta,
        latency_ms=observation.latency_ms,
        input_tokens=observation.input_tokens,
        output_tokens=observation.output_tokens,
        estimated_cost_usd=observation.estimated_cost_usd,
    )


def _live_case_comparison_payload(
    comparison: LiveGoldenEvalCaseComparison,
) -> dict[str, Any]:
    return {
        "case_id": comparison.case_id,
        "title": comparison.title,
        "status": _case_status(comparison),
        "mock_verdict": comparison.mock_result.actual_verdict.value,
        "live_verdict": (
            comparison.live_result.actual_verdict.value
            if comparison.live_result is not None
            else None
        ),
        "verdict_changed": comparison.verdict_changed,
        "validation_errors_changed": comparison.validation_errors_changed,
        "mock_validation_errors": list(comparison.mock_validation_errors),
        "live_validation_errors": list(comparison.live_validation_errors),
        "live_validation_failure": comparison.live_validation_failure,
        "live_unavailable_reason": comparison.live_unavailable_reason,
        "mock_evidence_coverage_score": comparison.mock_result.evidence_coverage.score,
        "live_evidence_coverage_score": (
            comparison.live_result.evidence_coverage.score
            if comparison.live_result is not None
            else None
        ),
        "evidence_coverage_delta": comparison.evidence_coverage_delta,
        "latency_ms": comparison.latency_ms,
        "input_tokens": comparison.input_tokens,
        "output_tokens": comparison.output_tokens,
        "estimated_cost_usd": comparison.estimated_cost_usd,
    }


def _live_case_comparison_markdown_row(
    comparison: LiveGoldenEvalCaseComparison,
) -> str:
    live_verdict = (
        comparison.live_result.actual_verdict.value
        if comparison.live_result is not None
        else "n/a"
    )
    live_coverage = (
        f"{comparison.live_result.evidence_coverage.score:.2f}"
        if comparison.live_result is not None
        else "n/a"
    )
    return (
        f"| {comparison.case_id} "
        f"| {_case_status(comparison).upper()} "
        f"| {comparison.mock_result.actual_verdict.value} "
        f"| {live_verdict} "
        f"| {_yes_no(comparison.verdict_changed)} "
        f"| {_yes_no(comparison.validation_errors_changed)} "
        f"| {live_coverage} "
        f"| {_optional_value(comparison.latency_ms)} "
        f"| {_optional_value(comparison.input_tokens)} "
        f"| {_optional_value(comparison.output_tokens)} "
        f"| {_optional_value(comparison.estimated_cost_usd)} |"
    )


def _live_case_comparison_detail_lines(
    comparison: LiveGoldenEvalCaseComparison,
) -> list[str]:
    lines = [f"### {comparison.case_id}", ""]
    if comparison.live_unavailable_reason:
        lines.append(f"- Live unavailable: {comparison.live_unavailable_reason}")
    if comparison.live_validation_failure:
        lines.append(f"- Live validation failure: {comparison.live_validation_failure}")
    if comparison.verdict_changed and comparison.live_result is not None:
        lines.append(
            "- Verdict changed: "
            f"{comparison.mock_result.actual_verdict.value} -> "
            f"{comparison.live_result.actual_verdict.value}"
        )
    if comparison.validation_errors_changed:
        lines.append(
            "- Validation errors changed: "
            f"mock={_joined(comparison.mock_validation_errors)}; "
            f"live={_joined(comparison.live_validation_errors)}"
        )
    if comparison.evidence_coverage_delta not in (None, 0):
        lines.append(
            "- Evidence coverage delta: "
            f"{comparison.evidence_coverage_delta:+.2f}"
        )
    lines.append("")
    return lines


def _case_status(comparison: LiveGoldenEvalCaseComparison) -> str:
    if comparison.live_unavailable_reason:
        return "unavailable"
    if comparison.live_validation_failure:
        return "validation_failure"
    if comparison.has_difference:
        return "diff"
    return "match"


def _status_label(status: LiveGoldenEvalStatus) -> str:
    if status is LiveGoldenEvalStatus.PASSED:
        return "PASS"
    if status is LiveGoldenEvalStatus.UNAVAILABLE:
        return "UNAVAILABLE"
    return "FAIL"


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _optional_value(value: object | None) -> str:
    return str(value) if value is not None else "n/a"


def _joined(values: tuple[str, ...]) -> str:
    return "; ".join(values) or "none"


def _select_cases(
    case_id: str | None,
    *,
    fixture_group: GoldenFixtureSelection,
) -> tuple[GoldenDemoCase, ...]:
    try:
        cases = golden_demo_cases(fixture_group=fixture_group)
    except ValueError as exc:
        raise GoldenEvalError(str(exc)) from exc
    if case_id is None:
        return cases
    selected = tuple(case for case in cases if case.case_id == case_id)
    if not selected:
        raise GoldenEvalError(
            f"Unknown golden case ID: {case_id} for fixture group {fixture_group}"
        )
    return selected


def _live_golden_eval_prompt(case: GoldenDemoCase) -> dict[str, Any]:
    return {
        "task": (
            "Decide the bid/no-bid outcome for this golden procurement case "
            "using only the provided evidence_board. Return a JSON object "
            "matching output_schema."
        ),
        "rules": [
            "Do not use external sources.",
            "Every material claim must cite evidence_refs from evidence_board.",
            "Unsupported material claims belong in validation_errors.",
            "Use verdict values bid, no_bid, conditional_bid, or needs_human_review.",
        ],
        "case": {
            "case_id": case.case_id,
            "title": case.title,
            "fixture_group": case.fixture_group,
            "adversarial_category": case.adversarial_category,
            "evidence_board": [
                evidence_item.model_dump(mode="json")
                for evidence_item in case.evidence_board
            ],
        },
        "output_schema": GoldenActualOutcome.model_json_schema(),
    }


def _anthropic_response_text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, Sequence):
        parts: list[str] = []
        for block in content:
            if isinstance(block, Mapping):
                text = block.get("text")
            else:
                text = getattr(block, "text", None)
            if text:
                parts.append(str(text))
        return "\n".join(parts)
    return str(content)


def _parse_json_object(text: str) -> Mapping[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
        if match is None:
            raise
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, Mapping):
        raise ValueError("Anthropic response did not contain a JSON object.")
    return parsed


def _usage_value(response: Any, field_name: str) -> int | None:
    usage = getattr(response, "usage", None)
    value = _mapping_or_attr_value(usage, field_name)
    return int(value) if value is not None else None


def _response_float(response: Any, field_name: str) -> float | None:
    value = _mapping_or_attr_value(response, field_name)
    return float(value) if value is not None else None


def _mapping_or_attr_value(value: Any, field_name: str) -> Any | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return value.get(field_name)
    return getattr(value, field_name, None)
