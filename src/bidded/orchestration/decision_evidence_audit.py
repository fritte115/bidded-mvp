from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from bidded.orchestration.state import (
    BidRunState,
    DocumentChunkState,
    EvidenceItemState,
    EvidenceRef,
    EvidenceSourceType,
    StrictStateModel,
)
from bidded.requirements import RequirementType

DECISION_EVIDENCE_AUDIT_SCHEMA_VERSION = (
    "2026-04-23.decision-evidence-audit.v1"
)
_FORMAL_BLOCKER_REQUIREMENT_TYPES = frozenset(
    {
        RequirementType.EXCLUSION_GROUND,
        RequirementType.QUALIFICATION_REQUIREMENT,
    }
)
_BOTH_SOURCE_TYPES = (
    EvidenceSourceType.TENDER_DOCUMENT,
    EvidenceSourceType.COMPANY_PROFILE,
)
_SOURCE_TYPE_VALUES = {source_type.value for source_type in EvidenceSourceType}
_SUPPORTED_WEIGHT = 0.45
_SOURCE_VERIFICATION_WEIGHT = 0.25
_SOURCE_TYPE_WEIGHT = 0.20
_FORMAL_BLOCKER_WEIGHT = 0.10
_OVERCONFIDENCE_TOLERANCE = 0.20


class DecisionAuditFinding(StrictStateModel):
    """One deterministic issue or derived fact from the decision audit graph."""

    kind: Literal[
        "unsupported_claim",
        "weak_claim",
        "strong_claim",
        "source_unverified",
        "source_type_mismatch",
        "invalid_hard_blocker",
        "overconfident_decision",
    ]
    severity: Literal["info", "warning", "error"]
    message: str = Field(min_length=1)
    claim_id: str | None = None
    evidence_key: str | None = None
    field_path: str | None = None
    evidence_keys: tuple[str, ...] = ()


class DecisionAuditClaim(StrictStateModel):
    """A material Judge claim that can be checked against cited evidence."""

    claim_id: str = Field(min_length=1)
    claim_type: str = Field(min_length=1)
    text: str = Field(min_length=1)
    field_path: str = Field(min_length=1)
    evidence_refs: tuple[EvidenceRef, ...] = ()
    required_source_types: tuple[EvidenceSourceType, ...] = ()
    requirement_type: RequirementType | None = None
    is_formal_blocker: bool = False


class DecisionAuditEvidence(StrictStateModel):
    """A cited evidence ref resolved, or attempted, against the evidence board."""

    evidence_key: str = Field(min_length=1)
    source_type: EvidenceSourceType
    evidence_id: UUID | None = None
    resolved: bool = False
    source_verified: bool = False
    requirement_type: RequirementType | None = None
    excerpt: str = ""
    source_label: str = ""


class DecisionAuditEdge(StrictStateModel):
    """A support edge from one decision claim to one cited evidence ref."""

    claim_id: str = Field(min_length=1)
    evidence_key: str = Field(min_length=1)
    source_type: EvidenceSourceType
    evidence_id: UUID | None = None
    resolved: bool = False
    source_verified: bool = False


class DecisionEvidenceGraph(StrictStateModel):
    """Bidded-native claim/evidence graph inspired by BITF."""

    claims: tuple[DecisionAuditClaim, ...] = ()
    evidence: tuple[DecisionAuditEvidence, ...] = ()
    edges: tuple[DecisionAuditEdge, ...] = ()


