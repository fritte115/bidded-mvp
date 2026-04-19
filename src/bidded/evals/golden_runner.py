from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from enum import StrEnum
from pathlib import Path

from pydantic import Field

from bidded.evals.decision_diff import NormalizedDecision
from bidded.fixtures.golden_cases import (
    GoldenDemoCase,
    GoldenFixtureSelection,
    golden_demo_cases,
)
from bidded.orchestration.state import (
    EvidenceItemState,
    EvidenceRef,
    EvidenceSourceType,
    StrictStateModel,
    Verdict,
)
from bidded.versioning import (
    GOLDEN_EVAL_FIXTURE_VERSION,
    VersionMetadata,
    default_version_metadata,
    normalize_version_metadata,
    version_metadata_warnings,
)


class GoldenEvalError(ValueError):
    """Raised when a golden eval cannot be configured or selected."""


class EvidenceCoverageClaimType(StrEnum):
    """Claim buckets evaluated by the golden evidence coverage scorer."""

    MATERIAL_FINDING = "material_finding"
    BLOCKER = "blocker"
    JUDGE_DECISION = "judge_decision"
    RISK_REGISTER_ENTRY = "risk_register_entry"
    RECOMMENDED_ACTION = "recommended_action"
    ASSUMPTION = "assumption"
    MISSING_INFO = "missing_info"
    POTENTIAL_EVIDENCE_GAP = "potential_evidence_gap"


class EvidenceCitationRequirement(StrEnum):
    """Evidence source requirements for one material claim."""

    ANY_EVIDENCE = "any_evidence"
    TENDER_DOCUMENT = "tender_document"
    COMPANY_PROFILE = "company_profile"
    TENDER_AND_COMPANY_WHEN_AVAILABLE = "tender_and_company_when_available"


class EvidenceCoverageClaim(StrictStateModel):
    """One actual claim whose evidence citation coverage can be scored."""

    claim_type: EvidenceCoverageClaimType
    claim: str = Field(min_length=1)
    citation_requirement: EvidenceCitationRequirement = (
        EvidenceCitationRequirement.ANY_EVIDENCE
    )
    evidence_refs: tuple[EvidenceRef, ...] = ()


class MissingCitationDetail(StrictStateModel):
    """Deterministic explanation for one uncovered material claim."""

    claim_type: EvidenceCoverageClaimType
    claim: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    missing_source_types: tuple[EvidenceSourceType, ...] = ()
    present_source_types: tuple[EvidenceSourceType, ...] = ()
    unresolved_evidence_refs: tuple[str, ...] = ()


class EvidenceCoverageScore(StrictStateModel):
    """Per-case citation coverage score for material eval claims."""

    score: float = Field(ge=0, le=1)
    threshold: float = Field(ge=0, le=1)
    passed: bool
    material_claim_count: int = Field(ge=0)
    covered_claim_count: int = Field(ge=0)
    unsupported_claim_count: int = Field(ge=0)
    missing_citation_details: tuple[MissingCitationDetail, ...] = ()


_MATERIAL_CLAIM_TYPES = frozenset(
    {
        EvidenceCoverageClaimType.MATERIAL_FINDING,
        EvidenceCoverageClaimType.BLOCKER,
        EvidenceCoverageClaimType.JUDGE_DECISION,
        EvidenceCoverageClaimType.RISK_REGISTER_ENTRY,
        EvidenceCoverageClaimType.RECOMMENDED_ACTION,
    }
)
_SOURCE_TYPE_ORDER = (
    EvidenceSourceType.TENDER_DOCUMENT,
    EvidenceSourceType.COMPANY_PROFILE,
)


def _default_evidence_coverage_score() -> EvidenceCoverageScore:
    return EvidenceCoverageScore(
        score=1.0,
        threshold=1.0,
        passed=True,
        material_claim_count=0,
        covered_claim_count=0,
        unsupported_claim_count=0,
    )


