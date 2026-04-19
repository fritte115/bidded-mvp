from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, ValidationError

from bidded.agents.schemas import AgentRole, EvidenceReference, Round1Motion
from bidded.orchestration.contract_clause_audit import (
    ContractClauseCoverageWarning,
    audit_contract_clause_coverage,
)
from bidded.orchestration.evidence_recall import (
    EvidenceRecallWarning,
    audit_evidence_recall,
)
from bidded.orchestration.graph import (
    GraphRouteNode,
    InvalidGraphOutput,
    Round1Handler,
    Round1MotionResult,
)
from bidded.orchestration.requirement_context import (
    RequirementEvidenceContext,
    build_requirement_context,
)
from bidded.orchestration.state import (
    AgentOutputState,
    BidRunState,
    EvidenceItemState,
    EvidenceRef,
    EvidenceSourceType,
    ScoutOutputState,
    SpecialistMotionState,
    SpecialistRole,
    ValidationIssueState,
    Verdict,
)
from bidded.requirements import RequirementType


class Round1MotionValidationError(ValueError):
    """Raised when a mocked or real specialist motion is not audit-valid."""

    def __init__(self, message: str, *, field_path: str | None = None) -> None:
        super().__init__(message)
        self.field_path = field_path


class Round1SpecialistRequest(BaseModel):
    """Evidence-locked input passed independently to one Round 1 specialist."""

    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    company_id: UUID
    tender_id: UUID
    document_ids: tuple[UUID, ...]
    agent_role: AgentRole
    evidence_board: tuple[EvidenceItemState, ...]
    requirement_context: tuple[RequirementEvidenceContext, ...] = ()
    evidence_recall_warnings: tuple[EvidenceRecallWarning, ...] = ()
    contract_clause_audit_warnings: tuple[ContractClauseCoverageWarning, ...] = ()
    scout_output: ScoutOutputState


class Round1SpecialistModel(Protocol):
    """Small adapter surface for Claude or deterministic Round 1 tests."""

    def draft_motion(
        self,
        request: Round1SpecialistRequest,
    ) -> Round1Motion | Mapping[str, Any]: ...


Round1SpecialistDrafter = (
    Round1SpecialistModel
    | Callable[[Round1SpecialistRequest], Round1Motion | Mapping[str, Any]]
)

_AGENT_ROLE_BY_SPECIALIST: dict[SpecialistRole, AgentRole] = {
    SpecialistRole.COMPLIANCE: AgentRole.COMPLIANCE_OFFICER,
    SpecialistRole.WIN_STRATEGIST: AgentRole.WIN_STRATEGIST,
    SpecialistRole.DELIVERY_CFO: AgentRole.DELIVERY_CFO,
    SpecialistRole.RED_TEAM: AgentRole.RED_TEAM,
}
_SPECIALIST_BY_AGENT_ROLE: dict[AgentRole, SpecialistRole] = {
    agent_role: specialist_role
    for specialist_role, agent_role in _AGENT_ROLE_BY_SPECIALIST.items()
}
_ROUND_1_ROUTE_BY_ROLE: dict[SpecialistRole, GraphRouteNode] = {
    SpecialistRole.COMPLIANCE: GraphRouteNode.ROUND_1_COMPLIANCE,
    SpecialistRole.WIN_STRATEGIST: GraphRouteNode.ROUND_1_WIN_STRATEGIST,
    SpecialistRole.DELIVERY_CFO: GraphRouteNode.ROUND_1_DELIVERY_CFO,
    SpecialistRole.RED_TEAM: GraphRouteNode.ROUND_1_RED_TEAM,
}
_FORMAL_BLOCKER_REQUIREMENT_TYPES = frozenset(
    {
        RequirementType.EXCLUSION_GROUND,
        RequirementType.QUALIFICATION_REQUIREMENT,
    }
)


def build_round_1_specialist_handler(
    model: Round1SpecialistDrafter,
) -> Round1Handler:
    """Build a graph handler from a Claude-like specialist motion adapter."""

    def handler(
        state: BidRunState,
        role: SpecialistRole,
    ) -> Round1MotionResult | InvalidGraphOutput:
        try:
            request = build_round_1_specialist_request(state, role)
            raw_output = _draft_round_1_motion(model, request)
            validated = validate_round_1_motion_output(
                raw_output,
                evidence_board=state.evidence_board,
                expected_role=role,
            )
            return round_1_motion_result_from_agent_output(validated)
        except Round1MotionValidationError as exc:
            return InvalidGraphOutput(
                source=_ROUND_1_ROUTE_BY_ROLE[role],
                message=str(exc),
                field_path=exc.field_path,
            )

    return handler