class DecisionEvidenceAudit(StrictStateModel):
    """Runtime audit comparing Judge confidence to evidence graph support."""

    schema_version: str = DECISION_EVIDENCE_AUDIT_SCHEMA_VERSION
    gate_verdict: Literal["confirmed", "flagged", "rejected"]
    structural_score: float = Field(ge=0, le=1)
    judge_confidence: float = Field(ge=0, le=1)
    claim_count: int = Field(ge=0)
    evidence_count: int = Field(ge=0)
    support_edge_count: int = Field(ge=0)
    supported_claim_count: int = Field(ge=0)
    unsupported_claim_count: int = Field(ge=0)
    weak_claim_count: int = Field(ge=0)
    strong_claim_count: int = Field(ge=0)
    source_verified_count: int = Field(ge=0)
    source_unverified_count: int = Field(ge=0)
    source_type_mismatch_count: int = Field(ge=0)
    invalid_hard_blocker_count: int = Field(ge=0)
    overconfident_decision: bool = False
    graph: DecisionEvidenceGraph
    findings: tuple[DecisionAuditFinding, ...] = ()


def audit_decision_evidence(
    state: BidRunState,
    final_decision: Mapping[str, Any] | None = None,
) -> DecisionEvidenceAudit:
    """Build and score the deterministic decision evidence audit graph."""

    decision_payload = (
        dict(final_decision)
        if final_decision is not None
        else (
            state.final_decision.model_dump(mode="json")
            if state.final_decision is not None
            else {}
        )
    )
    claims = _decision_claims(decision_payload, state.evidence_board)
    evidence_by_identity: dict[tuple[str, str, UUID | None], DecisionAuditEvidence] = {}
    edges: list[DecisionAuditEdge] = []

    for claim in claims:
        for ref in claim.evidence_refs:
            audit_evidence = _audit_evidence_for_ref(ref, state)
            identity = (
                audit_evidence.evidence_key,
                audit_evidence.source_type.value,
                audit_evidence.evidence_id,
            )
            evidence_by_identity[identity] = audit_evidence
            edges.append(
                DecisionAuditEdge(
                    claim_id=claim.claim_id,
                    evidence_key=audit_evidence.evidence_key,
                    source_type=audit_evidence.source_type,
                    evidence_id=audit_evidence.evidence_id,
                    resolved=audit_evidence.resolved,
                    source_verified=audit_evidence.source_verified,
                )
            )

    graph = DecisionEvidenceGraph(
        claims=tuple(claims),
        evidence=tuple(evidence_by_identity.values()),
        edges=tuple(edges),
    )
    return _score_graph(
        graph,
        judge_confidence=_clamped_float(decision_payload.get("confidence")),
        evidence_board=state.evidence_board,
    )


def _decision_claims(
    decision_payload: Mapping[str, Any],
    evidence_board: Sequence[EvidenceItemState],
) -> list[DecisionAuditClaim]:
    available_source_types = frozenset(item.source_type for item in evidence_board)
    claims: list[DecisionAuditClaim] = []

    def add_claim(
        *,
        claim_type: str,
        text: str,
        field_path: str,
        raw_refs: object,
        raw_item: Mapping[str, Any] | None = None,
        is_formal_blocker: bool = False,
    ) -> None:
        clean_text = _clean_text(text)
        if not clean_text:
            return
        requirement_type = _requirement_type(_mapping(raw_item).get("requirement_type"))
        evidence_refs = tuple(_evidence_refs(raw_refs))
        claims.append(
            DecisionAuditClaim(
                claim_id=f"claim-{len(claims) + 1:03d}",
                claim_type=claim_type,
                text=clean_text,
                field_path=field_path,
                evidence_refs=evidence_refs,
                required_source_types=_required_source_types(
                    claim_type=claim_type,
                    text=clean_text,
                    raw_item=raw_item or {},
                    available_source_types=available_source_types,
                ),
                requirement_type=requirement_type,
                is_formal_blocker=is_formal_blocker,
            )
        )

    for index, raw_item in enumerate(
        _sequence(decision_payload.get("compliance_matrix"))
    ):
        item = _mapping(raw_item)
        add_claim(
            claim_type="compliance_matrix",
            text=_join_text(item.get("requirement"), item.get("assessment")),
            field_path=f"compliance_matrix[{index}]",
            raw_refs=item.get("evidence_refs"),
            raw_item=item,
        )

    for field_name, claim_type, is_formal in (
        ("compliance_blockers", "compliance_blocker", True),
        ("potential_blockers", "potential_blocker", False),
    ):
        for index, raw_item in enumerate(_sequence(decision_payload.get(field_name))):
            item = _mapping(raw_item)
            add_claim(
                claim_type=claim_type,
                text=str(item.get("claim") or raw_item),
                field_path=f"{field_name}[{index}]",
                raw_refs=item.get("evidence_refs"),
                raw_item=item,
                is_formal_blocker=is_formal,
            )

    for index, raw_item in enumerate(_sequence(decision_payload.get("risk_register"))):
        item = _mapping(raw_item)
        add_claim(
            claim_type="risk_register",
            text=_join_text(item.get("risk"), item.get("mitigation")),
            field_path=f"risk_register[{index}]",
            raw_refs=item.get("evidence_refs"),
            raw_item=item,
        )

    for field_name, claim_type in (
        ("recommended_action_details", "recommended_action"),
        ("missing_info_details", "missing_info"),
    ):
        for index, raw_item in enumerate(_sequence(decision_payload.get(field_name))):
            item = _mapping(raw_item)
            add_claim(
                claim_type=claim_type,
                text=str(item.get("text") or raw_item),
                field_path=f"{field_name}[{index}]",
                raw_refs=item.get("evidence_refs"),
                raw_item=item,
            )

    if _sequence(decision_payload.get("evidence_refs")):
        add_claim(
            claim_type="cited_memo",
            text=str(decision_payload.get("cited_memo") or ""),
            field_path="cited_memo",
            raw_refs=decision_payload.get("evidence_refs"),
        )

    return claims


