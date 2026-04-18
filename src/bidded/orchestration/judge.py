from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, ValidationError

from bidded.agents.schemas import (
    AgentRole,
    EvidenceReference,
    FinalVerdict,
    JudgeDecision,
    SupportedClaim,
    VoteSummary,
)
from bidded.orchestration.graph import (
    GraphRouteNode,
    InvalidGraphOutput,
    JudgeDecisionResult,
    JudgeHandler,
    PersistHandler,
)
from bidded.orchestration.state import (
    AgentOutputState,
    BidRunState,
    EvidenceItemState,
    EvidenceRef,
    EvidenceSourceType,
    FinalDecisionState,
    RebuttalState,
    ScoutOutputState,
    SpecialistMotionState,
    SpecialistRole,
    ValidationIssueState,
    Verdict,
)

DEMO_TENANT_KEY = "demo"


class JudgeDecisionValidationError(ValueError):
    """Raised when a mocked or real Judge artifact is not audit-valid."""

    def __init__(self, message: str, *, field_path: str | None = None) -> None:
        super().__init__(message)
        self.field_path = field_path


class JudgeDecisionPersistenceError(RuntimeError):
    """Raised when the orchestrator cannot persist a final decision."""


class JudgeDecisionRequest(BaseModel):
    """Validated, evidence-locked input passed to the Judge."""

    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    company_id: UUID
    tender_id: UUID
    document_ids: tuple[UUID, ...]
    evidence_board: tuple[EvidenceItemState, ...]
    scout_output: ScoutOutputState
    motions: dict[AgentRole, SpecialistMotionState]
    rebuttals: dict[AgentRole, RebuttalState]
    vote_summary: VoteSummary
    formal_compliance_blockers: tuple[SupportedClaim, ...] = ()
    potential_blockers: tuple[SupportedClaim, ...] = ()


class JudgeDecisionModel(Protocol):
    """Small adapter surface for Claude or deterministic Judge tests."""

    def decide(
        self,
        request: JudgeDecisionRequest,
    ) -> JudgeDecision | Mapping[str, Any]: ...


JudgeDecisionDrafter = (
    JudgeDecisionModel
    | Callable[[JudgeDecisionRequest], JudgeDecision | Mapping[str, Any]]
)


class SupabaseDecisionPersistenceQuery(Protocol):
    def insert(self, payload: dict[str, Any]) -> SupabaseDecisionPersistenceQuery: ...

    def execute(self) -> Any: ...


class SupabaseDecisionPersistenceClient(Protocol):
    def table(self, table_name: str) -> SupabaseDecisionPersistenceQuery: ...


@dataclass(frozen=True)
class DecisionPersistenceResult:
    agent_run_id: UUID
    verdict: Verdict
    rows_returned: int


_AGENT_ROLE_BY_SPECIALIST: dict[SpecialistRole, AgentRole] = {
    SpecialistRole.COMPLIANCE: AgentRole.COMPLIANCE_OFFICER,
    SpecialistRole.WIN_STRATEGIST: AgentRole.WIN_STRATEGIST,
    SpecialistRole.DELIVERY_CFO: AgentRole.DELIVERY_CFO,
    SpecialistRole.RED_TEAM: AgentRole.RED_TEAM,
}
def build_judge_handler(model: JudgeDecisionDrafter) -> JudgeHandler:
    """Build a graph handler from a Claude-like Judge adapter."""

    def handler(state: BidRunState) -> JudgeDecisionResult | InvalidGraphOutput:
        try:
            request = build_judge_decision_request(state)
            raw_output = _draft_judge_decision(model, request)
            validated = validate_judge_decision_output(
                raw_output,
                evidence_board=state.evidence_board,
                expected_vote_summary=request.vote_summary,
                formal_compliance_blockers=request.formal_compliance_blockers,
            )
            return judge_decision_result_from_agent_output(validated)
        except JudgeDecisionValidationError as exc:
            return InvalidGraphOutput(
                source=GraphRouteNode.JUDGE,
                message=str(exc),
                field_path=exc.field_path,
            )

    return handler