def build_round_1_specialist_request(
    state: BidRunState,
    role: SpecialistRole,
) -> Round1SpecialistRequest:
    """Create the independent Round 1 request without peer motions or context."""

    if state.scout_output is None:
        raise Round1MotionValidationError(
            "Round 1 specialist motions require completed Evidence Scout output.",
            field_path="scout_output",
        )

    return Round1SpecialistRequest(
        run_id=state.run_id,
        company_id=state.company_id,
        tender_id=state.tender_id,
        document_ids=tuple(state.document_ids),
        agent_role=_AGENT_ROLE_BY_SPECIALIST[role],
        evidence_board=tuple(state.evidence_board),
        requirement_context=build_requirement_context(state.evidence_board),
        evidence_recall_warnings=audit_evidence_recall(
            chunks=state.chunks,
            evidence_board=state.evidence_board,
        ),
        contract_clause_audit_warnings=audit_contract_clause_coverage(
            chunks=state.chunks,
            evidence_board=state.evidence_board,
        ),
        scout_output=state.scout_output,
    )


def validate_round_1_motion_output(
    raw_output: Round1Motion | Mapping[str, Any],
    *,
    evidence_board: Sequence[EvidenceItemState],
    expected_role: SpecialistRole,
) -> Round1Motion:
    """Validate strict motion schema and evidence refs against the board."""

    try:
        output = Round1Motion.model_validate(raw_output)
    except ValidationError as exc:
        raise Round1MotionValidationError(
            str(exc),
            field_path=_field_path_from_validation_error(exc),
        ) from exc

    expected_agent_role = _AGENT_ROLE_BY_SPECIALIST[expected_role]
    if output.agent_role is not expected_agent_role:
        raise Round1MotionValidationError(
            (
                f"Round 1 handler for {expected_agent_role.value} returned "
                f"{output.agent_role.value}."
            ),
            field_path="agent_role",
        )

    if not output.top_findings:
        raise Round1MotionValidationError(
            "Round 1 specialist motions require at least one evidence-backed finding.",
            field_path="top_findings",
        )

    if not (
        output.role_specific_risks
        or output.formal_blockers
        or output.potential_blockers
    ):
        raise Round1MotionValidationError(
            (
                "Round 1 specialist motions require at least one role-specific "
                "risk or blocker."
            ),
            field_path="role_specific_risks",
        )

    _validate_supported_claims(
        output.top_findings,
        evidence_board=evidence_board,
        field_name="top_findings",
    )
    _validate_supported_claims(
        output.role_specific_risks,
        evidence_board=evidence_board,
        field_name="role_specific_risks",
    )
    _validate_supported_claims(
        output.formal_blockers,
        evidence_board=evidence_board,
        field_name="formal_blockers",
    )
    _validate_formal_blocker_requirement_types(
        output.formal_blockers,
        evidence_board=evidence_board,
    )
    _validate_supported_claims(
        output.potential_blockers,
        evidence_board=evidence_board,
        field_name="potential_blockers",
    )
    return output


def round_1_motion_result_from_agent_output(
    output: Round1Motion,
) -> Round1MotionResult:
    """Convert a strict Round 1 artifact into graph state plus audit row."""

    evidence_refs = _dedupe_evidence_refs(_all_material_evidence_refs(output))
    motion = SpecialistMotionState(
        agent_role=_SPECIALIST_BY_AGENT_ROLE[output.agent_role],
        verdict=Verdict(output.vote.value),
        confidence=output.confidence,
        summary=_motion_summary(output),
        evidence_refs=evidence_refs,
        findings=[finding.claim for finding in output.top_findings],
        risks=[risk.claim for risk in output.role_specific_risks],
        blockers=[
            blocker.claim
            for blocker in [*output.formal_blockers, *output.potential_blockers]
        ],
        assumptions=list(output.assumptions),
        missing_info=list(output.missing_info),
        recommended_actions=list(output.recommended_actions),
    )
    agent_output = AgentOutputState(
        agent_role=output.agent_role.value,
        round_name="round_1_motion",
        output_type="motion",
        payload=output.model_dump(mode="json"),
        validation_errors=[
            ValidationIssueState(
                source=output.agent_role.value,
                message=error.message,
                field_path=error.field_path,
                evidence_refs=[
                    _state_ref_from_agent_ref(evidence_ref)
                    for evidence_ref in error.evidence_refs
                ],
            )
            for error in output.validation_errors
        ],
        evidence_refs=evidence_refs,
    )
    return Round1MotionResult(motion=motion, agent_output=agent_output)