def _audit_evidence_for_ref(
    evidence_ref: EvidenceRef,
    state: BidRunState,
) -> DecisionAuditEvidence:
    evidence_item = _matching_evidence_item(evidence_ref, state.evidence_board)
    if evidence_item is None:
        return DecisionAuditEvidence(
            evidence_key=evidence_ref.evidence_key,
            source_type=evidence_ref.source_type,
            evidence_id=evidence_ref.evidence_id,
        )

    return DecisionAuditEvidence(
        evidence_key=evidence_item.evidence_key,
        source_type=evidence_item.source_type,
        evidence_id=evidence_item.evidence_id,
        resolved=True,
        source_verified=_source_verified(evidence_item, state.chunks),
        requirement_type=evidence_item.requirement_type,
        excerpt=evidence_item.excerpt,
        source_label=str(evidence_item.source_metadata.get("source_label") or ""),
    )


def _score_graph(
    graph: DecisionEvidenceGraph,
    *,
    judge_confidence: float,
    evidence_board: Sequence[EvidenceItemState],
) -> DecisionEvidenceAudit:
    edges_by_claim = {
        claim.claim_id: [
            edge
            for edge in graph.edges
            if edge.claim_id == claim.claim_id and edge.resolved
        ]
        for claim in graph.claims
    }
    evidence_by_key = {
        (
            evidence.evidence_key,
            evidence.source_type.value,
            evidence.evidence_id,
        ): evidence
        for evidence in graph.evidence
    }
    findings: list[DecisionAuditFinding] = []
    supported_claim_count = 0
    unsupported_claim_count = 0
    weak_claim_count = 0
    strong_claim_count = 0
    source_type_mismatch_count = 0
    invalid_hard_blocker_count = 0

    for claim in graph.claims:
        resolved_edges = edges_by_claim[claim.claim_id]
        if resolved_edges:
            supported_claim_count += 1
        else:
            unsupported_claim_count += 1
            findings.append(
                DecisionAuditFinding(
                    kind="unsupported_claim",
                    severity="error",
                    message="Material Judge claim has no resolved evidence refs.",
                    claim_id=claim.claim_id,
                    field_path=claim.field_path,
                    evidence_keys=_claim_evidence_keys(claim),
                )
            )

        missing_source_types = _missing_required_source_types(
            claim,
            resolved_edges,
        )
        if missing_source_types:
            source_type_mismatch_count += 1
            findings.append(
                DecisionAuditFinding(
                    kind="source_type_mismatch",
                    severity="warning",
                    message=(
                        "Material Judge claim is missing required evidence source "
                        "type(s): "
                        f"{', '.join(source.value for source in missing_source_types)}."
                    ),
                    claim_id=claim.claim_id,
                    field_path=claim.field_path,
                    evidence_keys=_claim_evidence_keys(claim),
                )
            )

        if claim.is_formal_blocker and not _has_valid_formal_blocker_evidence(
            resolved_edges,
            evidence_by_key=evidence_by_key,
        ):
            invalid_hard_blocker_count += 1
            findings.append(
                DecisionAuditFinding(
                    kind="invalid_hard_blocker",
                    severity="error",
                    message=(
                        "Formal compliance blocker lacks tender evidence classified "
                        "as exclusion_ground or qualification_requirement."
                    ),
                    claim_id=claim.claim_id,
                    field_path=claim.field_path,
                    evidence_keys=_claim_evidence_keys(claim),
                )
            )

        if resolved_edges and not missing_source_types:
            if len(resolved_edges) >= 2 and all(
                edge.source_verified for edge in resolved_edges
            ):
                strong_claim_count += 1
                findings.append(
                    DecisionAuditFinding(
                        kind="strong_claim",
                        severity="info",
                        message=(
                            "Material Judge claim has multiple verified evidence refs."
                        ),
                        claim_id=claim.claim_id,
                        field_path=claim.field_path,
                        evidence_keys=_claim_evidence_keys(claim),
                    )
                )
            else:
                weak_claim_count += 1
                findings.append(
                    DecisionAuditFinding(
                        kind="weak_claim",
                        severity="warning",
                        message=(
                            "Material Judge claim has evidence but limited "
                            "structural support."
                        ),
                        claim_id=claim.claim_id,
                        field_path=claim.field_path,
                        evidence_keys=_claim_evidence_keys(claim),
                    )
                )

    for evidence in graph.evidence:
        if evidence.source_verified:
            continue
        findings.append(
            DecisionAuditFinding(
                kind="source_unverified",
                severity="warning",
                message=(
                    "Cited evidence could not be verified against available "
                    "source provenance."
                ),
                evidence_key=evidence.evidence_key,
                evidence_keys=(evidence.evidence_key,),
            )
        )

    formal_claim_count = sum(1 for claim in graph.claims if claim.is_formal_blocker)
    source_verified_count = sum(
        1 for evidence in graph.evidence if evidence.source_verified
    )
    source_unverified_count = len(graph.evidence) - source_verified_count
    structural_score = _structural_score(
        claim_count=len(graph.claims),
        evidence_count=len(graph.evidence),
        supported_claim_count=supported_claim_count,
        source_verified_count=source_verified_count,
        source_type_mismatch_count=source_type_mismatch_count,
        formal_claim_count=formal_claim_count,
        invalid_hard_blocker_count=invalid_hard_blocker_count,
    )
    overconfident_decision = (
        judge_confidence - structural_score > _OVERCONFIDENCE_TOLERANCE
    )
    if overconfident_decision:
        findings.append(
            DecisionAuditFinding(
                kind="overconfident_decision",
                severity="warning",
                message=(
                    "Judge confidence is stronger than the structural evidence audit."
                ),
            )
        )

    gate_verdict = _gate_verdict(
        claim_count=len(graph.claims),
        supported_claim_count=supported_claim_count,
        invalid_hard_blocker_count=invalid_hard_blocker_count,
        overconfident_decision=overconfident_decision,
        unsupported_claim_count=unsupported_claim_count,
        source_type_mismatch_count=source_type_mismatch_count,
        source_unverified_count=source_unverified_count,
    )

    return DecisionEvidenceAudit(
        gate_verdict=gate_verdict,
        structural_score=structural_score,
        judge_confidence=judge_confidence,
        claim_count=len(graph.claims),
        evidence_count=len(graph.evidence),
        support_edge_count=len(graph.edges),
        supported_claim_count=supported_claim_count,
        unsupported_claim_count=unsupported_claim_count,
        weak_claim_count=weak_claim_count,
        strong_claim_count=strong_claim_count,
        source_verified_count=source_verified_count,
        source_unverified_count=source_unverified_count,
        source_type_mismatch_count=source_type_mismatch_count,
        invalid_hard_blocker_count=invalid_hard_blocker_count,
        overconfident_decision=overconfident_decision,
        graph=graph,
        findings=tuple(findings),
    )