class GoldenActualOutcome(StrictStateModel):
    """Actual output produced for a golden case by a recorded or mocked runner."""

    verdict: Verdict
    confidence: float | None = Field(default=None, ge=0, le=1)
    specialist_votes: tuple[Verdict, ...] = ()
    blockers: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    missing_info: tuple[str, ...] = ()
    recommended_actions: tuple[str, ...] = ()
    unsupported_claims_rejected: tuple[str, ...] = ()
    validation_errors: tuple[str, ...] = ()
    evidence_refs: tuple[EvidenceRef, ...] = Field(default_factory=tuple)
    coverage_claims: tuple[EvidenceCoverageClaim, ...] = ()
    version_metadata: VersionMetadata | None = None


class GoldenCaseEvalResult(StrictStateModel):
    """Comparison result for one golden case."""

    case_id: str
    title: str
    passed: bool
    expected_verdict: Verdict
    allowed_verdicts: tuple[Verdict, ...] = ()
    actual_verdict: Verdict
    verdict_regression_failures: tuple[str, ...] = ()
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
    evidence_coverage: EvidenceCoverageScore = Field(
        default_factory=_default_evidence_coverage_score
    )
    actual_decision: NormalizedDecision | None = None
    version_metadata: VersionMetadata = Field(
        default_factory=lambda: default_version_metadata(
            eval_fixture_version=GOLDEN_EVAL_FIXTURE_VERSION
        )
    )
    version_warnings: tuple[str, ...] = ()


class GoldenEvalReport(StrictStateModel):
    """Stable top-level result for a golden eval run."""

    passed: bool
    total_count: int
    passed_count: int
    failed_count: int
    results: tuple[GoldenCaseEvalResult, ...]
    version_metadata: VersionMetadata = Field(
        default_factory=lambda: default_version_metadata(
            eval_fixture_version=GOLDEN_EVAL_FIXTURE_VERSION
        )
    )
    version_warnings: tuple[str, ...] = ()


GoldenOutcomeProvider = Callable[[GoldenDemoCase], GoldenActualOutcome]


def run_golden_evals(
    *,
    case_id: str | None = None,
    fixture_group: GoldenFixtureSelection = "core",
    outcome_provider: GoldenOutcomeProvider | None = None,
) -> GoldenEvalReport:
    """Run deterministic golden evals over all cases or one selected case."""

    cases = _select_cases(case_id, fixture_group=fixture_group)
    provider = outcome_provider or recorded_golden_outcome
    version_metadata = default_version_metadata(
        eval_fixture_version=GOLDEN_EVAL_FIXTURE_VERSION
    )
    results = tuple(
        evaluate_golden_case(
            case,
            actual=provider(case),
            fallback_version_metadata=version_metadata,
        )
        for case in cases
    )
    passed_count = sum(1 for result in results if result.passed)
    failed_count = len(results) - passed_count
    return GoldenEvalReport(
        passed=failed_count == 0,
        total_count=len(results),
        passed_count=passed_count,
        failed_count=failed_count,
        results=results,
        version_metadata=version_metadata,
        version_warnings=tuple(
            f"{result.case_id}: {warning}"
            for result in results
            for warning in result.version_warnings
        ),
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
        coverage_claims=_recorded_coverage_claims(case),
        version_metadata=default_version_metadata(
            eval_fixture_version=GOLDEN_EVAL_FIXTURE_VERSION
        ),
    )