def _draft_round_1_motion(
    model: Round1SpecialistDrafter,
    request: Round1SpecialistRequest,
) -> Round1Motion | Mapping[str, Any]:
    if hasattr(model, "draft_motion"):
        return model.draft_motion(request)
    return model(request)


def _validate_supported_claims(
    claims: Sequence[Any],
    *,
    evidence_board: Sequence[EvidenceItemState],
    field_name: str,
) -> None:
    for claim_index, claim in enumerate(claims):
        _validate_evidence_refs(
            claim.evidence_refs,
            evidence_board=evidence_board,
            field_path=f"{field_name}[{claim_index}].evidence_refs",
        )


def _validate_formal_blocker_requirement_types(
    claims: Sequence[Any],
    *,
    evidence_board: Sequence[EvidenceItemState],
) -> None:
    for claim_index, claim in enumerate(claims):
        matching_items = [
            item
            for evidence_ref in claim.evidence_refs
            if (item := _matching_evidence_item(evidence_ref, evidence_board))
            is not None
        ]
        if any(_is_formal_blocker_evidence(item) for item in matching_items):
            continue

        raise Round1MotionValidationError(
            (
                "formal_blockers must cite tender_document evidence classified as "
                "exclusion_ground or qualification_requirement."
            ),
            field_path=f"formal_blockers[{claim_index}].evidence_refs",
        )


def _validate_evidence_refs(
    evidence_refs: Sequence[EvidenceReference],
    *,
    evidence_board: Sequence[EvidenceItemState],
    field_path: str,
) -> None:
    for evidence_ref in evidence_refs:
        if _matching_evidence_item(evidence_ref, evidence_board) is None:
            raise Round1MotionValidationError(
                (
                    f"{evidence_ref.evidence_key} with evidence_id "
                    f"{evidence_ref.evidence_id} is not present in evidence_board."
                ),
                field_path=field_path,
            )


def _matching_evidence_item(
    evidence_ref: EvidenceReference,
    evidence_board: Sequence[EvidenceItemState],
) -> EvidenceItemState | None:
    return next(
        (
            item
            for item in evidence_board
            if item.evidence_key == evidence_ref.evidence_key
            and item.source_type.value == evidence_ref.source_type.value
            and item.evidence_id == evidence_ref.evidence_id
        ),
        None,
    )


def _is_formal_blocker_evidence(evidence: EvidenceItemState) -> bool:
    return (
        evidence.source_type is EvidenceSourceType.TENDER_DOCUMENT
        and evidence.requirement_type in _FORMAL_BLOCKER_REQUIREMENT_TYPES
    )


def _all_material_evidence_refs(output: Round1Motion) -> list[EvidenceReference]:
    return [
        evidence_ref
        for claim in [
            *output.top_findings,
            *output.role_specific_risks,
            *output.formal_blockers,
            *output.potential_blockers,
        ]
        for evidence_ref in claim.evidence_refs
    ]


def _state_ref_from_agent_ref(evidence_ref: EvidenceReference) -> EvidenceRef:
    return EvidenceRef(
        evidence_key=evidence_ref.evidence_key,
        source_type=EvidenceSourceType(evidence_ref.source_type.value),
        evidence_id=evidence_ref.evidence_id,
    )


def _dedupe_evidence_refs(
    evidence_refs: Sequence[EvidenceReference],
) -> list[EvidenceRef]:
    deduped: list[EvidenceRef] = []
    seen: set[tuple[str, str, UUID | None]] = set()
    for evidence_ref in evidence_refs:
        state_ref = _state_ref_from_agent_ref(evidence_ref)
        key = (
            state_ref.evidence_key,
            state_ref.source_type.value,
            state_ref.evidence_id,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(state_ref)
    return deduped


def _motion_summary(output: Round1Motion) -> str:
    if output.top_findings:
        return output.top_findings[0].claim
    return f"{output.agent_role.value} motion."


def _field_path_from_validation_error(exc: ValidationError) -> str | None:
    errors = exc.errors()
    if not errors:
        return None
    location = errors[0].get("loc", ())
    return _format_location(location)


def _format_location(location: Sequence[object]) -> str | None:
    if not location:
        return None

    path = ""
    for part in location:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path = f"{path}.{part}" if path else str(part)
    return path


__all__ = [
    "Round1MotionValidationError",
    "Round1SpecialistDrafter",
    "Round1SpecialistModel",
    "Round1SpecialistRequest",
    "build_round_1_specialist_handler",
    "build_round_1_specialist_request",
    "round_1_motion_result_from_agent_output",
    "validate_round_1_motion_output",
]
