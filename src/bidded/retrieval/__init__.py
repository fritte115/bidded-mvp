from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from math import sqrt
from typing import Any, Protocol
from uuid import UUID

from bidded.embeddings import MockEmbeddingAdapter

DEMO_TENANT_KEY = "demo"
HYBRID_RETRIEVAL_WEIGHTS: dict[str, float] = {
    "embedding_score": 0.45,
    "keyword_score": 0.30,
    "glossary_score": 0.20,
    "requirement_type": 0.05,
}


class RetrievalError(RuntimeError):
    """Raised when retrieval input or source rows are invalid."""


class SupabaseDocumentChunkQuery(Protocol):
    def select(self, columns: str) -> SupabaseDocumentChunkQuery: ...

    def eq(self, column: str, value: object) -> SupabaseDocumentChunkQuery: ...

    def execute(self) -> Any: ...


class SupabaseDocumentChunkRpc(Protocol):
    def execute(self) -> Any: ...


class SupabaseDocumentChunkClient(Protocol):
    def table(self, table_name: str) -> SupabaseDocumentChunkQuery: ...

    def rpc(
        self,
        function_name: str,
        params: dict[str, Any],
    ) -> SupabaseDocumentChunkRpc: ...


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


@dataclass
class _HybridCandidate:
    row: Mapping[str, Any]
    keyword_score: float = 0.0
    glossary_score: float = 0.0
    glossary_matches: tuple[Any, ...] = ()
    embedding_score: float = 0.0
    candidate_methods: set[str] = field(default_factory=set)


def retrieve_document_chunks(
    client: SupabaseDocumentChunkClient,
    *,
    query: str,
    document_id: UUID | str | None = None,
    top_k: int = 5,
    tenant_key: str = DEMO_TENANT_KEY,
    embedding_adapter: EmbeddingAdapter | None = None,
    match_threshold: float = 0.0,
) -> list[RetrievedDocumentChunk]:
    """Return top matching chunks with hybrid retrieval scoring."""

    normalized_query = query.strip()
    if not normalized_query:
        raise RetrievalError("query must not be empty.")
    if top_k <= 0:
        raise RetrievalError("top_k must be greater than zero.")
    if match_threshold < 0 or match_threshold > 1:
        raise RetrievalError("match_threshold must be between 0 and 1.")

    normalized_document_id = _normalize_uuid_or_none(document_id)
    rpc_rows: list[Mapping[str, Any]] = []
    if embedding_adapter is not None and _is_live_embedding_adapter(embedding_adapter):
        rpc_rows = _retrieve_with_supabase_rpc_rows(
            client,
            query=normalized_query,
            document_id=normalized_document_id,
            top_k=top_k,
            tenant_key=tenant_key,
            embedding_adapter=embedding_adapter,
            match_threshold=match_threshold,
        )
    response = _document_chunk_query(
        client,
        document_id=normalized_document_id,
        tenant_key=tenant_key,
    ).execute()
    rows = _response_rows(response)

    return rank_document_chunk_rows(
        rows,
        query=normalized_query,
        top_k=top_k,
        embedding_adapter=(
            None
            if embedding_adapter is not None
            and _is_live_embedding_adapter(embedding_adapter)
            else embedding_adapter
        ),
        embedding_candidate_rows=rpc_rows,
        match_threshold=match_threshold,
    )


def rank_document_chunk_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    query: str,
    top_k: int,
    embedding_adapter: EmbeddingAdapter | None = None,
    embedding_candidate_rows: Sequence[Mapping[str, Any]] = (),
    match_threshold: float = 0.0,
) -> list[RetrievedDocumentChunk]:
    """Rank already-loaded document chunk rows with the hybrid scoring contract."""

    normalized_query = query.strip()
    if not normalized_query:
        raise RetrievalError("query must not be empty.")
    if top_k <= 0:
        raise RetrievalError("top_k must be greater than zero.")
    if match_threshold < 0 or match_threshold > 1:
        raise RetrievalError("match_threshold must be between 0 and 1.")

    candidates: dict[str, _HybridCandidate] = {}
    query_vector = (
        embedding_adapter.embed_text(normalized_query)
        if embedding_adapter is not None
        else None
    )

    for row in rows:
        candidate = _hybrid_candidate_for_row(
            row,
            query=normalized_query,
            embedding_adapter=embedding_adapter,
            query_vector=query_vector,
            match_threshold=match_threshold,
        )
        if candidate is None:
            continue
        candidates[_row_chunk_id(candidate.row)] = candidate

    for row in embedding_candidate_rows:
        normalized_row = _normalized_rpc_row(row)
        row_id = _row_chunk_id(normalized_row)
        existing = candidates.get(row_id)
        candidate = existing or _HybridCandidate(row=normalized_row)
        try:
            embedding_score = _similarity_score(normalized_row.get("similarity"))
        except RetrievalError:
            continue
        if embedding_score >= match_threshold and embedding_score > 0:
            candidate.embedding_score = max(
                candidate.embedding_score,
                embedding_score,
            )
            candidate.candidate_methods.add("embedding")
        if existing is None:
            candidates[row_id] = candidate

    ranked_candidates = sorted(
        (
            candidate
            for candidate in candidates.values()
            if _candidate_final_score(candidate) > 0
        ),
        key=lambda candidate: (
            -_candidate_final_score(candidate),
            -candidate.embedding_score,
            -candidate.keyword_score,
            -candidate.glossary_score,
            _int_value(candidate.row.get("chunk_index")),
            _row_chunk_id(candidate.row),
        ),
    )

    return [
        _retrieved_hybrid_chunk(candidate) for candidate in ranked_candidates[:top_k]
    ]


