from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, ValidationError

from bidded.agents.schemas import (
    EvidenceReference,
    EvidenceScoutOutput,
    ScoutCategory,
)
from bidded.orchestration.contract_clause_audit import (
    ContractClauseCoverageWarning,
    audit_contract_clause_coverage,
)
from bidded.orchestration.evidence_recall import (
    EvidenceRecallWarning,
    audit_evidence_recall,
)
from bidded.orchestration.evidence_refs import coerce_evidence_refs
from bidded.orchestration.graph import GraphRouteNode, InvalidGraphOutput, ScoutHandler
from bidded.orchestration.state import (
    BidRunState,
    DocumentChunkState,
    EvidenceItemState,
    EvidenceRef,
    EvidenceSourceType,
    ScoutFindingState,
    ScoutOutputState,
)
from bidded.requirements import RequirementType
from bidded.retrieval import RetrievedDocumentChunk, rank_document_chunk_rows

SIX_PACK_SCOUT_CATEGORIES: tuple[str, ...] = tuple(
    category.value for category in ScoutCategory
)

_SCOUT_CATEGORY_QUERIES: dict[str, str] = {
    ScoutCategory.DEADLINE.value: (
        "deadline due submitted submission closing date time tender response"
    ),
    ScoutCategory.SHALL_REQUIREMENT.value: (
        "shall must mandatory required requirement certification security service"
    ),
    ScoutCategory.QUALIFICATION_CRITERION.value: (
        "qualification bidder bidders eligibility references experience financial"
    ),
    ScoutCategory.EVALUATION_CRITERION.value: (
        "evaluation award criteria scoring quality price weight points"
    ),
    ScoutCategory.CONTRACT_RISK.value: (
        "contract risk liability penalty penalties damages termination delay milestone"
    ),
    ScoutCategory.REQUIRED_SUBMISSION_DOCUMENT.value: (
        "submission document documents include signed form appendix attachment "
        "agreement"
    ),
}


class EvidenceScoutValidationError(ValueError):
    """Raised when mocked or real Evidence Scout output is not evidence-backed."""

    def __init__(self, message: str, *, field_path: str | None = None) -> None:
        super().__init__(message)
        self.field_path = field_path


class EvidenceScoutRetrievedChunk(BaseModel):
    """Tender chunk selected for one Evidence Scout category."""

    model_config = ConfigDict(extra="forbid")

    category: str = Field(min_length=1)
    chunk_id: UUID
    document_id: UUID
    chunk_index: NonNegativeInt
    page_start: int = Field(gt=0)
    page_end: int = Field(gt=0)
    text: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    retrieval_score: float = Field(ge=0)


class EvidenceScoutRequest(BaseModel):
    """Evidence-locked input passed to the Evidence Scout model adapter."""

    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    company_id: UUID
    tender_id: UUID
    document_ids: tuple[UUID, ...]
    categories: tuple[str, ...]
    retrieved_chunks: tuple[EvidenceScoutRetrievedChunk, ...]
    evidence_board: tuple[EvidenceItemState, ...]
    evidence_recall_warnings: tuple[EvidenceRecallWarning, ...] = ()
    contract_clause_audit_warnings: tuple[ContractClauseCoverageWarning, ...] = ()


class EvidenceScoutModel(Protocol):
    """Small adapter surface for Claude or deterministic tests."""

    def extract(
        self,
        request: EvidenceScoutRequest,
    ) -> EvidenceScoutOutput | Mapping[str, Any]: ...


EvidenceScoutExtractor = (
    EvidenceScoutModel
    | Callable[[EvidenceScoutRequest], EvidenceScoutOutput | Mapping[str, Any]]
)


def build_evidence_scout_handler(
    model: EvidenceScoutExtractor,
    *,
    top_k_per_category: int = 2,
) -> ScoutHandler:
    """Build a graph handler from a Claude-like Evidence Scout adapter."""

    def handler(state: BidRunState) -> ScoutOutputState | InvalidGraphOutput:
        try:
            request = build_evidence_scout_request(
                state,
                top_k_per_category=top_k_per_category,
            )
            raw_output = _extract_scout_output(model, request)
            validated = validate_evidence_scout_output(
                raw_output,
                evidence_board=state.evidence_board,
            )
            return scout_output_state_from_agent_output(validated)
        except EvidenceScoutValidationError as exc:
            return InvalidGraphOutput(
                source=GraphRouteNode.EVIDENCE_SCOUT,
                message=str(exc),
                field_path=exc.field_path,
            )

    return handler


