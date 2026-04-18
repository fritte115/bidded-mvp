from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, ValidationError

from bidded.agents.schemas import (
    EvidenceReference,
    EvidenceScoutOutput,
    ScoutCategory,
)
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


def _resolve_ref_against_board(
    ref_dict: dict[str, Any],
    board: Sequence[EvidenceItemState],
) -> dict[str, Any]:
    """Fill in evidence_id from board when Claude omits or mismatches it."""
    out = dict(ref_dict)
    key = str(out.get("evidence_key") or "")
    source_type = str(out.get("source_type") or "")
    ev_id_raw = out.get("evidence_id")
    needs_resolve = ev_id_raw is None or str(ev_id_raw).strip() in ("", "null", "None")
    if needs_resolve:
        item = next(
            (
                i
                for i in board
                if i.evidence_key == key and i.source_type.value == source_type
            ),
            None,
        )
        if item is not None and item.evidence_id is not None:
            out["evidence_id"] = str(item.evidence_id)
    return out


def _coerce_refs_list(
    refs: Any,
    board: Sequence[EvidenceItemState],
) -> list[Any]:
    if not isinstance(refs, list):
        return refs
    return [
        _resolve_ref_against_board(r, board) if isinstance(r, dict) else r
        for r in refs
    ]


def _coerce_claim_item(
    item: dict[str, Any],
    board: Sequence[EvidenceItemState],
) -> dict[str, Any]:
    out = _merge_title_detail_into_claim(item)
    refs = out.get("evidence_refs")
    if refs is not None:
        out["evidence_refs"] = _coerce_refs_list(refs, board)
    return out


def _coerce_evidence_scout_mapping(
    raw: Mapping[str, Any],
    evidence_board: Sequence[EvidenceItemState],
) -> dict[str, Any]:
    """Normalize field aliases and resolve evidence_ids before Pydantic validation."""
    out = dict(raw)
    findings = out.get("findings")
    if isinstance(findings, list):
        out["findings"] = [
            _coerce_claim_item(f, evidence_board) if isinstance(f, dict) else f
            for f in findings
        ]
    blockers = out.get("potential_blockers")
    if isinstance(blockers, list):
        out["potential_blockers"] = [
            _coerce_claim_item(b, evidence_board) if isinstance(b, dict) else b
            for b in blockers
        ]
    return out


def validate_evidence_scout_output(
    raw_output: EvidenceScoutOutput | Mapping[str, Any],
    *,
    evidence_board: Sequence[EvidenceItemState],
) -> EvidenceScoutOutput:
    """Validate strict scout schema and evidence refs against the board."""

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

    for finding_index, finding in enumerate(output.findings):
        _validate_evidence_refs(
            finding.evidence_refs,
            evidence_board=evidence_board,
            field_path=f"findings[{finding_index}].evidence_refs",
        )

    for blocker_index, blocker in enumerate(output.potential_blockers):
        _validate_evidence_refs(
            blocker.evidence_refs,
            evidence_board=evidence_board,
            field_path=f"potential_blockers[{blocker_index}].evidence_refs",
        )

    return output


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
        potential_blockers=[blocker.claim for blocker in output.potential_blockers],
    )


def _retrieve_category_chunks(
    chunks: Sequence[DocumentChunkState],
    *,
    category: str,
    top_k: int,
) -> tuple[EvidenceScoutRetrievedChunk, ...]:
    query = _SCOUT_CATEGORY_QUERIES[category]
    query_terms = Counter(_tokens(query))
    scored_chunks = [
        (_keyword_score(query_terms, chunk.text), chunk) for chunk in chunks
    ]
    ranked_chunks = sorted(
        ((score, chunk) for score, chunk in scored_chunks if score > 0),
        key=lambda scored_chunk: (
            -scored_chunk[0],
            scored_chunk[1].chunk_index,
            str(scored_chunk[1].chunk_id),
        ),
    )
    return tuple(
        EvidenceScoutRetrievedChunk(
            category=category,
            chunk_id=chunk.chunk_id,
            document_id=chunk.document_id,
            chunk_index=chunk.chunk_index,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            text=chunk.text,
            metadata=dict(chunk.metadata),
            retrieval_score=score,
        )
        for score, chunk in ranked_chunks[:top_k]
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


def _keyword_score(query_terms: Counter[str], text: str) -> float:
    text_terms = Counter(_tokens(text))
    matched_terms = sum(text_terms[term] for term in set(query_terms))
    if matched_terms == 0:
        return 0.0
    coverage = len(set(query_terms) & set(text_terms)) / len(query_terms)
    density = matched_terms / max(1, sum(text_terms.values()))
    return round(matched_terms + coverage + density, 6)


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


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
