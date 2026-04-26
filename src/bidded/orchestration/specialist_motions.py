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
from bidded.orchestration.evidence_refs import coerce_evidence_refs
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


def _coerce_refs_list(
    refs: Any,
    board: Sequence[EvidenceItemState],
) -> list[dict[str, Any]]:
    """Normalize LLM-produced ``evidence_refs`` via the shared canonicalizer.

    Drops non-dict items, fills missing evidence_id from evidence_key (and
    vice versa) where the match is unambiguous, and drops refs that still
    don't resolve to a board item. See
    :func:`bidded.orchestration.evidence_refs.coerce_evidence_refs`.
    """
    return coerce_evidence_refs(refs, board)


def _merge_title_detail_into_claim(item: dict[str, Any]) -> dict[str, Any]:
    out = dict(item)
    claim = (out.get("claim") or "").strip()
    if not claim:
        title = (out.get("title") or "").strip()
        detail = (out.get("detail") or "").strip()
        summary = (out.get("summary") or "").strip()
        if title and detail:
            claim = f"{title} — {detail}"
        elif title:
            claim = title
        elif detail:
            claim = detail
        elif summary:
            claim = summary
    if claim:
        out["claim"] = claim
    for key in ("title", "detail", "summary", "description", "name", "heading"):
        out.pop(key, None)
    return out


def _coerce_claim_list(
    items: Any,
    board: Sequence[EvidenceItemState],
) -> list[Any]:
    """Normalize each claim in a claim-array field.

    Merges title/detail aliases into the required ``claim`` field, canonicalizes
    each evidence_ref via the shared helper, and **drops claims whose refs list
    is empty after canonicalization**. The ``SupportedClaim`` schema requires
    ``evidence_refs`` with ``min_length=1``; leaving empty-ref claims in place
    would trip ``model_validate`` and abort the run.
    """
    if not isinstance(items, list):
        return items
    result: list[Any] = []
    for item in items:
        if not isinstance(item, dict):
            # Non-dict claims have no salvageable shape — drop silently
            # rather than passing hallucinations through to Pydantic.
            continue
        out = _merge_title_detail_into_claim(item)
        refs = out.get("evidence_refs")
        canonical_refs = _coerce_refs_list(refs, board) if refs is not None else []
        if not canonical_refs:
            # Schema requires at least one evidence_ref per claim. A claim
            # with zero resolvable refs is a hallucinated citation with
            # nothing behind it — drop the whole claim.
            continue
        out["evidence_refs"] = canonical_refs
        result.append(out)
    return result


