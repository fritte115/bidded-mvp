from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bidded.retrieval import RetrievedDocumentChunk


class SupabaseTenderEvidenceQuery(Protocol):
    def select(self, columns: str) -> SupabaseTenderEvidenceQuery: ...

    def eq(self, column: str, value: object) -> SupabaseTenderEvidenceQuery: ...

    def upsert(
        self,
        payload: list[dict[str, Any]],
        *,
        on_conflict: str | None = None,
    ) -> SupabaseTenderEvidenceQuery: ...

    def execute(self) -> Any: ...


class SupabaseTenderEvidenceClient(Protocol):
    def table(self, table_name: str) -> SupabaseTenderEvidenceQuery: ...


@dataclass(frozen=True)
class TenderEvidenceUpsertResult:
    evidence_count: int
    evidence_keys: tuple[str, ...]
    rows_returned: int


class TenderEvidenceCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_type: Literal["tender_document"] = "tender_document"
    document_id: UUID
    chunk_id: UUID
    page_start: int = Field(gt=0)
    page_end: int = Field(gt=0)
    excerpt: str = Field(min_length=1)
    source_label: str = Field(min_length=1)
    category: str = Field(min_length=1)
    normalized_meaning: str = Field(min_length=1)
    confidence: float = Field(default=0.8, ge=0, le=1)

    @model_validator(mode="after")
    def validate_page_range(self) -> TenderEvidenceCandidate:
        if self.page_end < self.page_start:
            raise ValueError("page_end must be greater than or equal to page_start")
        return self


def build_tender_evidence_candidates(
    chunks: list[RetrievedDocumentChunk],
) -> list[TenderEvidenceCandidate]:
    """Propose excerpt-level tender evidence from retrieved document chunks."""

    candidates: list[TenderEvidenceCandidate] = []
    for chunk in chunks:
        source_label = str(chunk.metadata.get("source_label") or "tender document")
        for sentence in _sentences(chunk.text):
            category = _category_for_sentence(sentence)
            if category is None:
                continue

            candidates.append(
                TenderEvidenceCandidate(
                    document_id=chunk.document_id,
                    chunk_id=UUID(chunk.chunk_id),
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    excerpt=sentence,
                    source_label=source_label,
                    category=category,
                    normalized_meaning=f"Tender states: {sentence}",
                )
            )

    if not candidates and chunks:
        chunk = chunks[0]
        raw = chunk.text.strip()
        if raw:
            excerpt = raw[:800] if len(raw) > 800 else raw
            source_label = str(chunk.metadata.get("source_label") or "tender document")
            candidates.append(
                TenderEvidenceCandidate(
                    document_id=chunk.document_id,
                    chunk_id=UUID(chunk.chunk_id),
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    excerpt=excerpt,
                    source_label=source_label,
                    category="tender_content",
                    normalized_meaning=(
                        "Tender document excerpt (fallback when no keyword "
                        "categories matched)."
                    ),
                )
            )

    return candidates


def build_tender_evidence_items(
    candidates: list[TenderEvidenceCandidate | Mapping[str, Any]],
    *,
    tenant_key: str = "demo",
) -> list[dict[str, Any]]:
    """Validate candidates and convert them to evidence_items payloads."""

    evidence_items: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for raw_candidate in candidates:
        candidate = TenderEvidenceCandidate.model_validate(raw_candidate)
        evidence_key = _evidence_key(candidate)
        if evidence_key in seen_keys:
            continue
        seen_keys.add(evidence_key)
        evidence_items.append(
            {
                "tenant_key": tenant_key,
                "evidence_key": evidence_key,
                "source_type": "tender_document",
                "excerpt": candidate.excerpt,
                "normalized_meaning": candidate.normalized_meaning,
                "category": candidate.category,
                "confidence": candidate.confidence,
                "source_metadata": {"source_label": candidate.source_label},
                "document_id": str(candidate.document_id),
                "chunk_id": str(candidate.chunk_id),
                "page_start": candidate.page_start,
                "page_end": candidate.page_end,
                "metadata": {"source": "tender_evidence_board"},
            }
        )

    return evidence_items


def upsert_tender_evidence_items(
    client: SupabaseTenderEvidenceClient,
    candidates: list[TenderEvidenceCandidate | Mapping[str, Any]],
    *,
    tenant_key: str = "demo",
) -> TenderEvidenceUpsertResult:
    evidence_items = build_tender_evidence_items(candidates, tenant_key=tenant_key)
    response = (
        client.table("evidence_items")
        .upsert(evidence_items, on_conflict="tenant_key,evidence_key")
        .execute()
    )
    data = getattr(response, "data", [])
    rows_returned = len(data) if isinstance(data, list) else 0

    return TenderEvidenceUpsertResult(
        evidence_count=len(evidence_items),
        evidence_keys=tuple(item["evidence_key"] for item in evidence_items),
        rows_returned=rows_returned,
    )


def get_tender_evidence_item_by_key(
    client: SupabaseTenderEvidenceClient,
    evidence_key: str,
    *,
    tenant_key: str = "demo",
) -> dict[str, Any] | None:
    response = (
        client.table("evidence_items")
        .select("*")
        .eq("tenant_key", tenant_key)
        .eq("source_type", "tender_document")
        .eq("evidence_key", evidence_key)
        .execute()
    )
    data = getattr(response, "data", None)
    if not isinstance(data, list):
        return None
    first_row = next((row for row in data if isinstance(row, Mapping)), None)
    return dict(first_row) if first_row is not None else None


def _evidence_key(candidate: TenderEvidenceCandidate) -> str:
    readable_slug = _slug(candidate.excerpt)
    digest = sha256(
        "|".join(
            [
                str(candidate.document_id),
                str(candidate.chunk_id),
                str(candidate.page_start),
                str(candidate.page_end),
                candidate.category,
                candidate.excerpt,
                candidate.normalized_meaning,
            ]
        ).encode("utf-8")
    ).hexdigest()[:8].upper()
    return (
        f"TENDER-P{candidate.page_start}-"
        f"{_slug(candidate.category)}-{readable_slug[:80].strip('-')}-{digest}"
    )


def _sentences(text: str) -> list[str]:
    return [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", text.strip())
        if sentence.strip()
    ]


def _category_for_sentence(sentence: str) -> str | None:
    lowered = sentence.lower()
    if any(term in lowered for term in ["must", "shall", "mandatory", "required"]):
        return "mandatory_requirement"
    if "award" in lowered or "evaluation" in lowered:
        return "award_criterion"
    if "deadline" in lowered or "submission" in lowered:
        return "submission_deadline"
    if "liability" in lowered or "penalty" in lowered:
        return "contract_risk"
    return None


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").upper()
    return slug or "UNKNOWN"


__all__ = [
    "TenderEvidenceUpsertResult",
    "TenderEvidenceCandidate",
    "build_tender_evidence_candidates",
    "build_tender_evidence_items",
    "get_tender_evidence_item_by_key",
    "upsert_tender_evidence_items",
]