def build_judge_decision_request(state: BidRunState) -> JudgeDecisionRequest:
    """Create the Judge request after all motions and rebuttals validate."""

    if state.scout_output is None:
        raise JudgeDecisionValidationError(
            "Judge decisions require completed Evidence Scout output.",
            field_path="scout_output",
        )
    _validate_complete_motion_set(state.motions, field_path="motions")
    _validate_complete_rebuttal_set(state.rebuttals, field_path="rebuttals")

    formal_blockers = _formal_compliance_blockers_from_agent_outputs(state)
    potential_blockers = _potential_blockers_from_agent_outputs(state)
    _validate_supported_claims(
        formal_blockers,
        evidence_board=state.evidence_board,
        field_path="formal_compliance_blockers",
    )
    _validate_supported_claims(
        potential_blockers,
        evidence_board=state.evidence_board,
        field_path="potential_blockers",
    )

    return JudgeDecisionRequest(
        run_id=state.run_id,
        company_id=state.company_id,
        tender_id=state.tender_id,
        document_ids=tuple(state.document_ids),
        evidence_board=tuple(state.evidence_board),
        scout_output=state.scout_output,
        motions=_agent_role_motion_map(state.motions),
        rebuttals=_agent_role_rebuttal_map(state.rebuttals),
        vote_summary=_vote_summary_from_motions(state.motions),
        formal_compliance_blockers=tuple(formal_blockers),
        potential_blockers=tuple(potential_blockers),
    )


def validate_judge_decision_output(
    raw_output: JudgeDecision | Mapping[str, Any],
    *,
    evidence_board: Sequence[EvidenceItemState],
    expected_vote_summary: VoteSummary,
    formal_compliance_blockers: Sequence[SupportedClaim] = (),
) -> JudgeDecision:
    """Validate strict Judge schema and evidence refs against the board."""

    try:
        output = JudgeDecision.model_validate(raw_output)
    except ValidationError as exc:
        raise JudgeDecisionValidationError(
            str(exc),
            field_path=_field_path_from_validation_error(exc),
        ) from exc

    if output.vote_summary != expected_vote_summary:
        raise JudgeDecisionValidationError(
            "Judge vote_summary must match the validated Round 1 motions.",
            field_path="vote_summary",
        )

    _validate_evidence_ids(output.evidence_ids, evidence_board=evidence_board)
    _validate_judge_evidence_refs(output, evidence_board=evidence_board)

    gated_output = _apply_formal_compliance_gate(
        output,
        formal_compliance_blockers=formal_compliance_blockers,
    )
    _validate_verdict_semantics(gated_output)
    return gated_output


