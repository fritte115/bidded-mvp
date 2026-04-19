from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path

from pydantic import Field

from bidded.fixtures.golden_cases import GoldenDemoCase, golden_demo_cases
from bidded.orchestration.state import (
    EvidenceItemState,
    EvidenceRef,
    StrictStateModel,
    Verdict,
)


class GoldenEvalError(ValueError):
    """Raised when a golden eval cannot be configured or selected."""


class GoldenActualOutcome(StrictStateModel):
    """Actual output produced for a golden case by a recorded or mocked runner."""

    verdict: Verdict
    blockers: tuple[str, ...] = ()
    missing_info: tuple[str, ...] = ()
    recommended_actions: tuple[str, ...] = ()
    unsupported_claims_rejected: tuple[str, ...] = ()
    validation_errors: tuple[str, ...] = ()
    evidence_refs: tuple[EvidenceRef, ...] = Field(default_factory=tuple)


class GoldenCaseEvalResult(StrictStateModel):
    """Comparison result for one golden case."""

    case_id: str
    title: str
    passed: bool
    expected_verdict: Verdict
    actual_verdict: Verdict
    missing_required_blockers: tuple[str, ...] = ()
    unexpected_hard_blockers: tuple[str, ...] = ()
    missing_required_missing_info: tuple[str, ...] = ()
    missing_required_recommended_actions: tuple[str, ...] = ()
    missing_expected_unsupported_claim_rejections: tuple[str, ...] = ()
    unexpected_unsupported_claim_rejections: tuple[str, ...] = ()
    missing_expected_validation_errors: tuple[str, ...] = ()
    unexpected_validation_errors: tuple[str, ...] = ()
    actual_validation_errors: tuple[str, ...] = ()
    evidence_reference_failures: tuple[str, ...] = ()


class GoldenEvalReport(StrictStateModel):
    """Stable top-level result for a golden eval run."""

    passed: bool
    total_count: int
    passed_count: int
    failed_count: int
    results: tuple[GoldenCaseEvalResult, ...]


GoldenOutcomeProvider = Callable[[GoldenDemoCase], GoldenActualOutcome]


def run_golden_evals(
    *,
    case_id: str | None = None,
    outcome_provider: GoldenOutcomeProvider | None = None,
) -> GoldenEvalReport:
    """Run deterministic golden evals over all cases or one selected case."""

    cases = _select_cases(case_id)
    provider = outcome_provider or recorded_golden_outcome
    results = tuple(
        evaluate_golden_case(case, actual=provider(case)) for case in cases
    )
    passed_count = sum(1 for result in results if result.passed)
    failed_count = len(results) - passed_count
    return GoldenEvalReport(
        passed=failed_count == 0,
        total_count=len(results),
        passed_count=passed_count,
        failed_count=failed_count,
        results=results,
    )


def recorded_golden_outcome(case: GoldenDemoCase) -> GoldenActualOutcome:
    """Return the recorded deterministic outcome for a golden fixture case."""

    return GoldenActualOutcome(
        verdict=case.expected.verdict,
        blockers=case.expected.blockers,
        missing_info=case.expected.missing_info,
        recommended_actions=case.expected.recommended_actions,
        unsupported_claims_rejected=case.expected.unsupported_claims_rejected,
        validation_errors=case.expected.validation_errors,
        evidence_refs=case.expected.required_evidence_refs,
    )