def evaluate_golden_case(
    case: GoldenDemoCase,
    *,
    actual: GoldenActualOutcome,
    fallback_version_metadata: VersionMetadata | None = None,
) -> GoldenCaseEvalResult:
    """Compare one actual outcome against the golden case expectations."""

    version_metadata = normalize_version_metadata(
        actual.version_metadata or fallback_version_metadata,
        eval_fixture_version=GOLDEN_EVAL_FIXTURE_VERSION,
    )
    version_warnings = version_metadata_warnings(
        actual.version_metadata,
        require_eval_fixture_version=True,
    )
    evidence_reference_failures = _evidence_reference_failures(
        actual.evidence_refs,
        required_refs=case.expected.required_evidence_refs,
        evidence_board=case.evidence_board,
    )
    evidence_coverage = score_evidence_coverage(
        actual.coverage_claims,
        evidence_board=case.evidence_board,
    )
    verdict_regression_failures = _verdict_regression_failures(case, actual)
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
            verdict_regression_failures,
            missing_required_blockers,
            unexpected_hard_blockers,
            missing_required_missing_info,
            missing_required_recommended_actions,
            missing_expected_unsupported_claim_rejections,
            unexpected_unsupported_claim_rejections,
            missing_expected_validation_errors,
            unexpected_validation_errors,
            evidence_reference_failures,
            not evidence_coverage.passed,
        )
    )

    return GoldenCaseEvalResult(
        case_id=case.case_id,
        title=case.title,
        passed=passed,
        expected_verdict=case.expected.verdict,
        allowed_verdicts=case.expected.allowed_verdicts,
        actual_verdict=actual.verdict,
        verdict_regression_failures=verdict_regression_failures,
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
        evidence_coverage=evidence_coverage,
        actual_decision=_normalized_actual_decision(case.case_id, actual),
        version_metadata=version_metadata,
        version_warnings=version_warnings,
    )


def score_evidence_coverage(
    claims: Sequence[EvidenceCoverageClaim],
    *,
    evidence_board: Sequence[EvidenceItemState],
    threshold: float = 1.0,
) -> EvidenceCoverageScore:
    """Score whether material eval claims cite the required evidence sources."""

    board_by_key = {item.evidence_key: item for item in evidence_board}
    available_source_types = frozenset(item.source_type for item in evidence_board)
    material_claim_count = 0
    covered_claim_count = 0
    unsupported_claim_count = 0
    missing_citation_details: list[MissingCitationDetail] = []

    for claim in claims:
        if claim.claim_type not in _MATERIAL_CLAIM_TYPES:
            continue

        material_claim_count += 1
        required_source_types = _required_source_types(
            claim.citation_requirement,
            available_source_types=available_source_types,
        )
        present_source_types, unresolved_refs = _present_source_types(
            claim.evidence_refs,
            board_by_key=board_by_key,
        )

        if not claim.evidence_refs:
            unsupported_claim_count += 1
            missing_citation_details.append(
                MissingCitationDetail(
                    claim_type=claim.claim_type,
                    claim=claim.claim,
                    reason="unsupported_material_claim",
                    missing_source_types=required_source_types,
                    present_source_types=present_source_types,
                )
            )
            continue

        missing_source_types = tuple(
            source_type
            for source_type in required_source_types
            if source_type not in present_source_types
        )
        if unresolved_refs:
            missing_citation_details.append(
                MissingCitationDetail(
                    claim_type=claim.claim_type,
                    claim=claim.claim,
                    reason="unresolved_evidence_refs",
                    missing_source_types=missing_source_types,
                    present_source_types=present_source_types,
                    unresolved_evidence_refs=unresolved_refs,
                )
            )
            continue

        if missing_source_types:
            missing_citation_details.append(
                MissingCitationDetail(
                    claim_type=claim.claim_type,
                    claim=claim.claim,
                    reason="missing_required_source_type",
                    missing_source_types=missing_source_types,
                    present_source_types=present_source_types,
                )
            )
            continue

        covered_claim_count += 1

    score = (
        1.0
        if material_claim_count == 0
        else covered_claim_count / material_claim_count
    )
    return EvidenceCoverageScore(
        score=score,
        threshold=threshold,
        passed=score >= threshold,
        material_claim_count=material_claim_count,
        covered_claim_count=covered_claim_count,
        unsupported_claim_count=unsupported_claim_count,
        missing_citation_details=tuple(missing_citation_details),
    )


