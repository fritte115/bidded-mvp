from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from bidded.orchestration.pending_run import DEMO_TENANT_KEY
from bidded.orchestration.state import (
    BidRunState,
    EvidenceItemState,
    EvidenceRef,
    EvidenceSourceType,
)
from bidded.requirements import RequirementType


class FitGapError(RuntimeError):
    """Raised when requirement fit-gap rows cannot be built or loaded."""


class FitGapMatchStatus(StrEnum):
    MATCHED = "matched"
    PARTIAL_MATCH = "partial_match"
    MISSING_COMPANY_EVIDENCE = "missing_company_evidence"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    STALE_EVIDENCE = "stale_evidence"
    NOT_APPLICABLE = "not_applicable"
    NEEDS_HUMAN_REVIEW = "needs_human_review"


RiskLevel = Literal["low", "medium", "high"]


class RequirementFitGapItem(BaseModel):
    """One per-run tender requirement matched against company proof."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_run_id: UUID
    tender_id: UUID
    company_id: UUID
    requirement_key: str = Field(min_length=1)
    requirement: str = Field(min_length=1)
    requirement_type: RequirementType
    match_status: FitGapMatchStatus
    risk_level: RiskLevel
    confidence: float = Field(ge=0, le=1)
    assessment: str = Field(min_length=1)
    tender_evidence_refs: tuple[EvidenceRef, ...] = Field(min_length=1)
    company_evidence_refs: tuple[EvidenceRef, ...] = ()
    tender_evidence_ids: tuple[UUID, ...] = Field(min_length=1)
    company_evidence_ids: tuple[UUID, ...] = ()
    missing_info: tuple[str, ...] = ()
    recommended_actions: tuple[str, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_row_payload(self, *, tenant_key: str = DEMO_TENANT_KEY) -> dict[str, Any]:
        return {
            "tenant_key": tenant_key,
            "agent_run_id": str(self.agent_run_id),
            "tender_id": str(self.tender_id),
            "company_id": str(self.company_id),
            "requirement_key": self.requirement_key,
            "requirement": self.requirement,
            "requirement_type": self.requirement_type.value,
            "match_status": self.match_status.value,
            "risk_level": self.risk_level,
            "confidence": self.confidence,
            "assessment": self.assessment,
            "tender_evidence_refs": [
                ref.model_dump(mode="json") for ref in self.tender_evidence_refs
            ],
            "company_evidence_refs": [
                ref.model_dump(mode="json") for ref in self.company_evidence_refs
            ],
            "tender_evidence_ids": [
                str(evidence_id) for evidence_id in self.tender_evidence_ids
            ],
            "company_evidence_ids": [
                str(evidence_id) for evidence_id in self.company_evidence_ids
            ],
            "missing_info": list(self.missing_info),
            "recommended_actions": list(self.recommended_actions),
            "metadata": self.metadata,
        }


class SupabaseFitGapQuery(Protocol):
    def select(self, columns: str) -> SupabaseFitGapQuery: ...

    def eq(self, column: str, value: object) -> SupabaseFitGapQuery: ...

    def insert(
        self,
        payload: list[dict[str, Any]],
    ) -> SupabaseFitGapQuery: ...

    def execute(self) -> Any: ...


class SupabaseFitGapClient(Protocol):
    def table(self, table_name: str) -> SupabaseFitGapQuery: ...


def ensure_requirement_fit_gaps_for_run(
    client: SupabaseFitGapClient,
    state: BidRunState,
    *,
    tenant_key: str = DEMO_TENANT_KEY,
) -> tuple[RequirementFitGapItem, ...]:
    """Return the per-run fit-gap snapshot, inserting it if missing."""

    existing = list_requirement_fit_gaps_for_run(
        client,
        run_id=state.run_id,
        tenant_key=tenant_key,
    )
    if existing:
        return existing

    board = build_requirement_fit_gap_board(state)
    if not board:
        return ()

    payload = [item.to_row_payload(tenant_key=tenant_key) for item in board]
    rows = _response_rows(
        client.table("requirement_fit_gaps").insert(payload).execute()
    )
    if rows:
        return tuple(_item_from_row(row) for row in rows)
    return board


def list_requirement_fit_gaps_for_run(
    client: SupabaseFitGapClient,
    *,
    run_id: UUID | str,
    tenant_key: str = DEMO_TENANT_KEY,
) -> tuple[RequirementFitGapItem, ...]:
    normalized_run_id = _normalize_uuid(run_id, "run_id")
    rows = _response_rows(
        client.table("requirement_fit_gaps")
        .select("*")
        .eq("tenant_key", tenant_key)
        .eq("agent_run_id", str(normalized_run_id))
        .execute()
    )
    return tuple(
        _item_from_row(row)
        for row in sorted(rows, key=lambda row: str(row.get("requirement_key") or ""))
    )


def build_requirement_fit_gap_board(
    state: BidRunState,
) -> tuple[RequirementFitGapItem, ...]:
    tender_items = [
        item
        for item in state.evidence_board
        if item.source_type is EvidenceSourceType.TENDER_DOCUMENT
        and item.requirement_type is not None
    ]
    company_items = [
        item
        for item in state.evidence_board
        if item.source_type is EvidenceSourceType.COMPANY_PROFILE
    ]
    return tuple(
        _fit_gap_item_for_tender(
            state,
            tender_item=tender_item,
            company_items=company_items,
        )
        for tender_item in sorted(tender_items, key=_tender_sort_key)
    )


def fit_gap_items_from_state(
    state: BidRunState,
) -> tuple[RequirementFitGapItem, ...]:
    return tuple(
        RequirementFitGapItem.model_validate(item) for item in state.fit_gap_board
    )


def fit_gap_payload(
    items: Sequence[RequirementFitGapItem],
) -> list[dict[str, Any]]:
    return [
        {
            "requirement_key": item.requirement_key,
            "requirement": item.requirement,
            "requirement_type": item.requirement_type.value,
            "match_status": item.match_status.value,
            "risk_level": item.risk_level,
            "confidence": item.confidence,
            "assessment": item.assessment,
            "tender_evidence_refs": [
                ref.model_dump(mode="json") for ref in item.tender_evidence_refs
            ],
            "company_evidence_refs": [
                ref.model_dump(mode="json") for ref in item.company_evidence_refs
            ],
            "missing_info": list(item.missing_info),
            "recommended_actions": list(item.recommended_actions),
        }
        for item in items
    ]


def _fit_gap_item_for_tender(
    state: BidRunState,
    *,
    tender_item: EvidenceItemState,
    company_items: Sequence[EvidenceItemState],
) -> RequirementFitGapItem:
    candidates = _rank_company_candidates(tender_item, company_items)
    tender_refs = (_evidence_ref(tender_item),)
    tender_ids = _uuid_tuple(tender_item.evidence_id)
    requirement = tender_item.normalized_meaning or tender_item.excerpt

    if not candidates:
        return RequirementFitGapItem(
            agent_run_id=state.run_id,
            tender_id=state.tender_id,
            company_id=state.company_id,
            requirement_key=tender_item.evidence_key,
            requirement=requirement,
            requirement_type=tender_item.requirement_type
            or RequirementType.SHALL_REQUIREMENT,
            match_status=FitGapMatchStatus.MISSING_COMPANY_EVIDENCE,
            risk_level="high",
            confidence=0.58,
            assessment=(
                "No company_profile evidence was found for this tender requirement."
            ),
            tender_evidence_refs=tender_refs,
            tender_evidence_ids=tender_ids,
            missing_info=(
                "No company evidence currently supports this tender requirement.",
            ),
            recommended_actions=(
                f"Upload or identify company proof for: {_short(requirement)}",
            ),
            metadata=_metadata(tender_item, candidates=()),
        )

    selected = candidates[:3]
    company_refs = tuple(_evidence_ref(candidate.item) for candidate in selected)
    company_ids = tuple(
        evidence_id
        for candidate in selected
        if (evidence_id := candidate.item.evidence_id) is not None
    )
    status = _match_status(tender_item, selected)
    risk_level = _risk_level(status)
    confidence = _confidence(status, selected[0].score)
    missing_info, actions = _gap_actions(
        tender_item,
        status=status,
        requirement=requirement,
    )

    return RequirementFitGapItem(
        agent_run_id=state.run_id,
        tender_id=state.tender_id,
        company_id=state.company_id,
        requirement_key=tender_item.evidence_key,
        requirement=requirement,
        requirement_type=(
            tender_item.requirement_type or RequirementType.SHALL_REQUIREMENT
        ),
        match_status=status,
        risk_level=risk_level,
        confidence=confidence,
        assessment=_assessment(status, requirement=requirement, selected=selected),
        tender_evidence_refs=tender_refs,
        company_evidence_refs=company_refs,
        tender_evidence_ids=tender_ids,
        company_evidence_ids=company_ids,
        missing_info=missing_info,
        recommended_actions=actions,
        metadata=_metadata(tender_item, candidates=selected),
    )


class _Candidate(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    item: EvidenceItemState
    score: float
    token_overlap: tuple[str, ...]
    route_match: bool = False
    phrase_matches: tuple[str, ...] = ()


def _rank_company_candidates(
    tender_item: EvidenceItemState,
    company_items: Sequence[EvidenceItemState],
) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    query_terms = set(_tokens(_evidence_text(tender_item)))
    important_phrases = _important_phrases(_evidence_text(tender_item))
    for company_item in company_items:
        company_text = _evidence_text(company_item)
        company_terms = set(_tokens(company_text))
        overlap = tuple(sorted(query_terms & company_terms - _STOPWORDS))
        phrase_matches = tuple(
            phrase
            for phrase in important_phrases
            if phrase in _normalized(company_text)
        )
        route_match = _route_match(tender_item, company_item)
        score = _candidate_score(
            overlap=overlap,
            phrase_matches=phrase_matches,
            route_match=route_match,
        )
        if score <= 0:
            continue
        candidates.append(
            _Candidate(
                item=company_item,
                score=score,
                token_overlap=overlap,
                route_match=route_match,
                phrase_matches=phrase_matches,
            )
        )
    return sorted(
        candidates,
        key=lambda candidate: (
            -candidate.score,
            candidate.item.field_path or "",
            candidate.item.evidence_key,
        ),
    )


def _match_status(
    tender_item: EvidenceItemState,
    candidates: Sequence[_Candidate],
) -> FitGapMatchStatus:
    if not candidates:
        return FitGapMatchStatus.MISSING_COMPANY_EVIDENCE
    if any(_has_conflict_language(candidate.item) for candidate in candidates):
        return FitGapMatchStatus.CONFLICTING_EVIDENCE
    if any(_is_stale(candidate.item) for candidate in candidates):
        return FitGapMatchStatus.STALE_EVIDENCE
    if _needs_counted_proof(tender_item) and len(candidates) < _required_count(
        tender_item
    ):
        return FitGapMatchStatus.PARTIAL_MATCH
    if candidates[0].score >= 0.72:
        return FitGapMatchStatus.MATCHED
    return FitGapMatchStatus.PARTIAL_MATCH


def _risk_level(status: FitGapMatchStatus) -> RiskLevel:
    if status is FitGapMatchStatus.MATCHED:
        return "low"
    if status in {
        FitGapMatchStatus.PARTIAL_MATCH,
        FitGapMatchStatus.STALE_EVIDENCE,
        FitGapMatchStatus.NOT_APPLICABLE,
    }:
        return "medium"
    return "high"


def _confidence(status: FitGapMatchStatus, score: float) -> float:
    base = {
        FitGapMatchStatus.MATCHED: 0.86,
        FitGapMatchStatus.PARTIAL_MATCH: 0.68,
        FitGapMatchStatus.MISSING_COMPANY_EVIDENCE: 0.58,
        FitGapMatchStatus.CONFLICTING_EVIDENCE: 0.74,
        FitGapMatchStatus.STALE_EVIDENCE: 0.70,
        FitGapMatchStatus.NOT_APPLICABLE: 0.62,
        FitGapMatchStatus.NEEDS_HUMAN_REVIEW: 0.50,
    }[status]
    return round(max(0.0, min(1.0, base + min(0.08, score / 10))), 2)


def _assessment(
    status: FitGapMatchStatus,
    *,
    requirement: str,
    selected: Sequence[_Candidate],
) -> str:
    if status is FitGapMatchStatus.MATCHED:
        return (
            "Company evidence appears to match the tender requirement: "
            f"{_short(requirement)}"
        )
    if status is FitGapMatchStatus.PARTIAL_MATCH:
        return (
            "Company evidence partially supports the tender requirement, but "
            "additional proof is needed before treating it as covered."
        )
    if status is FitGapMatchStatus.CONFLICTING_EVIDENCE:
        return "Company evidence contains negative or conflicting language."
    if status is FitGapMatchStatus.STALE_EVIDENCE:
        return "Company evidence appears stale or expired and needs refresh."
    if selected:
        return "Company evidence needs human review before the requirement is covered."
    return "No company evidence was found for this tender requirement."


def _gap_actions(
    tender_item: EvidenceItemState,
    *,
    status: FitGapMatchStatus,
    requirement: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if status is FitGapMatchStatus.MATCHED:
        return (), ()
    if status is FitGapMatchStatus.MISSING_COMPANY_EVIDENCE:
        return (
            ("No company evidence currently supports this tender requirement.",),
            (f"Upload or identify company proof for: {_short(requirement)}",),
        )
    if status is FitGapMatchStatus.CONFLICTING_EVIDENCE:
        return (
            ("Company evidence conflicts with the tender requirement.",),
            ("Resolve the conflicting company proof before bid approval.",),
        )
    if status is FitGapMatchStatus.STALE_EVIDENCE:
        return (
            ("Company evidence appears stale or expired.",),
            ("Refresh the company evidence and attach current proof.",),
        )
    return (
        ("Additional proof is needed to fully satisfy this requirement.",),
        (
            "Attach supporting company evidence or confirm the partial match with "
            "the bid owner.",
        ),
    )


def _route_match(
    tender_item: EvidenceItemState,
    company_item: EvidenceItemState,
) -> bool:
    categories = _ROUTE_CATEGORIES.get(tender_item.requirement_type or None, ())
    category_text = " ".join(
        [
            company_item.category,
            company_item.field_path or "",
            str(company_item.metadata.get("fact_type") or ""),
        ]
    ).casefold()
    return any(category in category_text for category in categories)


def _candidate_score(
    *,
    overlap: Sequence[str],
    phrase_matches: Sequence[str],
    route_match: bool,
) -> float:
    score = 0.0
    if route_match:
        score += 0.35
    if phrase_matches:
        score += min(0.55, 0.30 + len(phrase_matches) * 0.12)
    if overlap:
        score += min(0.40, len(overlap) * 0.08)
    return round(min(1.0, score), 6)


def _needs_counted_proof(tender_item: EvidenceItemState) -> bool:
    text = _normalized(_evidence_text(tender_item))
    return any(term in text for term in ("references", "referens", "cv", "profiles"))


def _required_count(tender_item: EvidenceItemState) -> int:
    text = _normalized(_evidence_text(tender_item))
    digits = [int(match) for match in re.findall(r"\b([2-9])\b", text)]
    words = {"two": 2, "three": 3, "four": 4, "five": 5, "tva": 2, "tre": 3}
    for word, count in words.items():
        if re.search(rf"\b{word}\b", text):
            digits.append(count)
    return max(digits or [1])


def _has_conflict_language(item: EvidenceItemState) -> bool:
    text = _normalized(_evidence_text(item))
    return any(
        phrase in text
        for phrase in (
            "not active",
            "expired",
            "revoked",
            "does not hold",
            "does not have",
            "missing",
            "saknar",
            "utgangen",
        )
    )


def _is_stale(item: EvidenceItemState) -> bool:
    text = _normalized(_evidence_text(item))
    valid_until = item.metadata.get("valid_until") or item.metadata.get("expires_at")
    if valid_until is not None:
        try:
            return int(str(valid_until)[:4]) < 2026
        except ValueError:
            return False
    if "current" in text or "active" in text:
        return False
    years = [int(year) for year in re.findall(r"\b(20[0-2][0-9])\b", text)]
    return bool(years and max(years) < 2025)


def _important_phrases(text: str) -> tuple[str, ...]:
    normalized = _normalized(text)
    phrases = []
    for pattern in (
        r"iso\s*27001",
        r"iso\s*9001",
        r"iso\s*14001",
        r"gdpr",
        r"\bdpa\b",
        r"security cleared",
        r"public sector",
        r"financial standing",
        r"credit report",
        r"insurance",
        r"references?",
        r"\bcv\b",
    ):
        if match := re.search(pattern, normalized):
            phrases.append(match.group(0))
    return tuple(dict.fromkeys(phrases))


def _evidence_text(item: EvidenceItemState) -> str:
    metadata_values = " ".join(
        str(value)
        for value in item.metadata.values()
        if isinstance(value, str | int | float)
    )
    return " ".join(
        [
            item.excerpt,
            item.normalized_meaning,
            item.category,
            item.field_path or "",
            metadata_values,
        ]
    )


def _metadata(
    tender_item: EvidenceItemState,
    *,
    candidates: Sequence[_Candidate],
) -> dict[str, Any]:
    return {
        "source": "deterministic_fit_gap_v1",
        "tender_evidence_key": tender_item.evidence_key,
        "candidate_scores": [
            {
                "evidence_key": candidate.item.evidence_key,
                "score": candidate.score,
                "token_overlap": list(candidate.token_overlap),
                "route_match": candidate.route_match,
                "phrase_matches": list(candidate.phrase_matches),
            }
            for candidate in candidates
        ],
    }


def _item_from_row(row: Mapping[str, Any]) -> RequirementFitGapItem:
    return RequirementFitGapItem(
        agent_run_id=_normalize_uuid(row.get("agent_run_id"), "agent_run_id"),
        tender_id=_normalize_uuid(row.get("tender_id"), "tender_id"),
        company_id=_normalize_uuid(row.get("company_id"), "company_id"),
        requirement_key=str(row.get("requirement_key") or ""),
        requirement=str(row.get("requirement") or ""),
        requirement_type=RequirementType(str(row.get("requirement_type"))),
        match_status=FitGapMatchStatus(str(row.get("match_status"))),
        risk_level=str(row.get("risk_level") or "medium"),  # type: ignore[arg-type]
        confidence=float(row.get("confidence") or 0),
        assessment=str(row.get("assessment") or ""),
        tender_evidence_refs=tuple(
            EvidenceRef.model_validate(ref)
            for ref in _sequence(row.get("tender_evidence_refs"))
        ),
        company_evidence_refs=tuple(
            EvidenceRef.model_validate(ref)
            for ref in _sequence(row.get("company_evidence_refs"))
        ),
        tender_evidence_ids=tuple(
            _normalize_uuid(value, "tender_evidence_ids")
            for value in _sequence(row.get("tender_evidence_ids"))
        ),
        company_evidence_ids=tuple(
            _normalize_uuid(value, "company_evidence_ids")
            for value in _sequence(row.get("company_evidence_ids"))
        ),
        missing_info=tuple(str(value) for value in _sequence(row.get("missing_info"))),
        recommended_actions=tuple(
            str(value) for value in _sequence(row.get("recommended_actions"))
        ),
        metadata=dict(_mapping(row.get("metadata"))),
    )


def _evidence_ref(item: EvidenceItemState) -> EvidenceRef:
    return EvidenceRef(
        evidence_key=item.evidence_key,
        source_type=item.source_type,
        evidence_id=item.evidence_id,
    )


def _uuid_tuple(value: UUID | None) -> tuple[UUID, ...]:
    return (value,) if value is not None else ()


def _normalize_uuid(value: object, field_name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise FitGapError(f"{field_name} must be a UUID.") from exc


def _response_rows(response: Any) -> list[Mapping[str, Any]]:
    data = getattr(response, "data", None)
    if not isinstance(data, list):
        raise FitGapError("Supabase requirement_fit_gaps query returned no row list.")
    return [row for row in data if isinstance(row, Mapping)]


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, str) else ()


def _tender_sort_key(item: EvidenceItemState) -> tuple[str, int, str]:
    return (str(item.document_id or ""), item.page_start or 0, item.evidence_key)


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", _normalized(text))


def _normalized(text: str) -> str:
    return (
        text.casefold()
        .replace("å", "a")
        .replace("ä", "a")
        .replace("ö", "o")
        .replace("-", " ")
    )


def _short(text: str, *, limit: int = 120) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "or",
        "must",
        "shall",
        "ska",
        "skall",
        "supplier",
        "leverantor",
        "provide",
        "include",
        "require",
        "required",
        "krav",
        "requirement",
        "company",
        "profile",
        "evidence",
    }
)

_ROUTE_CATEGORIES: dict[RequirementType, tuple[str, ...]] = {
    RequirementType.SHALL_REQUIREMENT: (
        "certification",
        "reference",
        "capacity",
        "cv",
        "policy",
        "economics",
        "legal",
    ),
    RequirementType.QUALIFICATION_REQUIREMENT: (
        "certification",
        "reference",
        "capacity",
        "cv",
        "legal",
    ),
    RequirementType.EXCLUSION_GROUND: ("legal", "status", "financial"),
    RequirementType.FINANCIAL_STANDING: (
        "economics",
        "financial",
        "revenue",
        "credit",
    ),
    RequirementType.LEGAL_OR_REGULATORY_REFERENCE: ("legal", "policy", "insurance"),
    RequirementType.QUALITY_MANAGEMENT: (
        "certification",
        "quality",
        "policy",
        "process",
    ),
    RequirementType.SUBMISSION_DOCUMENT: (
        "cv",
        "policy",
        "legal",
        "certificate",
        "pricing",
    ),
    RequirementType.CONTRACT_OBLIGATION: (
        "policy",
        "legal",
        "capacity",
        "insurance",
        "pricing",
    ),
}


__all__ = [
    "FitGapError",
    "FitGapMatchStatus",
    "RequirementFitGapItem",
    "build_requirement_fit_gap_board",
    "ensure_requirement_fit_gaps_for_run",
    "fit_gap_items_from_state",
    "fit_gap_payload",
    "list_requirement_fit_gaps_for_run",
]