def list_document_chunks_for_document(
    client: SupabaseDocumentChunkClient,
    *,
    document_id: UUID | str,
    tenant_key: str = DEMO_TENANT_KEY,
) -> list[RetrievedDocumentChunk]:
    """Return all stored chunks for one document in stable chunk order."""

    normalized_document_id = _normalize_uuid(document_id, "document_id")
    response = _document_chunk_query(
        client,
        document_id=normalized_document_id,
        tenant_key=tenant_key,
    ).execute()
    rows = sorted(
        _response_rows(response),
        key=lambda row: (_int_value(row.get("chunk_index")), str(row.get("id") or "")),
    )
    return [
        _retrieved_chunk(
            row,
            retrieval_metadata={"method": "document_scan", "score": 1.0},
        )
        for row in rows
    ]


def _retrieve_with_supabase_rpc_rows(
    client: SupabaseDocumentChunkClient,
    *,
    query: str,
    document_id: UUID | None,
    top_k: int,
    tenant_key: str,
    embedding_adapter: EmbeddingAdapter,
    match_threshold: float,
) -> list[Mapping[str, Any]]:
    rpc = getattr(client, "rpc", None)
    if not callable(rpc):
        return []

    try:
        query_embedding = embedding_adapter.embed_text(query)
        if len(query_embedding) != embedding_adapter.dimensions:
            return []
        response = rpc(
            "match_document_chunks",
            {
                "query_embedding": query_embedding,
                "match_count": top_k,
                "match_threshold": match_threshold,
                "tenant_key": tenant_key,
                "document_id": str(document_id) if document_id is not None else None,
            },
        ).execute()
        return _response_rows(response)
    except Exception:
        return []


def _is_live_embedding_adapter(embedding_adapter: EmbeddingAdapter) -> bool:
    return getattr(embedding_adapter, "mode", None) == "live"


def _hybrid_candidate_for_row(
    row: Mapping[str, Any],
    *,
    query: str,
    embedding_adapter: EmbeddingAdapter | None,
    query_vector: list[float] | None,
    match_threshold: float,
) -> _HybridCandidate | None:
    candidate = _HybridCandidate(row=row)
    text = str(row.get("text") or "")

    keyword_score = _keyword_score(query, text)
    if keyword_score > 0:
        candidate.keyword_score = keyword_score
        candidate.candidate_methods.add("keyword")

    glossary_matches = _query_relevant_glossary_matches(
        _match_regulatory_glossary(text),
        query,
    )
    if glossary_matches:
        candidate.glossary_matches = glossary_matches
        candidate.glossary_score = _glossary_score(glossary_matches)
        candidate.candidate_methods.add("glossary")

    if embedding_adapter is not None and query_vector is not None:
        embedding_score = _cosine_similarity(
            query_vector,
            _chunk_embedding_vector(row, embedding_adapter=embedding_adapter),
        )
        embedding_score = _clamped_score(embedding_score)
        if embedding_score >= match_threshold and embedding_score > 0:
            candidate.embedding_score = embedding_score
            candidate.candidate_methods.add("embedding")

    if not candidate.candidate_methods:
        return None
    return candidate


def _retrieved_hybrid_chunk(candidate: _HybridCandidate) -> RetrievedDocumentChunk:
    return _retrieved_chunk(
        candidate.row,
        retrieval_metadata=_hybrid_retrieval_metadata(candidate),
    )


