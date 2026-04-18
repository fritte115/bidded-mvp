from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import sqrt
from typing import Any, Protocol
from uuid import UUID

from bidded.embeddings import MockEmbeddingAdapter

DEMO_TENANT_KEY = "demo"


class RetrievalError(RuntimeError):
    """Raised when retrieval input or source rows are invalid."""


class SupabaseDocumentChunkQuery(Protocol):
    def select(self, columns: str) -> SupabaseDocumentChunkQuery: ...

    def eq(self, column: str, value: object) -> SupabaseDocumentChunkQuery: ...

    def execute(self) -> Any: ...


class SupabaseDocumentChunkClient(Protocol):
    def table(self, table_name: str) -> SupabaseDocumentChunkQuery: ...


class EmbeddingAdapter(Protocol):
    name: str
    dimensions: int

    def embed_text(self, text: str) -> list[float]: ...


@dataclass(frozen=True)
class RetrievedDocumentChunk:
    chunk_id: str
    document_id: UUID
    page_start: int
    page_end: int
    chunk_index: int
    text: str
    metadata: dict[str, Any]


def retrieve_document_chunks(
    client: SupabaseDocumentChunkClient,
    *,
    query: str,
    document_id: UUID | str | None = None,
    top_k: int = 5,
    tenant_key: str = DEMO_TENANT_KEY,
    embedding_adapter: EmbeddingAdapter | None = None,
) -> list[RetrievedDocumentChunk]:
    """Return top matching document chunks using embeddings or keyword fallback."""

    normalized_query = query.strip()
    if not normalized_query:
        raise RetrievalError("query must not be empty.")
    if top_k <= 0:
        raise RetrievalError("top_k must be greater than zero.")

    response = _document_chunk_query(
        client,
        document_id=_normalize_uuid_or_none(document_id),
        tenant_key=tenant_key,
    ).execute()
    rows = _response_rows(response)

    if embedding_adapter is not None:
        embedding_results = _rank_by_embedding(
            rows,
            query=normalized_query,
            top_k=top_k,
            embedding_adapter=embedding_adapter,
        )
        if embedding_results:
            return embedding_results

    return _rank_by_keyword(rows, query=normalized_query, top_k=top_k)


def _rank_by_keyword(
    rows: list[Mapping[str, Any]],
    *,
    query: str,
    top_k: int,
) -> list[RetrievedDocumentChunk]:
    scored_rows = [
        (
            _keyword_score(query, str(row.get("text") or "")),
            row,
        )
        for row in rows
    ]

    ranked_rows = sorted(
        ((score, row) for score, row in scored_rows if score > 0),
        key=lambda score_row: (
            -score_row[0],
            _int_value(score_row[1].get("chunk_index")),
            str(score_row[1].get("id") or ""),
        ),
    )

    return [
        _retrieved_chunk(row, method="keyword", score=score)
        for score, row in ranked_rows[:top_k]
    ]


def _rank_by_embedding(
    rows: list[Mapping[str, Any]],
    *,
    query: str,
    top_k: int,
    embedding_adapter: EmbeddingAdapter,
) -> list[RetrievedDocumentChunk]:
    query_vector = embedding_adapter.embed_text(query)
    scored_rows = [
        (
            _cosine_similarity(
                query_vector,
                _chunk_embedding_vector(row, embedding_adapter=embedding_adapter),
            ),
            row,
        )
        for row in rows
    ]

    ranked_rows = sorted(
        ((score, row) for score, row in scored_rows if score > 0),
        key=lambda score_row: (
            -score_row[0],
            _int_value(score_row[1].get("chunk_index")),
            str(score_row[1].get("id") or ""),
        ),
    )

    return [
        _retrieved_chunk(
            row,
            method=embedding_adapter.name,
            score=round(score, 6),
        )
        for score, row in ranked_rows[:top_k]
    ]