def evaluate_golden_case(
    case: GoldenDemoCase,
    *,
    actual: GoldenActualOutcome,
) -> GoldenCaseEvalResult:
    """Compare one actual outcome against the golden case expectations."""

    evidence_reference_failures = _evidence_reference_failures(
        actual.evidence_refs,
        required_refs=case.expected.required_evidence_refs,
        evidence_board=case.evidence_board,
    )
    missing_required_blockers = _missing_required(
        case.expected.blockers,
        actual.blockers,
    )
    unexpected_hard_blockers = _unexpected(actual.blockers, case.expected.blockers)
    missing_required_missing_info = _missing_required(
        case.expected.missing_info,
        actual.missing_info,
    )
    missing_required_recommended_actions = _missing_required(
        case.expected.recommended_actions,
        actual.recommended_actions,
    )
    missing_expected_unsupported_claim_rejections = _missing_required(
        case.expected.unsupported_claims_rejected,
        actual.unsupported_claims_rejected,
    )
    unexpected_unsupported_claim_rejections = _unexpected(
        actual.unsupported_claims_rejected,
        case.expected.unsupported_claims_rejected,
    )
    missing_expected_validation_errors = _missing_required(
        case.expected.validation_errors,
        actual.validation_errors,
    )
    unexpected_validation_errors = _unexpected(
        actual.validation_errors,
        case.expected.validation_errors,
    )
    passed = not any(
        (
            actual.verdict != case.expected.verdict,
            missing_required_blockers,
            unexpected_hard_blockers,
            missing_required_missing_info,
            missing_required_recommended_actions,
            missing_expected_unsupported_claim_rejections,
            unexpected_unsupported_claim_rejections,
            missing_expected_validation_errors,
            unexpected_validation_errors,
            evidence_reference_failures,
        )
    )

    return GoldenCaseEvalResult(
        case_id=case.case_id,
        title=case.title,
        passed=passed,
        expected_verdict=case.expected.verdict,
        actual_verdict=actual.verdict,
        missing_required_blockers=missing_required_blockers,
        unexpected_hard_blockers=unexpected_hard_blockers,
        missing_required_missing_info=missing_required_missing_info,
        missing_required_recommended_actions=missing_required_recommended_actions,
        missing_expected_unsupported_claim_rejections=(
            missing_expected_unsupported_claim_rejections
        ),
        unexpected_unsupported_claim_rejections=(
            unexpected_unsupported_claim_rejections
        ),
        missing_expected_validation_errors=missing_expected_validation_errors,
        unexpected_validation_errors=unexpected_validation_errors,
        actual_validation_errors=actual.validation_errors,
        evidence_reference_failures=evidence_reference_failures,
    )


def write_golden_eval_json(report: GoldenEvalReport, path: Path) -> None:
    """Write a deterministic JSON representation of an eval report."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = report.model_dump(mode="json")
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _select_cases(case_id: str | None) -> tuple[GoldenDemoCase, ...]:
    cases = golden_demo_cases()
    if case_id is None:
        return cases

    selected = tuple(case for case in cases if case.case_id == case_id)
    if not selected:
        raise GoldenEvalError(f"Unknown golden case ID: {case_id}")
    return selected


def _missing_required(
    required_values: Sequence[str],
    actual_values: Sequence[str],
) -> tuple[str, ...]:
    actual = set(actual_values)
    return tuple(value for value in required_values if value not in actual)


def _unexpected(
    actual_values: Sequence[str],
    expected_values: Sequence[str],
) -> tuple[str, ...]:
    expected = set(expected_values)
    return tuple(value for value in actual_values if value not in expected)


def _evidence_reference_failures(
    actual_refs: Sequence[EvidenceRef],
    *,
    required_refs: Sequence[EvidenceRef],
    evidence_board: Sequence[EvidenceItemState],
) -> tuple[str, ...]:
    failures: list[str] = []
    actual_ref_keys = {_evidence_ref_identity(ref) for ref in actual_refs}
    for required_ref in required_refs:
        if _evidence_ref_identity(required_ref) not in actual_ref_keys:
            failures.append(
                f"missing required evidence ref: {required_ref.evidence_key}"
            )

    board_by_key = {item.evidence_key: item for item in evidence_board}
    for actual_ref in actual_refs:
        board_item = board_by_key.get(actual_ref.evidence_key)
        if board_item is None:
            failures.append(f"unresolved evidence ref: {actual_ref.evidence_key}")
            continue
        if board_item.source_type is not actual_ref.source_type:
            failures.append(
                "wrong evidence source for "
                f"{actual_ref.evidence_key}: {actual_ref.source_type.value}"
            )
        if actual_ref.evidence_id is None:
            failures.append(f"missing evidence_id for: {actual_ref.evidence_key}")
        elif board_item.evidence_id != actual_ref.evidence_id:
            failures.append(f"wrong evidence_id for: {actual_ref.evidence_key}")

    return tuple(dict.fromkeys(failures))


def _evidence_ref_identity(ref: EvidenceRef) -> tuple[str, str, str | None]:
    return (
        ref.evidence_key,
        ref.source_type.value,
        str(ref.evidence_id) if ref.evidence_id is not None else None,
    )
