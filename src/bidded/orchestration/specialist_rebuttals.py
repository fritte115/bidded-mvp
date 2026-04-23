from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from bidded.agents.schemas import (
    AgentRole,
    EvidenceReference,
    Round2Rebuttal,
)
from bidded.orchestration.evidence_refs import coerce_evidence_refs
from bidded.orchestration.graph import (
    GraphRouteNode,
    InvalidGraphOutput,
    Round2Handler,
    Round2RebuttalResult,
)
from bidded.orchestration.state import (
    AgentOutputState,
    BidRunState,
    EvidenceItemState,
    EvidenceRef,
    EvidenceSourceType,
    RebuttalState,
    ScoutOutputState,
    SpecialistMotionState,
    SpecialistRole,
    ValidationIssueState,
    Verdict,
)


class Round2RebuttalValidationError(ValueError):
    """Raised when a mocked or real specialist rebuttal is not audit-valid."""

    def __init__(self, message: str, *, field_path: str | None = None) -> None:
        super().__init__(message)
        self.field_path = field_path


class RebuttalFocusPoint(BaseModel):
    """Focused critique prompt derived from validated Round 1 artifacts."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal[
        "top_disagreement",
        "unsupported_claim",
        "blocker_challenge",
        "material_missing_info",
        "strongest_bid_argument",
        "conditional_bid_logic",
    ]
    target_role: AgentRole | None = None
    prompt: str = Field(min_length=1)


class Round2RebuttalRequest(BaseModel):
    """Evidence-locked input passed to one Round 2 specialist."""

    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    company_id: UUID
    tender_id: UUID
    document_ids: tuple[UUID, ...]
    agent_role: AgentRole
    evidence_board: tuple[EvidenceItemState, ...]
    scout_output: ScoutOutputState
    motions: dict[AgentRole, SpecialistMotionState]
    focus_points: tuple[RebuttalFocusPoint, ...]


class Round2RebuttalModel(Protocol):
    """Small adapter surface for Claude or deterministic Round 2 tests."""

    def draft_rebuttal(
        self,
        request: Round2RebuttalRequest,
    ) -> Round2Rebuttal | Mapping[str, Any]: ...


Round2RebuttalDrafter = (
    Round2RebuttalModel
    | Callable[[Round2RebuttalRequest], Round2Rebuttal | Mapping[str, Any]]
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
_ROUND_2_ROUTE_BY_ROLE: dict[SpecialistRole, GraphRouteNode] = {
    SpecialistRole.COMPLIANCE: GraphRouteNode.ROUND_2_COMPLIANCE,
    SpecialistRole.WIN_STRATEGIST: GraphRouteNode.ROUND_2_WIN_STRATEGIST,
    SpecialistRole.DELIVERY_CFO: GraphRouteNode.ROUND_2_DELIVERY_CFO,
    SpecialistRole.RED_TEAM: GraphRouteNode.ROUND_2_RED_TEAM,
}
_BID_POSITIVE_VERDICTS = {Verdict.BID, Verdict.CONDITIONAL_BID}


def _coerce_refs_list(
    refs: Any,
    board: Sequence[EvidenceItemState],
) -> list[dict[str, Any]]:
    """Normalize LLM-produced ``evidence_refs`` via the shared canonicalizer.

    See :func:`bidded.orchestration.evidence_refs.coerce_evidence_refs` —
    drops non-dict items, fills missing evidence_id from evidence_key (and
    vice versa) where the match is unambiguous, and drops refs that can't
    be resolved to a board item.
    """
    return coerce_evidence_refs(refs, board)


def _normalize_blocker_position(value: Any) -> Any:
    """Map verbose LLM position strings to the 3 allowed literal values."""
    if not isinstance(value, str):
        return value
    v = value.strip().lower()
    if any(k in v for k in ("reject", "dismiss", "invalid", "unfounded", "wrong")):
        return "reject"
    if any(k in v for k in ("partial", "downgrade", "reduce", "weaken", "moderate")):
        return "downgrade"
    # "confirm", "uphold", "support", "strengthen", "accept", "additional", etc.
    return "uphold"


def _coerce_rebuttal_item_refs(
    item: dict[str, Any],
    board: Sequence[EvidenceItemState],
) -> dict[str, Any]:
    out = dict(item)
    refs = out.get("evidence_refs")
    if refs is not None:
        out["evidence_refs"] = _coerce_refs_list(refs, board)
    if "position" in out:
        out["position"] = _normalize_blocker_position(out["position"])
    return out


def _normalize_agent_role(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip().lower().replace(" ", "_")
    return value


def _coerce_validation_error_item(item: Any) -> Any:
    if isinstance(item, str):
        return {"code": "llm_note", "message": item}
    return item


def _normalize_role_list(roles: Any) -> Any:
    if not isinstance(roles, list):
        return roles
    return [_normalize_agent_role(r) for r in roles]


def _coerce_disagreement_item(
    item: dict[str, Any],
    board: Sequence[EvidenceItemState],
) -> dict[str, Any]:
    out = _coerce_rebuttal_item_refs(item, board)
    if "target_role" in out:
        out["target_role"] = _normalize_agent_role(out["target_role"])
    return out


def _coerce_unsupported_claim_item(item: Any) -> Any:
    if not isinstance(item, dict):
        return item
    out = dict(item)
    if "target_role" in out:
        out["target_role"] = _normalize_agent_role(out["target_role"])
    return out


def _coerce_revised_stance(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() in ("null", "none", ""):
        return None
    return value


_ROUND_2_REBUTTAL_ALLOWED_KEYS = frozenset(
    {
        "agent_role",
        "target_roles",
        "targeted_disagreements",
        "unsupported_claims",
        "blocker_challenges",
        "revised_stance",
        "confidence",
        "evidence_refs",
        "missing_info",
        "potential_evidence_gaps",
        "recommended_actions",
        "validation_errors",
    }
)


def _coerce_round2_rebuttal_mapping(
    raw: Mapping[str, Any],
    evidence_board: Sequence[EvidenceItemState],
) -> dict[str, Any]:
    """Heal LLM-drift shape issues before strict Pydantic validation.

    Mirrors the Round 1 coercer. Whitelists top-level keys (``extra="forbid"``
    on the strict schema rejects anything else), normalizes agent_role /
    target_role / revised_stance / blocker positions, and canonicalizes every
    evidence_refs list via the shared helper (which drops refs that don't
    resolve to a board item and drops blocker_challenges whose refs become
    empty — the schema requires ``min_length=1`` on that list).
    """
    out = dict(raw)

    # Whitelist top-level keys first so extras don't survive to model_validate.
    for extra_key in list(out.keys()):
        if extra_key not in _ROUND_2_REBUTTAL_ALLOWED_KEYS:
            out.pop(extra_key, None)

    if "agent_role" in out:
        out["agent_role"] = _normalize_agent_role(out["agent_role"])
    # Normalize target_roles list
    if "target_roles" in out:
        out["target_roles"] = _normalize_role_list(out["target_roles"])
    # Coerce revised_stance "null" string → None
    if "revised_stance" in out:
        out["revised_stance"] = _coerce_revised_stance(out["revised_stance"])
    # Resolve top-level evidence_refs
    refs = out.get("evidence_refs")
    if isinstance(refs, list):
        out["evidence_refs"] = _coerce_refs_list(refs, evidence_board)
    # targeted_disagreements: normalize target_role + resolve evidence_refs.
    # Drop any disagreement whose refs list is empty after canonicalization —
    # the schema requires ``min_length=1`` on evidence_refs, so an empty list
    # would trip Pydantic validation and abort the whole rebuttal.
    disagreements = out.get("targeted_disagreements")
    if isinstance(disagreements, list):
        coerced_disagreements: list[Any] = []
        for d in disagreements:
            if not isinstance(d, dict):
                continue
            d = _coerce_disagreement_item(d, evidence_board)
            if not d.get("evidence_refs"):
                continue
            coerced_disagreements.append(d)
        out["targeted_disagreements"] = coerced_disagreements
    # unsupported_claims: normalize target_role
    unsupported = out.get("unsupported_claims")
    if isinstance(unsupported, list):
        out["unsupported_claims"] = [
            _coerce_unsupported_claim_item(c) for c in unsupported
        ]
    # blocker_challenges: resolve evidence_refs + normalize position
    # Drop any challenge that has no resolvable evidence_refs (schema requires min 1)
    challenges = out.get("blocker_challenges")
    if isinstance(challenges, list):
        coerced_challenges = []
        for c in challenges:
            if isinstance(c, dict):
                c = _coerce_rebuttal_item_refs(c, evidence_board)
                if not c.get("evidence_refs"):
                    continue
            coerced_challenges.append(c)
        out["blocker_challenges"] = coerced_challenges
    validation_errors = out.get("validation_errors")
    if isinstance(validation_errors, list):
        out["validation_errors"] = [
            _coerce_validation_error_item(e) for e in validation_errors
        ]
    return out


def build_round_2_rebuttal_handler(
    model: Round2RebuttalDrafter,
) -> Round2Handler:
    """Build a graph handler from a Claude-like specialist rebuttal adapter."""

    def handler(
        state: BidRunState,
        role: SpecialistRole,
    ) -> Round2RebuttalResult | InvalidGraphOutput:
        try:
            request = build_round_2_rebuttal_request(state, role)
            raw_output = _draft_round_2_rebuttal(model, request)
            validated = validate_round_2_rebuttal_output(
                raw_output,
                evidence_board=state.evidence_board,
                motions=state.motions,
                expected_role=role,
            )
            return round_2_rebuttal_result_from_agent_output(validated)
        except Round2RebuttalValidationError as exc:
            return InvalidGraphOutput(
                source=_ROUND_2_ROUTE_BY_ROLE[role],
                message=str(exc),
                field_path=exc.field_path,
            )

    return handler


def build_round_2_rebuttal_request(
    state: BidRunState,
    role: SpecialistRole,
) -> Round2RebuttalRequest:
    """Create the first cross-agent request after all Round 1 motions validate."""

    if state.scout_output is None:
        raise Round2RebuttalValidationError(
            "Round 2 rebuttals require completed Evidence Scout output.",
            field_path="scout_output",
        )
    _validate_complete_motion_set(state.motions, field_path="motions")

    return Round2RebuttalRequest(
        run_id=state.run_id,
        company_id=state.company_id,
        tender_id=state.tender_id,
        document_ids=tuple(state.document_ids),
        agent_role=_AGENT_ROLE_BY_SPECIALIST[role],
        evidence_board=tuple(state.evidence_board),
        scout_output=state.scout_output,
        motions=_agent_role_motion_map(state.motions),
        focus_points=_build_focus_points(state.motions, role),
    )


def validate_round_2_rebuttal_output(
    raw_output: Round2Rebuttal | Mapping[str, Any],
    *,
    evidence_board: Sequence[EvidenceItemState],
    motions: Mapping[SpecialistRole, SpecialistMotionState],
    expected_role: SpecialistRole,
) -> Round2Rebuttal:
    """Validate strict rebuttal schema and evidence refs against the board."""

    try:
        coerced = (
            raw_output
            if isinstance(raw_output, Round2Rebuttal)
            else _coerce_round2_rebuttal_mapping(raw_output, evidence_board)
        )
        output = Round2Rebuttal.model_validate(coerced)
    except ValidationError as exc:
        raise Round2RebuttalValidationError(
            str(exc),
            field_path=_field_path_from_validation_error(exc),
        ) from exc

    expected_agent_role = _AGENT_ROLE_BY_SPECIALIST[expected_role]
    if output.agent_role is not expected_agent_role:
        raise Round2RebuttalValidationError(
            (
                f"Round 2 handler for {expected_agent_role.value} returned "
                f"{output.agent_role.value}."
            ),
            field_path="agent_role",
        )

    _validate_complete_motion_set(motions, field_path="motions")
    _validate_target_roles(output)
    # Defensible coercion: drop evidence_refs that do not resolve against the
    # board before strict validation. The canonicalizer already tried every
    # field-swap the LLM commonly makes; anything unresolvable is a
    # hallucinated citation and should not crash the run.
    output = _drop_unsupported_rebuttal_refs(output, evidence_board=evidence_board)
    _validate_focused_rebuttal(output)
    _validate_red_team_scope(output, motions=motions, expected_role=expected_role)
    _validate_rebuttal_evidence_refs(output, evidence_board=evidence_board)
    return output


def round_2_rebuttal_result_from_agent_output(
    output: Round2Rebuttal,
) -> Round2RebuttalResult:
    """Convert a strict Round 2 artifact into graph state plus audit row."""

    evidence_refs = _dedupe_evidence_refs(_all_material_evidence_refs(output))
    rebuttal = RebuttalState(
        agent_role=_SPECIALIST_BY_AGENT_ROLE[output.agent_role],
        target_motion_role=_SPECIALIST_BY_AGENT_ROLE[output.target_roles[0]],
        confidence=output.confidence,
        summary=_rebuttal_summary(output),
        challenged_claims=[
            *[
                disagreement.disputed_claim
                for disagreement in output.targeted_disagreements
            ],
            *[claim.claim for claim in output.unsupported_claims],
            *[challenge.blocker for challenge in output.blocker_challenges],
        ],
        accepted_claims=[],
        evidence_refs=evidence_refs,
    )
    agent_output = AgentOutputState(
        agent_role=output.agent_role.value,
        round_name="round_2_rebuttal",
        output_type="rebuttal",
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
    return Round2RebuttalResult(rebuttal=rebuttal, agent_output=agent_output)


def _draft_round_2_rebuttal(
    model: Round2RebuttalDrafter,
    request: Round2RebuttalRequest,
) -> Round2Rebuttal | Mapping[str, Any]:
    if hasattr(model, "draft_rebuttal"):
        return model.draft_rebuttal(request)
    return model(request)


def _validate_complete_motion_set(
    motions: Mapping[SpecialistRole, SpecialistMotionState],
    *,
    field_path: str,
) -> None:
    expected_roles = set(SpecialistRole)
    actual_roles = set(motions)
    missing_roles = expected_roles - actual_roles
    if missing_roles:
        missing = ", ".join(sorted(role.value for role in missing_roles))
        raise Round2RebuttalValidationError(
            f"Round 2 rebuttals require all validated Round 1 motions: {missing}.",
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


def _build_focus_points(
    motions: Mapping[SpecialistRole, SpecialistMotionState],
    role: SpecialistRole,
) -> tuple[RebuttalFocusPoint, ...]:
    own_agent_role = _AGENT_ROLE_BY_SPECIALIST[role]
    points: list[RebuttalFocusPoint] = []

    if len({motion.verdict for motion in motions.values()}) > 1:
        vote_summary = ", ".join(
            f"{motion.agent_role.value}: {motion.verdict.value}"
            for motion in sorted(
                motions.values(),
                key=lambda motion: motion.agent_role.value,
            )
        )
        points.append(
            RebuttalFocusPoint(
                kind="top_disagreement",
                prompt=f"Resolve material vote disagreement: {vote_summary}.",
            )
        )

    for motion in sorted(motions.values(), key=lambda motion: motion.agent_role.value):
        target_role = _AGENT_ROLE_BY_SPECIALIST[motion.agent_role]
        if target_role is own_agent_role:
            continue

        if role is SpecialistRole.RED_TEAM and motion.verdict in _BID_POSITIVE_VERDICTS:
            points.append(
                RebuttalFocusPoint(
                    kind="strongest_bid_argument",
                    target_role=target_role,
                    prompt=motion.summary,
                )
            )

        if (
            role is SpecialistRole.RED_TEAM
            and motion.verdict is Verdict.CONDITIONAL_BID
        ):
            points.append(
                RebuttalFocusPoint(
                    kind="conditional_bid_logic",
                    target_role=target_role,
                    prompt=(
                        "Stress-test whether conditional-bid next actions make "
                        f"{target_role.value}'s stance defensible."
                    ),
                )
            )

        for blocker in motion.blockers:
            points.append(
                RebuttalFocusPoint(
                    kind="blocker_challenge",
                    target_role=target_role,
                    prompt=blocker,
                )
            )

        for missing_info in motion.missing_info:
            points.append(
                RebuttalFocusPoint(
                    kind="material_missing_info",
                    target_role=target_role,
                    prompt=missing_info,
                )
            )

        if motion.findings and not motion.evidence_refs:
            points.append(
                RebuttalFocusPoint(
                    kind="unsupported_claim",
                    target_role=target_role,
                    prompt=motion.findings[0],
                )
            )

    return tuple(points)


def _validate_target_roles(output: Round2Rebuttal) -> None:
    if output.agent_role in output.target_roles:
        raise Round2RebuttalValidationError(
            "Round 2 rebuttals must target peer specialist motions, not self.",
            field_path="target_roles",
        )

    target_role_set = set(output.target_roles)
    for index, disagreement in enumerate(output.targeted_disagreements):
        if disagreement.target_role not in target_role_set:
            raise Round2RebuttalValidationError(
                "Targeted disagreements must reference a declared target_role.",
                field_path=f"targeted_disagreements[{index}].target_role",
            )

    for index, unsupported_claim in enumerate(output.unsupported_claims):
        if unsupported_claim.target_role not in target_role_set:
            raise Round2RebuttalValidationError(
                "Unsupported claims must reference a declared target_role.",
                field_path=f"unsupported_claims[{index}].target_role",
            )


def _validate_focused_rebuttal(output: Round2Rebuttal) -> None:
    if (
        output.targeted_disagreements
        or output.unsupported_claims
        or output.blocker_challenges
        or output.missing_info
        or output.potential_evidence_gaps
    ):
        return

    raise Round2RebuttalValidationError(
        (
            "Round 2 rebuttals must focus on disagreements, unsupported claims, "
            "blocker challenges, missing information, or evidence gaps."
        ),
        field_path="targeted_disagreements",
    )


def _validate_red_team_scope(
    output: Round2Rebuttal,
    *,
    motions: Mapping[SpecialistRole, SpecialistMotionState],
    expected_role: SpecialistRole,
) -> None:
    if expected_role is not SpecialistRole.RED_TEAM:
        return

    targeted_roles = set(output.target_roles)
    bid_positive_roles = {
        _AGENT_ROLE_BY_SPECIALIST[role]
        for role, motion in motions.items()
        if role is not SpecialistRole.RED_TEAM
        and motion.verdict in _BID_POSITIVE_VERDICTS
    }
    if bid_positive_roles and targeted_roles.isdisjoint(bid_positive_roles):
        raise Round2RebuttalValidationError(
            "Red Team rebuttals must challenge the strongest bid arguments.",
            field_path="target_roles",
        )


def _drop_unsupported_rebuttal_refs(
    output: Round2Rebuttal,
    *,
    evidence_board: Sequence[EvidenceItemState],
) -> Round2Rebuttal:
    """Filter each evidence_refs list to only those that resolve against the
    board. Claims whose ref lists become empty (schema requires min_length=1)
    are dropped entirely rather than leaving invariant-violating objects in
    memory. The top-level `evidence_refs` list allows empty, so it's scrubbed
    in place.
    """

    def _kept(refs: Sequence[EvidenceReference]) -> list[EvidenceReference]:
        return [
            ref
            for ref in refs
            if _matching_evidence_item(ref, evidence_board) is not None
        ]

    new_top_refs = _kept(output.evidence_refs)

    new_targeted = []
    for d in output.targeted_disagreements:
        kept_refs = _kept(d.evidence_refs)
        if not kept_refs:
            continue
        new_targeted.append(d.model_copy(update={"evidence_refs": kept_refs}))

    new_blockers = []
    for c in output.blocker_challenges:
        kept_refs = _kept(c.evidence_refs)
        if not kept_refs:
            continue
        new_blockers.append(c.model_copy(update={"evidence_refs": kept_refs}))

    return output.model_copy(
        update={
            "evidence_refs": new_top_refs,
            "targeted_disagreements": new_targeted,
            "blocker_challenges": new_blockers,
        }
    )


def _validate_rebuttal_evidence_refs(
    output: Round2Rebuttal,
    *,
    evidence_board: Sequence[EvidenceItemState],
) -> None:
    for field_name, refs in _evidence_ref_groups(output):
        _validate_evidence_refs(
            refs,
            evidence_board=evidence_board,
            field_path=field_name,
        )


def _evidence_ref_groups(
    output: Round2Rebuttal,
) -> list[tuple[str, Sequence[EvidenceReference]]]:
    groups: list[tuple[str, Sequence[EvidenceReference]]] = [
        ("evidence_refs", output.evidence_refs)
    ]
    groups.extend(
        (
            f"targeted_disagreements[{index}].evidence_refs",
            disagreement.evidence_refs,
        )
        for index, disagreement in enumerate(output.targeted_disagreements)
    )
    groups.extend(
        (
            f"blocker_challenges[{index}].evidence_refs",
            challenge.evidence_refs,
        )
        for index, challenge in enumerate(output.blocker_challenges)
    )
    return groups


def _validate_evidence_refs(
    evidence_refs: Sequence[EvidenceReference],
    *,
    evidence_board: Sequence[EvidenceItemState],
    field_path: str,
) -> None:
    for evidence_ref in evidence_refs:
        if _matching_evidence_item(evidence_ref, evidence_board) is None:
            raise Round2RebuttalValidationError(
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


def _all_material_evidence_refs(output: Round2Rebuttal) -> list[EvidenceReference]:
    return [
        *output.evidence_refs,
        *[
            evidence_ref
            for disagreement in output.targeted_disagreements
            for evidence_ref in disagreement.evidence_refs
        ],
        *[
            evidence_ref
            for challenge in output.blocker_challenges
            for evidence_ref in challenge.evidence_refs
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


def _rebuttal_summary(output: Round2Rebuttal) -> str:
    if output.targeted_disagreements:
        return output.targeted_disagreements[0].rebuttal
    if output.unsupported_claims:
        return output.unsupported_claims[0].reason
    if output.blocker_challenges:
        return output.blocker_challenges[0].rationale
    if output.missing_info:
        return output.missing_info[0]
    return f"{output.agent_role.value} rebuttal."


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
    "RebuttalFocusPoint",
    "Round2RebuttalDrafter",
    "Round2RebuttalModel",
    "Round2RebuttalRequest",
    "Round2RebuttalValidationError",
    "build_round_2_rebuttal_handler",
    "build_round_2_rebuttal_request",
    "round_2_rebuttal_result_from_agent_output",
    "validate_round_2_rebuttal_output",
]
