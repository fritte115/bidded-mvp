from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from bidded.embeddings import DOCUMENT_CHUNK_EMBEDDING_DIMENSIONS, TextEmbeddingAdapter

DEMO_TENANT_KEY = "demo"


class ChunkEmbeddingError(RuntimeError):
    """Raised when document chunk embeddings are required but cannot be generated."""


class SupabaseChunkEmbeddingQuery(Protocol):
    def select(self, columns: str) -> SupabaseChunkEmbeddingQuery: ...

    def eq(self, column: str, value: object) -> SupabaseChunkEmbeddingQuery: ...

    def update(self, payload: dict[str, Any]) -> SupabaseChunkEmbeddingQuery: ...

    def execute(self) -> Any: ...


class SupabaseChunkEmbeddingClient(Protocol):
    def table(self, table_name: str) -> SupabaseChunkEmbeddingQuery: ...


ChunkEmbeddingAdapter = TextEmbeddingAdapter


@dataclass(frozen=True)
class DocumentChunkEmbeddingResult:
    document_id: UUID
    status: str
    total_count: int
    embedded_count: int
    skipped_count: int
    failed_count: int
    embedding_metadata: dict[str, Any] | None = None
    error_message: str | None = None

    def parser_metadata(self) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "status": self.status,
            "total_count": self.total_count,
            "embedded_count": self.embedded_count,
            "skipped_count": self.skipped_count,
            "failed_count": self.failed_count,
        }
        if self.embedding_metadata is not None:
            metadata.update(self.embedding_metadata)
        if self.error_message is not None:
            metadata["error_message"] = self.error_message
        return metadata


def populate_document_chunk_embeddings(
    client: SupabaseChunkEmbeddingClient,
    *,
    document_id: UUID | str,
    embedding_adapter: ChunkEmbeddingAdapter,
    require_embeddings: bool = False,
    tenant_key: str = DEMO_TENANT_KEY,
) -> DocumentChunkEmbeddingResult:
    """Generate and store embeddings for chunks missing the current contract."""

    normalized_document_id = _normalize_uuid(document_id, "document_id")
    embedding_metadata = dict(embedding_adapter.embedding_metadata())
    _validate_adapter_contract(embedding_adapter, embedding_metadata)
    rows = _fetch_document_chunks(
        client,
        document_id=normalized_document_id,
        tenant_key=tenant_key,
    )
    skipped_rows = [
        row for row in rows if _has_current_embedding(row, embedding_metadata)
    ]
    pending_rows = [
        row for row in rows if not _has_current_embedding(row, embedding_metadata)
    ]

    try:
        updates = []
        for row in pending_rows:
            embedding = embedding_adapter.embed_text(str(row.get("text") or ""))
            _validate_embedding_vector(embedding, embedding_adapter)
            updates.append((row, embedding))
    except Exception as exc:
        if require_embeddings:
            raise ChunkEmbeddingError(
                f"Embedding generation failed for document {normalized_document_id}: "
                f"{exc}"
            ) from exc
        return DocumentChunkEmbeddingResult(
            document_id=normalized_document_id,
            status="keyword_fallback",
            total_count=len(rows),
            embedded_count=0,
            skipped_count=len(skipped_rows),
            failed_count=len(pending_rows),
            embedding_metadata=embedding_metadata,
            error_message=str(exc),
        )
    for row, embedding in updates:
        _update_chunk_embedding(
            client,
            row=row,
            tenant_key=tenant_key,
            embedding=embedding,
            embedding_metadata=embedding_metadata,
        )

    return DocumentChunkEmbeddingResult(
        document_id=normalized_document_id,
        status="embedded" if updates else "skipped",
        total_count=len(rows),
        embedded_count=len(updates),
        skipped_count=len(skipped_rows),
        failed_count=0,
        embedding_metadata=embedding_metadata,
    )