def write_golden_eval_json(report: GoldenEvalReport, path: Path) -> None:
    """Write a deterministic JSON representation of an eval report."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = report.model_dump(mode="json")
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _recorded_coverage_claims(
    case: GoldenDemoCase,
) -> tuple[EvidenceCoverageClaim, ...]:
    claims = [
        EvidenceCoverageClaim(
            claim_type=EvidenceCoverageClaimType.JUDGE_DECISION,
            claim=case.expected.rationale,
            citation_requirement=(
                EvidenceCitationRequirement.TENDER_AND_COMPANY_WHEN_AVAILABLE
            ),
            evidence_refs=case.expected.required_evidence_refs,
        )
    ]
    claims.extend(
        EvidenceCoverageClaim(
            claim_type=EvidenceCoverageClaimType.BLOCKER,
            claim=blocker,
            citation_requirement=(
                EvidenceCitationRequirement.TENDER_AND_COMPANY_WHEN_AVAILABLE
            ),
            evidence_refs=case.expected.required_evidence_refs,
        )
        for blocker in case.expected.blockers
    )
    claims.extend(
        EvidenceCoverageClaim(
            claim_type=EvidenceCoverageClaimType.RECOMMENDED_ACTION,
            claim=action,
            citation_requirement=(
                EvidenceCitationRequirement.TENDER_AND_COMPANY_WHEN_AVAILABLE
            ),
            evidence_refs=case.expected.required_evidence_refs,
        )
        for action in case.expected.recommended_actions
    )
    return tuple(claims)


def _normalized_actual_decision(
    case_id: str,
    actual: GoldenActualOutcome,
) -> NormalizedDecision:
    return NormalizedDecision(
        decision_id=case_id,
        verdict=actual.verdict.value,
        confidence=actual.confidence,
        blockers=actual.blockers,
        risks=tuple({"risk": risk} for risk in actual.risks),
        missing_info=actual.missing_info,
        recommended_actions=actual.recommended_actions,
        cited_evidence_keys=tuple(
            evidence_ref.evidence_key for evidence_ref in actual.evidence_refs
        ),
    )


def _required_source_types(
    citation_requirement: EvidenceCitationRequirement,
    *,
    available_source_types: frozenset[EvidenceSourceType],
) -> tuple[EvidenceSourceType, ...]:
    if citation_requirement is EvidenceCitationRequirement.ANY_EVIDENCE:
        return ()
    if citation_requirement is EvidenceCitationRequirement.TENDER_DOCUMENT:
        return (EvidenceSourceType.TENDER_DOCUMENT,)
    if citation_requirement is EvidenceCitationRequirement.COMPANY_PROFILE:
        return (EvidenceSourceType.COMPANY_PROFILE,)

    return _ordered_source_types(available_source_types)


def _present_source_types(
    evidence_refs: Sequence[EvidenceRef],
    *,
    board_by_key: dict[str, EvidenceItemState],
) -> tuple[tuple[EvidenceSourceType, ...], tuple[str, ...]]:
    source_types: list[EvidenceSourceType] = []
    unresolved_refs: list[str] = []
    for evidence_ref in evidence_refs:
        board_item = board_by_key.get(evidence_ref.evidence_key)
        if (
            board_item is None
            or board_item.source_type is not evidence_ref.source_type
            or evidence_ref.evidence_id is None
            or board_item.evidence_id != evidence_ref.evidence_id
        ):
            unresolved_refs.append(evidence_ref.evidence_key)
            continue
        source_types.append(board_item.source_type)

    return _ordered_source_types(source_types), tuple(dict.fromkeys(unresolved_refs))


def _ordered_source_types(
    source_types: Sequence[EvidenceSourceType] | frozenset[EvidenceSourceType],
) -> tuple[EvidenceSourceType, ...]:
    source_type_set = set(source_types)
    return tuple(
        source_type
        for source_type in _SOURCE_TYPE_ORDER
        if source_type in source_type_set
    )


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


def _verdict_regression_failures(
    case: GoldenDemoCase,
    actual: GoldenActualOutcome,
) -> tuple[str, ...]:
    if (
        "formal_blocker_gates_no_bid" in case.expected.decision_rules
        and case.expected.blockers
        and actual.verdict is not Verdict.NO_BID
    ):
        return ("formal compliance blocker requires no_bid",)

    if actual.verdict in case.expected.allowed_verdicts:
        return ()

    return (
        "actual verdict "
        f"{actual.verdict.value} not in allowed set: "
        f"{_verdict_values(case.expected.allowed_verdicts)}",
    )


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


def _verdict_values(verdicts: Sequence[Verdict]) -> str:
    return ", ".join(verdict.value for verdict in verdicts)


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