def build_evidence_scout_request(
    state: BidRunState,
    *,
    top_k_per_category: int = 2,
) -> EvidenceScoutRequest:
    """Select bounded tender chunks for the six Evidence Scout categories."""

    if top_k_per_category <= 0:
        raise EvidenceScoutValidationError("top_k_per_category must be greater than 0")

    return EvidenceScoutRequest(
        run_id=state.run_id,
        company_id=state.company_id,
        tender_id=state.tender_id,
        document_ids=tuple(state.document_ids),
        categories=SIX_PACK_SCOUT_CATEGORIES,
        retrieved_chunks=tuple(
            retrieved_chunk
            for category in SIX_PACK_SCOUT_CATEGORIES
            for retrieved_chunk in _retrieve_category_chunks(
                state.chunks,
                category=category,
                top_k=top_k_per_category,
            )
        ),
        evidence_board=tuple(state.evidence_board),
        evidence_recall_warnings=audit_evidence_recall(
            chunks=state.chunks,
            evidence_board=state.evidence_board,
        ),
        contract_clause_audit_warnings=audit_contract_clause_coverage(
            chunks=state.chunks,
            evidence_board=state.evidence_board,
        ),
    )


def _merge_title_detail_into_claim(item: dict[str, Any]) -> dict[str, Any]:
    """LLMs often emit title/detail instead of the schema's single ``claim`` field."""
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
    for key in (
        "title",
        "detail",
        "summary",
        "description",
        "name",
        "heading",
    ):
        out.pop(key, None)
    return out


def _coerce_refs_list(
    refs: Any,
    board: Sequence[EvidenceItemState],
) -> list[dict[str, Any]]:
    """Normalize LLM-produced ``evidence_refs`` via the shared canonicalizer.

    See :func:`bidded.orchestration.evidence_refs.coerce_evidence_refs`.
    """
    return coerce_evidence_refs(refs, board)


_FINDING_ALLOWED_KEYS = frozenset(
    {"category", "claim", "evidence_refs", "requirement_type"}
)


def _normalize_requirement_type(value: Any) -> Any:
    """Coerce a free-text ``requirement_type`` string to the enum value form.

    The LLM sometimes emits e.g. ``"Qualification Requirement"`` or
    ``"shall-requirement"`` rather than the canonical ``"shall_requirement"``.
    Unknown values are dropped (set to None) rather than raising — it's
    metadata, not load-bearing.
    """
    if value is None or isinstance(value, RequirementType):
        return value
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower().replace(" ", "_").replace("-", "_")
    try:
        return RequirementType(normalized).value
    except ValueError:
        return None


def _coerce_finding_item(
    item: dict[str, Any],
    board: Sequence[EvidenceItemState],
) -> dict[str, Any] | None:
    """Normalize one scout finding dict.

    Returns ``None`` when the finding cannot be made schema-valid — specifically
    when after canonicalization there are zero resolvable evidence_refs (the
    schema requires ``min_length=1``). The caller drops ``None`` results so the
    finding doesn't survive into ``model_validate``.
    """
    out = _merge_title_detail_into_claim(item)
    refs = out.get("evidence_refs")
    out["evidence_refs"] = _coerce_refs_list(refs, board) if refs is not None else []
    if not out["evidence_refs"]:
        # A finding with zero resolvable refs is a hallucinated citation with
        # nothing behind it. Drop the whole finding.
        return None
    if "requirement_type" in out:
        out["requirement_type"] = _normalize_requirement_type(out["requirement_type"])
    # Whitelist: drop any extra keys Claude invents (relevance_note, etc.)
    return {k: v for k, v in out.items() if k in _FINDING_ALLOWED_KEYS}


def _coerce_blocker_item(item: Any) -> str:
    """Scout potential_blockers are list[str] — extract claim text from any shape."""
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        out = _merge_title_detail_into_claim(item)
        claim = (out.get("claim") or "").strip()
        return claim or str(item)
    return str(item)


def _coerce_validation_error_item(item: Any) -> Any:
    if isinstance(item, str):
        return {"code": "llm_note", "message": item}
    return item