def _structural_score(
    *,
    claim_count: int,
    evidence_count: int,
    supported_claim_count: int,
    source_verified_count: int,
    source_type_mismatch_count: int,
    formal_claim_count: int,
    invalid_hard_blocker_count: int,
) -> float:
    if claim_count == 0:
        return 0.0
    supported_ratio = supported_claim_count / claim_count
    source_verification_ratio = (
        source_verified_count / evidence_count if evidence_count else 0.0
    )
    source_type_ratio = (claim_count - source_type_mismatch_count) / claim_count
    formal_blocker_ratio = (
        1.0
        if formal_claim_count == 0
        else (formal_claim_count - invalid_hard_blocker_count) / formal_claim_count
    )
    return round(
        max(
            0.0,
            min(
                1.0,
                _SUPPORTED_WEIGHT * supported_ratio
                + _SOURCE_VERIFICATION_WEIGHT * source_verification_ratio
                + _SOURCE_TYPE_WEIGHT * source_type_ratio
                + _FORMAL_BLOCKER_WEIGHT * formal_blocker_ratio,
            ),
        ),
        6,
    )


def _gate_verdict(
    *,
    claim_count: int,
    supported_claim_count: int,
    invalid_hard_blocker_count: int,
    overconfident_decision: bool,
    unsupported_claim_count: int,
    source_type_mismatch_count: int,
    source_unverified_count: int,
) -> Literal["confirmed", "flagged", "rejected"]:
    if claim_count == 0 or supported_claim_count == 0 or invalid_hard_blocker_count:
        return "rejected"
    if (
        overconfident_decision
        or unsupported_claim_count
        or source_type_mismatch_count
        or source_unverified_count
    ):
        return "flagged"
    return "confirmed"