def judge_decision_result_from_agent_output(
    output: JudgeDecision,
) -> JudgeDecisionResult:
    """Convert a strict Judge artifact into graph state plus audit row."""

    evidence_refs = _dedupe_evidence_refs(_all_material_evidence_refs(output))
    final_decision = FinalDecisionState(
        verdict=Verdict(output.verdict.value),
        confidence=output.confidence,
        rationale=output.cited_memo,
        vote_summary=output.vote_summary.model_dump(),
        disagreement_summary=output.disagreement_summary,
        compliance_matrix=[
            item.model_dump(mode="json") for item in output.compliance_matrix
        ],
        compliance_blockers=[claim.claim for claim in output.compliance_blockers],
        potential_blockers=[claim.claim for claim in output.potential_blockers],
        risk_register=[risk.risk for risk in output.risk_register],
        missing_info=list(output.missing_info),
        potential_evidence_gaps=list(output.potential_evidence_gaps),
        recommended_actions=list(output.recommended_actions),
        cited_memo=output.cited_memo,
        evidence_ids=list(output.evidence_ids),
        evidence_refs=evidence_refs,
    )
    agent_output = AgentOutputState(
        agent_role=AgentRole.JUDGE.value,
        round_name="final_decision",
        output_type="decision",
        payload=output.model_dump(mode="json"),
        validation_errors=[
            ValidationIssueState(
                source=AgentRole.JUDGE.value,
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
    return JudgeDecisionResult(decision=final_decision, agent_output=agent_output)


def build_decision_persistence_handler(
    client: SupabaseDecisionPersistenceClient,
    *,
    tenant_key: str = DEMO_TENANT_KEY,
) -> PersistHandler:
    """Build an orchestrator-owned handler that writes bid_decisions."""

    def handler(state: BidRunState) -> InvalidGraphOutput | None:
        try:
            persist_final_decision(client, state, tenant_key=tenant_key)
        except JudgeDecisionPersistenceError as exc:
            return InvalidGraphOutput(
                source=GraphRouteNode.PERSIST_DECISION,
                message=str(exc),
                retryable=False,
            )
        except Exception as exc:  # pragma: no cover - depends on Supabase internals
            return InvalidGraphOutput(
                source=GraphRouteNode.PERSIST_DECISION,
                message=f"Failed to persist bid_decisions: {exc}",
                retryable=False,
            )
        return None

    return handler


def persist_final_decision(
    client: SupabaseDecisionPersistenceClient,
    state: BidRunState,
    *,
    tenant_key: str = DEMO_TENANT_KEY,
) -> DecisionPersistenceResult:
    """Persist the final Judge decision to Supabase-compatible bid_decisions."""

    if state.final_decision is None:
        raise JudgeDecisionPersistenceError("Cannot persist a missing Judge decision.")

    final_payload = _final_decision_payload(state)
    payload = {
        "tenant_key": tenant_key,
        "agent_run_id": str(state.run_id),
        "final_decision": final_payload,
        "verdict": state.final_decision.verdict.value,
        "confidence": state.final_decision.confidence,
        "evidence_ids": [
            str(evidence_id) for evidence_id in state.final_decision.evidence_ids
        ],
        "metadata": {
            "source_agent_outputs": _source_agent_output_refs(state.agent_outputs),
        },
    }
    response = client.table("bid_decisions").insert(payload).execute()
    data = getattr(response, "data", [])
    rows_returned = len(data) if isinstance(data, list) else 0
    return DecisionPersistenceResult(
        agent_run_id=state.run_id,
        verdict=state.final_decision.verdict,
        rows_returned=rows_returned,
    )


def _draft_judge_decision(
    model: JudgeDecisionDrafter,
    request: JudgeDecisionRequest,
) -> JudgeDecision | Mapping[str, Any]:
    if hasattr(model, "decide"):
        return model.decide(request)
    return model(request)


def _validate_complete_motion_set(
    motions: Mapping[SpecialistRole, SpecialistMotionState],
    *,
    field_path: str,
) -> None:
    missing_roles = set(SpecialistRole) - set(motions)
    if missing_roles:
        missing = ", ".join(sorted(role.value for role in missing_roles))
        raise JudgeDecisionValidationError(
            f"Judge decisions require all validated Round 1 motions: {missing}.",
            field_path=field_path,
        )


def _validate_complete_rebuttal_set(
    rebuttals: Mapping[SpecialistRole, RebuttalState],
    *,
    field_path: str,
) -> None:
    missing_roles = set(SpecialistRole) - set(rebuttals)
    if missing_roles:
        missing = ", ".join(sorted(role.value for role in missing_roles))
        raise JudgeDecisionValidationError(
            f"Judge decisions require all validated Round 2 rebuttals: {missing}.",
            field_path=field_path,
        )


def _agent_role_motion_map(
    motions: Mapping[SpecialistRole, SpecialistMotionState],
) -> dict[AgentRole, SpecialistMotionState]:
    return {
        _AGENT_ROLE_BY_SPECIALIST[role]: motion
        for role, motion in sorted(
            motions.items(),
            key=lambda item: item[0].value,
        )
    }


def _agent_role_rebuttal_map(
    rebuttals: Mapping[SpecialistRole, RebuttalState],
) -> dict[AgentRole, RebuttalState]:
    return {
        _AGENT_ROLE_BY_SPECIALIST[role]: rebuttal
        for role, rebuttal in sorted(
            rebuttals.items(),
            key=lambda item: item[0].value,
        )
    }


def _vote_summary_from_motions(
    motions: Mapping[SpecialistRole, SpecialistMotionState],
) -> VoteSummary:
    counts = {verdict.value: 0 for verdict in Verdict}
    for motion in motions.values():
        counts[motion.verdict.value] = counts.get(motion.verdict.value, 0) + 1
    return VoteSummary(
        bid=counts[Verdict.BID.value],
        no_bid=counts[Verdict.NO_BID.value],
        conditional_bid=counts[Verdict.CONDITIONAL_BID.value],
    )


def _formal_compliance_blockers_from_agent_outputs(
    state: BidRunState,
) -> list[SupportedClaim]:
    compliance_rows = [
        output
        for output in state.agent_outputs
        if output.agent_role == AgentRole.COMPLIANCE_OFFICER.value
        and output.round_name == "round_1_motion"
        and output.output_type == "motion"
    ]
    blockers: list[SupportedClaim] = []
    for row in compliance_rows:
        blockers.extend(
            _supported_claims_from_payload(
                row.payload.get("formal_blockers", []),
                field_path="agent_outputs.compliance_officer.formal_blockers",
            )
        )
    return _dedupe_supported_claims(blockers)


def _potential_blockers_from_agent_outputs(state: BidRunState) -> list[SupportedClaim]:
    blockers: list[SupportedClaim] = []
    for row in state.agent_outputs:
        if row.round_name != "round_1_motion" or row.output_type != "motion":
            continue
        blockers.extend(
            _supported_claims_from_payload(
                row.payload.get("potential_blockers", []),
                field_path=f"agent_outputs.{row.agent_role}.potential_blockers",
            )
        )
    return _dedupe_supported_claims(blockers)


def _supported_claims_from_payload(
    raw_claims: Any,
    *,
    field_path: str,
) -> list[SupportedClaim]:
    if raw_claims is None:
        return []
    if not isinstance(raw_claims, list):
        raise JudgeDecisionValidationError(
            f"{field_path} must be a list.",
            field_path=field_path,
        )

    claims: list[SupportedClaim] = []
    for index, raw_claim in enumerate(raw_claims):
        try:
            claims.append(SupportedClaim.model_validate(raw_claim))
        except ValidationError as exc:
            raise JudgeDecisionValidationError(
                str(exc),
                field_path=f"{field_path}[{index}]",
            ) from exc
    return claims


def _validate_supported_claims(
    claims: Sequence[SupportedClaim],
    *,
    evidence_board: Sequence[EvidenceItemState],
    field_path: str,
) -> None:
    for index, claim in enumerate(claims):
        _validate_evidence_refs(
            claim.evidence_refs,
            evidence_board=evidence_board,
            field_path=f"{field_path}[{index}].evidence_refs",
        )


def _validate_evidence_ids(
    evidence_ids: Sequence[UUID],
    *,
    evidence_board: Sequence[EvidenceItemState],
) -> None:
    known_ids = {item.evidence_id for item in evidence_board if item.evidence_id}
    unknown_ids = [
        evidence_id for evidence_id in evidence_ids if evidence_id not in known_ids
    ]
    if unknown_ids:
        raise JudgeDecisionValidationError(
            (
                "Judge evidence_ids must resolve against evidence_board: "
                + ", ".join(str(evidence_id) for evidence_id in unknown_ids)
            ),
            field_path="evidence_ids",
        )


def _validate_judge_evidence_refs(
    output: JudgeDecision,
    *,
    evidence_board: Sequence[EvidenceItemState],
) -> None:
    _validate_evidence_refs(
        _all_material_evidence_refs(output),
        evidence_board=evidence_board,
        field_path="evidence_refs",
    )


def _validate_evidence_refs(
    evidence_refs: Sequence[EvidenceReference],
    *,
    evidence_board: Sequence[EvidenceItemState],
    field_path: str,
) -> None:
    for evidence_ref in evidence_refs:
        if _matching_evidence_item(evidence_ref, evidence_board) is None:
            raise JudgeDecisionValidationError(
                (
                    f"{evidence_ref.evidence_key} with evidence_id "
                    f"{evidence_ref.evidence_id} is not present in evidence_board."
                ),
                field_path=field_path,
            )


def _validate_verdict_semantics(output: JudgeDecision) -> None:
    if (
        output.verdict is FinalVerdict.CONDITIONAL_BID
        and not output.recommended_actions
    ):
        raise JudgeDecisionValidationError(
            "conditional_bid Judge decisions require explicit recommended_actions.",
            field_path="recommended_actions",
        )

    if output.verdict is FinalVerdict.NEEDS_HUMAN_REVIEW and not (
        output.missing_info or output.potential_evidence_gaps
    ):
        raise JudgeDecisionValidationError(
            (
                "needs_human_review Judge decisions require critical missing "
                "information or evidence gaps."
            ),
            field_path="missing_info",
        )


def _apply_formal_compliance_gate(
    output: JudgeDecision,
    *,
    formal_compliance_blockers: Sequence[SupportedClaim],
) -> JudgeDecision:
    if not formal_compliance_blockers:
        return output

    compliance_blockers = _dedupe_supported_claims(
        [*output.compliance_blockers, *formal_compliance_blockers]
    )
    cited_memo = output.cited_memo
    gate_sentence = "Formal compliance blockers require no_bid under the Judge gate."
    if gate_sentence not in cited_memo:
        cited_memo = f"{cited_memo} {gate_sentence}"

    return output.model_copy(
        update={
            "verdict": FinalVerdict.NO_BID,
            "compliance_blockers": compliance_blockers,
            "cited_memo": cited_memo,
        }
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


def _all_material_evidence_refs(output: JudgeDecision) -> list[EvidenceReference]:
    return [
        *output.evidence_refs,
        *[
            evidence_ref
            for item in output.compliance_matrix
            for evidence_ref in item.evidence_refs
        ],
        *[
            evidence_ref
            for claim in output.compliance_blockers
            for evidence_ref in claim.evidence_refs
        ],
        *[
            evidence_ref
            for claim in output.potential_blockers
            for evidence_ref in claim.evidence_refs
        ],
        *[
            evidence_ref
            for risk in output.risk_register
            for evidence_ref in risk.evidence_refs
        ],
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


def _dedupe_supported_claims(
    claims: Sequence[SupportedClaim],
) -> list[SupportedClaim]:
    deduped: list[SupportedClaim] = []
    seen: set[str] = set()
    for claim in claims:
        if claim.claim in seen:
            continue
        seen.add(claim.claim)
        deduped.append(claim)
    return deduped


def _final_decision_payload(state: BidRunState) -> dict[str, Any]:
    judge_output = next(
        (
            output
            for output in reversed(state.agent_outputs)
            if output.agent_role == AgentRole.JUDGE.value
            and output.round_name == "final_decision"
            and output.output_type == "decision"
        ),
        None,
    )
    if judge_output is not None:
        return dict(judge_output.payload)
    if state.final_decision is None:
        raise JudgeDecisionPersistenceError("Cannot persist a missing Judge decision.")
    return state.final_decision.model_dump(mode="json")


def _source_agent_output_refs(
    agent_outputs: Sequence[AgentOutputState],
) -> list[dict[str, str]]:
    return [
        {
            "agent_role": output.agent_role,
            "round_name": output.round_name,
            "output_type": output.output_type,
        }
        for output in agent_outputs
    ]


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
    "DecisionPersistenceResult",
    "JudgeDecisionDrafter",
    "JudgeDecisionModel",
    "JudgeDecisionPersistenceError",
    "JudgeDecisionRequest",
    "JudgeDecisionValidationError",
    "SupabaseDecisionPersistenceClient",
    "build_decision_persistence_handler",
    "build_judge_decision_request",
    "build_judge_handler",
    "judge_decision_result_from_agent_output",
    "persist_final_decision",
    "validate_judge_decision_output",
]