def _normalize_agent_role(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip().lower().replace(" ", "_")
    return value


def _coerce_validation_error_item(item: Any) -> Any:
    if isinstance(item, str):
        return {"code": "llm_note", "message": item}
    return item


# Top-level keys the Round1Motion schema accepts (see agents/schemas.py). The
# coercer whitelists against this set so LLM-invented extras (e.g.
# "evaluation_summary", "reasoning") don't trip ``extra="forbid"`` on the
# strict schema.
_ROUND_1_MOTION_ALLOWED_KEYS = frozenset(
    {
        "agent_role",
        "vote",
        "confidence",
        "top_findings",
        "role_specific_risks",
        "formal_blockers",
        "potential_blockers",
        "assumptions",
        "missing_info",
        "potential_evidence_gaps",
        "recommended_actions",
        "validation_errors",
    }
)


def _normalize_requirement_type_in_place(item: Any) -> None:
    """If ``item`` is a dict with a ``requirement_type`` string, normalize it
    to the ``RequirementType`` enum value form. Unknown values are dropped
    (set to None) rather than raising.
    """
    if not isinstance(item, dict) or "requirement_type" not in item:
        return
    value = item["requirement_type"]
    if value is None or isinstance(value, RequirementType):
        return
    if not isinstance(value, str):
        item["requirement_type"] = None
        return
    normalized = value.strip().lower().replace(" ", "_").replace("-", "_")
    try:
        item["requirement_type"] = RequirementType(normalized).value
    except ValueError:
        # LLM invented a value not in the enum (e.g. "iso_certification").
        # Drop rather than fail — it's metadata, not load-bearing.
        item["requirement_type"] = None


def _coerce_formal_blockers_for_role(
    out: dict[str, Any],
    evidence_board: Sequence[EvidenceItemState],
) -> None:
    """Apply formal_blockers coercion in place.

    Pre-validate fixes for the two Pydantic checks that otherwise terminate
    the run:

    * Non-compliance roles may not populate ``formal_blockers``
      ([schemas.py] ``validate_specialist_motion``). Any content the LLM
      misfiled there is migrated to ``potential_blockers`` so the concern
      survives; ``formal_blockers`` is then cleared.
    * Compliance officer's ``formal_blockers`` whose evidence isn't
      classified as ``exclusion_ground`` / ``qualification_requirement``
      gate to no_bid automatically — too strong a penalty for an LLM
      misclassification. Those claims are demoted to ``potential_blockers``
      so the Judge still weighs them, but they don't force the verdict.
    """
    role = out.get("agent_role")
    formal = out.get("formal_blockers")
    if not isinstance(formal, list):
        return

    if role != AgentRole.COMPLIANCE_OFFICER.value:
        # Step B.3: non-compliance role — migrate every formal_blocker entry
        # into potential_blockers and clear the formal list.
        potential = out.get("potential_blockers")
        if not isinstance(potential, list):
            potential = []
        out["potential_blockers"] = [*potential, *formal]
        out["formal_blockers"] = []
        return

    # Step B.4: compliance role — demote formal_blockers whose evidence
    # doesn't qualify (requirement_type not in the formal-blocker set).
    kept_formal: list[Any] = []
    demoted: list[Any] = []
    for claim in formal:
        if not isinstance(claim, dict):
            demoted.append(claim)
            continue
        if _claim_dict_has_formal_blocker_evidence(claim, evidence_board):
            kept_formal.append(claim)
        else:
            demoted.append(claim)

    if demoted:
        potential = out.get("potential_blockers")
        if not isinstance(potential, list):
            potential = []
        out["potential_blockers"] = [*potential, *demoted]
    out["formal_blockers"] = kept_formal


def _claim_dict_has_formal_blocker_evidence(
    claim: dict[str, Any],
    evidence_board: Sequence[EvidenceItemState],
) -> bool:
    """Pre-Pydantic formal-blocker evidence check.

    Operates on raw dict claims (before Pydantic validation), looking up each
    evidence_ref against the board to check its ``requirement_type``. Returns
    True iff at least one of the claim's evidence refs points at a
    tender_document evidence item whose requirement_type is in
    :data:`_FORMAL_BLOCKER_REQUIREMENT_TYPES` (exclusion_ground or
    qualification_requirement).
    """
    refs = claim.get("evidence_refs")
    if not isinstance(refs, list):
        return False
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        key = ref.get("evidence_key")
        source_type = ref.get("source_type")
        evidence_id = ref.get("evidence_id")
        for item in evidence_board:
            if (
                item.evidence_key == key
                and item.source_type.value == source_type
                and item.evidence_id is not None
                and str(item.evidence_id) == str(evidence_id)
                and _is_formal_blocker_evidence(item)
            ):
                return True
    return False


def _coerce_round1_motion_mapping(
    raw: Mapping[str, Any],
    evidence_board: Sequence[EvidenceItemState],
) -> dict[str, Any]:
    """Heal LLM-drift shape issues before strict Pydantic validation.

    The four checks below run *before* ``Round1Motion.model_validate`` so that
    any Pydantic ``@model_validator`` — which otherwise fires inside
    ``model_validate`` and aborts the run with an un-coerceable error — sees
    already-healed data.

    1. Normalize ``agent_role`` case/whitespace.
    2. Whitelist top-level keys so LLM-invented extras don't trip
       ``extra="forbid"`` on the strict schema.
    3. Canonicalize every claim's evidence_refs via the shared helper (which
       drops refs that can't be resolved to a board item, and drops claims
       whose refs become empty).
    4. Clear ``formal_blockers`` for non-compliance roles (preserving content
       under ``potential_blockers``); demote compliance officer's
       formal_blockers whose evidence isn't exclusion_ground /
       qualification_requirement.
    5. Normalize ``requirement_type`` strings to the enum form; drop unknowns.
    """
    out = dict(raw)

    # Step 1: normalize role string so the whitelist and subsequent checks
    # see the canonical enum-value form.
    if "agent_role" in out:
        out["agent_role"] = _normalize_agent_role(out["agent_role"])

    # Step 2: whitelist top-level keys. Pydantic's ``extra="forbid"`` will
    # otherwise reject any LLM-invented extra (e.g. "evaluation_summary")
    # without the coercer getting a chance to run.
    for extra_key in list(out.keys()):
        if extra_key not in _ROUND_1_MOTION_ALLOWED_KEYS:
            out.pop(extra_key, None)

    # Step 3: canonicalize evidence_refs on every claim array, and drop
    # title/detail aliases so SupportedClaim's strict schema accepts the
    # result.
    for field in (
        "top_findings",
        "role_specific_risks",
        "formal_blockers",
        "potential_blockers",
    ):
        val = out.get(field)
        if isinstance(val, list):
            out[field] = _coerce_claim_list(val, evidence_board)

    # Step 4: fix formal_blockers *before* Pydantic validates. Must run after
    # step 3 so evidence_refs are canonicalized (allowing _claim_dict_has_
    # formal_blocker_evidence to match against the board).
    _coerce_formal_blockers_for_role(out, evidence_board)

    # Step 5: normalize requirement_type strings anywhere a claim or finding
    # carries one.
    for field in (
        "top_findings",
        "role_specific_risks",
        "formal_blockers",
        "potential_blockers",
    ):
        val = out.get(field)
        if isinstance(val, list):
            for item in val:
                _normalize_requirement_type_in_place(item)

    validation_errors = out.get("validation_errors")
    if isinstance(validation_errors, list):
        out["validation_errors"] = [
            _coerce_validation_error_item(e) for e in validation_errors
        ]
    return out


def validate_round_1_motion_output(
    raw_output: Round1Motion | Mapping[str, Any],
    *,
    evidence_board: Sequence[EvidenceItemState],
    expected_role: SpecialistRole,
) -> Round1Motion:
    """Validate strict motion schema and evidence refs against the board."""

    try:
        coerced = (
            raw_output
            if isinstance(raw_output, Round1Motion)
            else _coerce_round1_motion_mapping(raw_output, evidence_board)
        )
        output = Round1Motion.model_validate(coerced)
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

    # Defensible coercion: drop claims whose evidence refs do not resolve
    # against the board. The canonicalizer already tried every field-swap the
    # LLM commonly makes; anything still unresolvable is a hallucinated
    # citation with no audit trail. Dropping it lets the run proceed on the
    # claims that ARE grounded rather than failing the whole motion.
    output = _drop_unsupported_claims(output, evidence_board=evidence_board)

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
    # NOTE: the formal_blockers requirement_type check and non-compliance
    # clearing now happen pre-validate inside `_coerce_round1_motion_mapping`.
    # By the time we reach here, formal_blockers contains only entries whose
    # evidence is exclusion_ground / qualification_requirement AND the agent
    # is compliance_officer — so the historical `_coerce_invalid_formal_blockers`
    # call that used to live here is a no-op and has been removed.
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


def _drop_unsupported_claims(
    output: Round1Motion,
    *,
    evidence_board: Sequence[EvidenceItemState],
) -> Round1Motion:
    """Drop claims whose evidence refs cannot be resolved against the board,
    and drop evidence refs within kept claims that don't resolve. A claim
    with zero resolvable refs is removed entirely (the schema requires at
    least one ref per claim). This tolerates LLM citation drift without
    crashing the run.
    """
    changed = False
    updates: dict[str, list[Any]] = {}
    for field_name in (
        "top_findings",
        "role_specific_risks",
        "formal_blockers",
        "potential_blockers",
    ):
        original_claims: Sequence[Any] = getattr(output, field_name)
        kept_claims: list[Any] = []
        for claim in original_claims:
            resolved_refs = [
                ref
                for ref in claim.evidence_refs
                if _matching_evidence_item(ref, evidence_board) is not None
            ]
            if not resolved_refs:
                changed = True
                continue
            if len(resolved_refs) != len(claim.evidence_refs):
                changed = True
                kept_claims.append(
                    claim.model_copy(update={"evidence_refs": resolved_refs})
                )
            else:
                kept_claims.append(claim)
        updates[field_name] = kept_claims

    if not changed:
        return output
    return output.model_copy(update=updates)


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