def _fetch_document_chunks(
    client: SupabaseChunkEmbeddingClient,
    *,
    document_id: UUID,
    tenant_key: str,
) -> list[dict[str, Any]]:
    response = (
        client.table("document_chunks")
        .select("id,tenant_key,document_id,chunk_index,text,metadata,embedding")
        .eq("tenant_key", tenant_key)
        .eq("document_id", str(document_id))
        .execute()
    )
    rows = _response_rows(response)
    return sorted(
        (dict(row) for row in rows),
        key=lambda row: (_int_value(row.get("chunk_index")), str(row.get("id"))),
    )


def _update_chunk_embedding(
    client: SupabaseChunkEmbeddingClient,
    *,
    row: Mapping[str, Any],
    tenant_key: str,
    embedding: list[float],
    embedding_metadata: dict[str, Any],
) -> None:
    chunk_id = str(row.get("id") or "")
    if not chunk_id:
        raise ChunkEmbeddingError("document_chunks.id must be present.")

    metadata = dict(_mapping(row.get("metadata")))
    metadata["embedding"] = dict(embedding_metadata)
    (
        client.table("document_chunks")
        .update({"embedding": embedding, "metadata": metadata})
        .eq("tenant_key", tenant_key)
        .eq("id", chunk_id)
        .execute()
    )


def _has_current_embedding(
    row: Mapping[str, Any],
    embedding_metadata: Mapping[str, Any],
) -> bool:
    stored_embedding = _stored_embedding_vector(row.get("embedding"))
    if stored_embedding is None or len(stored_embedding) != embedding_metadata.get(
        "dimensions"
    ):
        return False

    metadata = _mapping(row.get("metadata"))
    existing_embedding = _mapping(metadata.get("embedding"))
    return all(
        existing_embedding.get(key) == value
        for key, value in embedding_metadata.items()
    )


def _validate_adapter_contract(
    embedding_adapter: ChunkEmbeddingAdapter,
    embedding_metadata: Mapping[str, Any],
) -> None:
    if embedding_adapter.dimensions != DOCUMENT_CHUNK_EMBEDDING_DIMENSIONS:
        raise ChunkEmbeddingError(
            "Embedding adapter dimensions must match document_chunks.embedding "
            f"vector({DOCUMENT_CHUNK_EMBEDDING_DIMENSIONS})."
        )
    if embedding_metadata.get("dimensions") != DOCUMENT_CHUNK_EMBEDDING_DIMENSIONS:
        raise ChunkEmbeddingError(
            "Embedding metadata dimensions must match document_chunks.embedding "
            f"vector({DOCUMENT_CHUNK_EMBEDDING_DIMENSIONS})."
        )


def _validate_embedding_vector(
    embedding: Sequence[float],
    embedding_adapter: ChunkEmbeddingAdapter,
) -> None:
    if len(embedding) != embedding_adapter.dimensions:
        raise ChunkEmbeddingError(
            f"{embedding_adapter.name} returned {len(embedding)} dimensions; "
            f"expected {embedding_adapter.dimensions}."
        )


def _response_rows(response: Any) -> list[Mapping[str, Any]]:
    data = getattr(response, "data", None)
    if not isinstance(data, list):
        raise ChunkEmbeddingError(
            "Supabase document_chunks query did not return a list."
        )
    return [row for row in data if isinstance(row, Mapping)]


def _stored_embedding_vector(value: object) -> list[float] | None:
    if isinstance(value, str):
        stripped = value.strip().removeprefix("[").removesuffix("]")
        if not stripped:
            return None
        try:
            return [float(part.strip()) for part in stripped.split(",")]
        except ValueError:
            return None

    if isinstance(value, Sequence) and not isinstance(value, str):
        try:
            return [float(item) for item in value]
        except (TypeError, ValueError):
            return None

    return None


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _int_value(value: object) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError) as exc:
        raise ChunkEmbeddingError("document chunk integer field is invalid.") from exc


def _normalize_uuid(value: UUID | str, field_name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except ValueError as exc:
        raise ChunkEmbeddingError(f"{field_name} must be a UUID.") from exc


__all__ = [
    "ChunkEmbeddingAdapter",
    "ChunkEmbeddingError",
    "DocumentChunkEmbeddingResult",
    "SupabaseChunkEmbeddingClient",
    "populate_document_chunk_embeddings",
]