def _missing_required_source_types(
    claim: DecisionAuditClaim,
    resolved_edges: Sequence[DecisionAuditEdge],
) -> tuple[EvidenceSourceType, ...]:
    if not claim.required_source_types:
        return ()
    present = {edge.source_type for edge in resolved_edges}
    return tuple(
        source_type
        for source_type in claim.required_source_types
        if source_type not in present
    )


def _has_valid_formal_blocker_evidence(
    resolved_edges: Sequence[DecisionAuditEdge],
    *,
    evidence_by_key: Mapping[tuple[str, str, UUID | None], DecisionAuditEvidence],
) -> bool:
    for edge in resolved_edges:
        evidence = evidence_by_key.get(
            (edge.evidence_key, edge.source_type.value, edge.evidence_id)
        )
        if (
            evidence is not None
            and evidence.source_type is EvidenceSourceType.TENDER_DOCUMENT
            and evidence.requirement_type in _FORMAL_BLOCKER_REQUIREMENT_TYPES
        ):
            return True
    return False


def _source_verified(
    evidence_item: EvidenceItemState,
    chunks: Sequence[DocumentChunkState],
) -> bool:
    if evidence_item.source_type is EvidenceSourceType.COMPANY_PROFILE:
        return evidence_item.company_id is not None and bool(evidence_item.field_path)

    if evidence_item.source_type is not EvidenceSourceType.TENDER_DOCUMENT:
        return False

    has_provenance = all(
        value is not None
        for value in (
            evidence_item.document_id,
            evidence_item.chunk_id,
            evidence_item.page_start,
            evidence_item.page_end,
        )
    )
    if not has_provenance:
        return False

    matching_chunks = [
        chunk for chunk in chunks if chunk.chunk_id == evidence_item.chunk_id
    ]
    if not chunks:
        return True
    if not matching_chunks:
        return False
    return any(
        _contains_excerpt(chunk.text, evidence_item.excerpt)
        for chunk in matching_chunks
    )