def _hybrid_retrieval_metadata(candidate: _HybridCandidate) -> dict[str, Any]:
    final_score = _candidate_final_score(candidate)
    return {
        "method": "hybrid",
        "score": final_score,
        "final_score": final_score,
        "embedding_score": candidate.embedding_score,
        "keyword_score": candidate.keyword_score,
        "glossary_score": candidate.glossary_score,
        "glossary_matches": _glossary_matches_metadata(candidate.glossary_matches),
        "requirement_type_score": _requirement_type_score(candidate),
        "candidate_methods": sorted(candidate.candidate_methods),
        "weights": dict(HYBRID_RETRIEVAL_WEIGHTS),
    }


def _candidate_final_score(candidate: _HybridCandidate) -> float:
    return round(
        HYBRID_RETRIEVAL_WEIGHTS["embedding_score"] * candidate.embedding_score
        + HYBRID_RETRIEVAL_WEIGHTS["keyword_score"] * candidate.keyword_score
        + HYBRID_RETRIEVAL_WEIGHTS["glossary_score"] * candidate.glossary_score
        + HYBRID_RETRIEVAL_WEIGHTS["requirement_type"]
        * _requirement_type_score(candidate),
        6,
    )


def _requirement_type_score(candidate: _HybridCandidate) -> float:
    return 1.0 if candidate.glossary_matches else 0.0


def _match_regulatory_glossary(text: str) -> tuple[Any, ...]:
    from bidded.evidence.regulatory_glossary import match_regulatory_glossary

    return tuple(match_regulatory_glossary(text))


def _query_relevant_glossary_matches(
    matches: Sequence[Any],
    query: str,
) -> tuple[Any, ...]:
    query_terms = set(_tokens(query))
    return tuple(
        match
        for match in matches
        if query_terms & set(_tokens(_glossary_relevance_text(match)))
    )


def _glossary_relevance_text(match: Any) -> str:
    return " ".join(
        [
            str(match.display_label),
            str(match.requirement_type),
            " ".join(match.matched_patterns),
        ]
    )


def _glossary_score(matches: Sequence[Any]) -> float:
    matched_pattern_count = sum(
        len(getattr(match, "matched_patterns", ())) for match in matches
    )
    if matched_pattern_count <= 0:
        return 0.0
    return round(min(1.0, matched_pattern_count / 3), 6)


def _glossary_matches_metadata(matches: Sequence[Any]) -> list[dict[str, Any]]:
    return [
        {
            "entry_id": str(match.entry_id),
            "requirement_type": str(match.requirement_type),
            "display_label": str(match.display_label),
            "matched_patterns": list(match.matched_patterns),
        }
        for match in matches
    ]


def _row_chunk_id(row: Mapping[str, Any]) -> str:
    row_id = row.get("id", row.get("chunk_id"))
    return str(row_id or "")


def _normalized_rpc_row(row: Mapping[str, Any]) -> dict[str, Any]:
    normalized_row = dict(row)
    if "chunk_id" in normalized_row and "id" not in normalized_row:
        normalized_row["id"] = normalized_row["chunk_id"]
    if "chunk_document_id" in normalized_row and "document_id" not in normalized_row:
        normalized_row["document_id"] = normalized_row["chunk_document_id"]
    return normalized_row


def _clamped_score(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 6)


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
    retrieval_metadata: Mapping[str, Any],
) -> RetrievedDocumentChunk:
    metadata = _metadata(row.get("metadata"))
    metadata["retrieval"] = dict(retrieval_metadata)
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

    unique_query_terms = set(query_terms)
    coverage = len(unique_query_terms & set(text_terms)) / len(unique_query_terms)
    match_density = min(1.0, matched_terms / max(1, len(query_terms)))
    phrase_boost = 1.0 if " ".join(query_terms) in " ".join(_tokens(text)) else 0.0
    return round(
        min(1.0, (0.65 * coverage) + (0.25 * match_density) + (0.10 * phrase_boost)),
        6,
    )


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


def _similarity_score(value: object) -> float:
    try:
        return round(float(str(value)), 6)
    except (TypeError, ValueError) as exc:
        raise RetrievalError("pgvector similarity score is invalid.") from exc


__all__ = [
    "EmbeddingAdapter",
    "HYBRID_RETRIEVAL_WEIGHTS",
    "MockEmbeddingAdapter",
    "RetrievedDocumentChunk",
    "RetrievalError",
    "list_document_chunks_for_document",
    "rank_document_chunk_rows",
    "retrieve_document_chunks",
]