def _normalize_agent_role(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip().lower().replace(" ", "_")
    return value


_EVIDENCE_SCOUT_ALLOWED_KEYS = frozenset(
    {
        "agent_role",
        "findings",
        "missing_info",
        "potential_blockers",
        "validation_errors",
    }
)

# Keys that indicate a semantic role violation (not drift) and must NOT be
# silently stripped by the whitelist. ``verdict`` / ``vote`` / ``recommendation``
# would mean the scout started issuing bid recommendations, which the PRD
# explicitly prohibits ("Evidence Scout extracts facts but does not recommend
# bid/no-bid"). These are kept in the payload so Pydantic's ``extra="forbid"``
# rejects them loudly rather than letting the scout overreach go unnoticed.
_EVIDENCE_SCOUT_FORBIDDEN_SEMANTIC_KEYS = frozenset(
    {"verdict", "vote", "recommendation"}
)


def _coerce_evidence_scout_mapping(
    raw: Mapping[str, Any],
    evidence_board: Sequence[EvidenceItemState],
) -> dict[str, Any]:
    """Heal LLM-drift shape issues before strict Pydantic validation.

    Matches the Round 1 / Round 2 coercer: whitelists top-level keys so
    extras don't trip ``extra="forbid"``, canonicalizes each finding's
    evidence_refs via the shared helper, drops findings that end up with
    zero resolvable refs (schema requires ``min_length=1``), and normalizes
    ``agent_role``.
    """
    out = dict(raw)

    # Whitelist top-level keys. Keys in the "forbidden semantic" set (verdict,
    # vote, recommendation) are preserved so Pydantic's ``extra="forbid"``
    # rejects them — a scout producing those would be a role-boundary
    # violation, not a typo-grade drift we want to silently heal.
    for extra_key in list(out.keys()):
        if extra_key in _EVIDENCE_SCOUT_FORBIDDEN_SEMANTIC_KEYS:
            continue
        if extra_key not in _EVIDENCE_SCOUT_ALLOWED_KEYS:
            out.pop(extra_key, None)

    # Normalize agent_role: 'Evidence Scout' → 'evidence_scout'
    if "agent_role" in out:
        out["agent_role"] = _normalize_agent_role(out["agent_role"])

    findings = out.get("findings")
    if isinstance(findings, list):
        coerced_findings: list[dict[str, Any]] = []
        for f in findings:
            if not isinstance(f, dict):
                continue
            coerced = _coerce_finding_item(f, evidence_board)
            if coerced is None:
                continue
            coerced_findings.append(coerced)
        out["findings"] = coerced_findings

    blockers = out.get("potential_blockers")
    if isinstance(blockers, list):
        out["potential_blockers"] = [_coerce_blocker_item(b) for b in blockers]

    validation_errors = out.get("validation_errors")
    if isinstance(validation_errors, list):
        out["validation_errors"] = [
            _coerce_validation_error_item(e) for e in validation_errors
        ]

    return out


def validate_evidence_scout_output(
    raw_output: EvidenceScoutOutput | Mapping[str, Any],
    *,
    evidence_board: Sequence[EvidenceItemState],
) -> EvidenceScoutOutput:
    """Validate strict scout schema and evidence refs against the board.

    Defensible coercion: findings whose evidence refs do not resolve against
    the board are dropped rather than failing the whole run. The canonicalizer
    already tries every field-swap the LLM commonly makes; if a ref is *still*
    unresolvable, it is a hallucinated citation with no audit trail and cannot
    be trusted. Dropping it lets the swarm continue with the findings it *can*
    substantiate — the scout's remaining findings, plus potential_blockers /
    missing_info, are still enough material for Round 1 specialists.
    """

    try:
        if isinstance(raw_output, EvidenceScoutOutput):
            output = raw_output
        else:
            output = EvidenceScoutOutput.model_validate(
                _coerce_evidence_scout_mapping(raw_output, evidence_board)
            )
    except ValidationError as exc:
        raise EvidenceScoutValidationError(
            str(exc),
            field_path=_field_path_from_validation_error(exc),
        ) from exc

    output = _drop_unresolvable_refs(output, evidence_board=evidence_board)

    for finding_index, finding in enumerate(output.findings):
        _validate_evidence_refs(
            finding.evidence_refs,
            evidence_board=evidence_board,
            field_path=f"findings[{finding_index}].evidence_refs",
        )

    return output


def _drop_unresolvable_refs(
    output: EvidenceScoutOutput,
    *,
    evidence_board: Sequence[EvidenceItemState],
) -> EvidenceScoutOutput:
    """Remove evidence_refs that do not match any board item; drop findings
    left with zero refs (the scout schema requires at least one per finding).
    """
    kept_findings: list[Any] = []
    for finding in output.findings:
        resolved_refs = [
            ref
            for ref in finding.evidence_refs
            if _matching_evidence_item(ref, evidence_board) is not None
        ]
        if not resolved_refs:
            # Scout finding without any resolvable citation — drop it. The
            # concern may already be surfaced via potential_blockers /
            # missing_info; if not, Round 1 specialists will still have the
            # full evidence_board to reason from.
            continue
        kept_findings.append(
            finding.model_copy(update={"evidence_refs": resolved_refs})
        )

    if len(kept_findings) == len(output.findings) and all(
        len(a.evidence_refs) == len(b.evidence_refs)
        for a, b in zip(kept_findings, output.findings, strict=False)
    ):
        return output

    return output.model_copy(update={"findings": kept_findings})


def scout_output_state_from_agent_output(
    output: EvidenceScoutOutput,
) -> ScoutOutputState:
    """Convert the strict agent artifact into shared graph state."""

    return ScoutOutputState(
        findings=[
            ScoutFindingState(
                category=finding.category.value,
                claim=finding.claim,
                evidence_refs=[
                    _state_ref_from_agent_ref(evidence_ref)
                    for evidence_ref in finding.evidence_refs
                ],
                requirement_type=(
                    finding.requirement_type.value
                    if finding.requirement_type is not None
                    else None
                ),
            )
            for finding in output.findings
        ],
        missing_info=list(output.missing_info),
        potential_blockers=list(output.potential_blockers),
    )


def _retrieve_category_chunks(
    chunks: Sequence[DocumentChunkState],
    *,
    category: str,
    top_k: int,
) -> tuple[EvidenceScoutRetrievedChunk, ...]:
    query = _SCOUT_CATEGORY_QUERIES[category]
    ranked_chunks = rank_document_chunk_rows(
        [_row_from_state_chunk(chunk) for chunk in chunks],
        query=query,
        top_k=top_k,
    )
    return tuple(
        _scout_chunk_from_retrieved(category, retrieved_chunk)
        for retrieved_chunk in ranked_chunks
    )


def _extract_scout_output(
    model: EvidenceScoutExtractor,
    request: EvidenceScoutRequest,
) -> EvidenceScoutOutput | Mapping[str, Any]:
    if hasattr(model, "extract"):
        return model.extract(request)
    return model(request)


def _validate_evidence_refs(
    evidence_refs: Sequence[EvidenceReference],
    *,
    evidence_board: Sequence[EvidenceItemState],
    field_path: str,
) -> None:
    for evidence_ref in evidence_refs:
        if _matching_evidence_item(evidence_ref, evidence_board) is None:
            raise EvidenceScoutValidationError(
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


def _state_ref_from_agent_ref(evidence_ref: EvidenceReference) -> EvidenceRef:
    return EvidenceRef(
        evidence_key=evidence_ref.evidence_key,
        source_type=EvidenceSourceType(evidence_ref.source_type.value),
        evidence_id=evidence_ref.evidence_id,
    )


def _row_from_state_chunk(chunk: DocumentChunkState) -> dict[str, Any]:
    return {
        "id": str(chunk.chunk_id),
        "document_id": str(chunk.document_id),
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "chunk_index": chunk.chunk_index,
        "text": chunk.text,
        "metadata": dict(chunk.metadata),
        "embedding": None,
    }


def _scout_chunk_from_retrieved(
    category: str,
    chunk: RetrievedDocumentChunk,
) -> EvidenceScoutRetrievedChunk:
    retrieval = chunk.metadata.get("retrieval", {})
    retrieval_score = (
        float(retrieval.get("final_score", 0))
        if isinstance(retrieval, Mapping)
        else 0.0
    )
    return EvidenceScoutRetrievedChunk(
        category=category,
        chunk_id=UUID(chunk.chunk_id),
        document_id=chunk.document_id,
        chunk_index=chunk.chunk_index,
        page_start=chunk.page_start,
        page_end=chunk.page_end,
        text=chunk.text,
        metadata=dict(chunk.metadata),
        retrieval_score=retrieval_score,
    )


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
    "EvidenceScoutModel",
    "EvidenceScoutRequest",
    "EvidenceScoutRetrievedChunk",
    "EvidenceScoutValidationError",
    "SIX_PACK_SCOUT_CATEGORIES",
    "build_evidence_scout_handler",
    "build_evidence_scout_request",
    "scout_output_state_from_agent_output",
    "validate_evidence_scout_output",
]