def _document_chunk_query(
    client: SupabaseDocumentChunkClient,
    *,
    document_id: UUID | None,
    tenant_key: str,
) -> SupabaseDocumentChunkQuery:
    query = (
        client.table("document_chunks")
        .select(
            "id,tenant_key,document_id,page_start,page_end,chunk_index,"
            "text,metadata,embedding"
        )
        .eq("tenant_key", tenant_key)
    )
    if document_id is not None:
        query = query.eq("document_id", str(document_id))
    return query


def _response_rows(response: Any) -> list[Mapping[str, Any]]:
    data = getattr(response, "data", None)
    if not isinstance(data, list):
        raise RetrievalError("Supabase document_chunks query did not return a list.")
    return [row for row in data if isinstance(row, Mapping)]


def _retrieved_chunk(
    row: Mapping[str, Any],
    *,
    method: str,
    score: float,
) -> RetrievedDocumentChunk:
    metadata = _metadata(row.get("metadata"))
    metadata["retrieval"] = {
        "method": method,
        "score": score,
    }
    return RetrievedDocumentChunk(
        chunk_id=str(row.get("id") or ""),
        document_id=_normalize_uuid(row.get("document_id"), "document_id"),
        page_start=_positive_int(row.get("page_start"), "page_start"),
        page_end=_positive_int(row.get("page_end"), "page_end"),
        chunk_index=_int_value(row.get("chunk_index")),
        text=str(row.get("text") or ""),
        metadata=metadata,
    )


def _keyword_score(query: str, text: str) -> float:
    query_terms = _tokens(query)
    if not query_terms:
        return 0.0

    text_terms = Counter(_tokens(text))
    matched_terms = sum(text_terms[term] for term in set(query_terms))
    if matched_terms == 0:
        return 0.0

    coverage = len(set(query_terms) & set(text_terms)) / len(set(query_terms))
    density = matched_terms / max(1, len(text_terms))
    phrase_boost = 0.5 if " ".join(query_terms) in " ".join(_tokens(text)) else 0.0
    return round(matched_terms + coverage + density + phrase_boost, 6)


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _chunk_embedding_vector(
    row: Mapping[str, Any],
    *,
    embedding_adapter: EmbeddingAdapter,
) -> list[float]:
    stored_embedding = _stored_embedding_vector(row.get("embedding"))
    if stored_embedding is not None:
        return stored_embedding
    return embedding_adapter.embed_text(str(row.get("text") or ""))


def _stored_embedding_vector(value: object) -> list[float] | None:
    if isinstance(value, str):
        stripped = value.strip().removeprefix("[").removesuffix("]")
        if not stripped:
            return None
        try:
            return [float(part.strip()) for part in stripped.split(",")]
        except ValueError:
            return None

    if isinstance(value, Sequence):
        try:
            return [float(item) for item in value]
        except (TypeError, ValueError):
            return None

    return None


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0

    left_norm = sqrt(sum(value * value for value in left))
    right_norm = sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0

    dot_product = sum(
        left_value * right_value
        for left_value, right_value in zip(left, right, strict=True)
    )
    return dot_product / (left_norm * right_norm)


def _metadata(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _normalize_uuid_or_none(value: UUID | str | None) -> UUID | None:
    if value is None:
        return None
    return _normalize_uuid(value, "document_id")


def _normalize_uuid(value: object, field_name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except ValueError as exc:
        raise RetrievalError(f"{field_name} must be a UUID.") from exc


def _positive_int(value: object, field_name: str) -> int:
    parsed = _int_value(value)
    if parsed <= 0:
        raise RetrievalError(f"{field_name} must be greater than zero.")
    return parsed


def _int_value(value: object) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError) as exc:
        raise RetrievalError("document chunk integer field is invalid.") from exc


__all__ = [
    "EmbeddingAdapter",
    "MockEmbeddingAdapter",
    "RetrievedDocumentChunk",
    "RetrievalError",
    "retrieve_document_chunks",
]