def _contains_excerpt(text: str, excerpt: str) -> bool:
    if excerpt in text:
        return True
    return _normalize_space(excerpt) in _normalize_space(text)


def _matching_evidence_item(
    evidence_ref: EvidenceRef,
    evidence_board: Sequence[EvidenceItemState],
) -> EvidenceItemState | None:
    return next(
        (
            item
            for item in evidence_board
            if item.evidence_key == evidence_ref.evidence_key
            and item.source_type is evidence_ref.source_type
            and item.evidence_id == evidence_ref.evidence_id
        ),
        None,
    )


def _required_source_types(
    *,
    claim_type: str,
    text: str,
    raw_item: Mapping[str, Any],
    available_source_types: frozenset[EvidenceSourceType],
) -> tuple[EvidenceSourceType, ...]:
    has_tender_and_company = all(
        source_type in available_source_types for source_type in _BOTH_SOURCE_TYPES
    )
    if (
        claim_type == "compliance_matrix"
        and str(raw_item.get("status") or "").strip().lower() == "met"
        and has_tender_and_company
    ):
        return _BOTH_SOURCE_TYPES
    if _looks_like_tender_company_comparison(text) and has_tender_and_company:
        return _BOTH_SOURCE_TYPES
    if claim_type == "compliance_blocker":
        return (EvidenceSourceType.TENDER_DOCUMENT,)
    return ()


def _looks_like_tender_company_comparison(text: str) -> bool:
    normalized = text.casefold()
    return (
        "company" in normalized
        and ("tender" in normalized or "requirement" in normalized)
    )


def _evidence_refs(raw_refs: object) -> list[EvidenceRef]:
    refs: list[EvidenceRef] = []
    for raw_ref in _sequence(raw_refs):
        ref = _mapping(raw_ref)
        evidence_key = str(ref.get("evidence_key") or "").strip()
        source_type_value = str(ref.get("source_type") or "").strip()
        if not evidence_key or source_type_value not in _SOURCE_TYPE_VALUES:
            continue
        refs.append(
            EvidenceRef(
                evidence_key=evidence_key,
                source_type=EvidenceSourceType(source_type_value),
                evidence_id=_uuid_or_none(ref.get("evidence_id")),
            )
        )
    return refs


def _claim_evidence_keys(claim: DecisionAuditClaim) -> tuple[str, ...]:
    return tuple(ref.evidence_key for ref in claim.evidence_refs)


def _requirement_type(value: object) -> RequirementType | None:
    if value is None or isinstance(value, RequirementType):
        return value
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower().replace(" ", "_").replace("-", "_")
    try:
        return RequirementType(normalized)
    except ValueError:
        return None


def _uuid_or_none(value: object) -> UUID | None:
    if value is None or isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, str) else ()


def _join_text(*values: object) -> str:
    return " - ".join(
        _clean_text(str(value)) for value in values if _clean_text(str(value))
    )


def _clean_text(value: str) -> str:
    return _normalize_space(str(value or ""))


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _clamped_float(value: object) -> float:
    try:
        parsed = float(str(value))
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, parsed))


__all__ = [
    "DECISION_EVIDENCE_AUDIT_SCHEMA_VERSION",
    "DecisionAuditClaim",
    "DecisionAuditEdge",
    "DecisionAuditEvidence",
    "DecisionAuditFinding",
    "DecisionEvidenceAudit",
    "DecisionEvidenceGraph",
    "audit_decision_evidence",
]
