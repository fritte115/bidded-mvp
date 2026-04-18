from __future__ import annotations

from typing import Any
from uuid import UUID

from bidded.documents import ChunkEmbeddingError
from bidded.embeddings import (
    DOCUMENT_CHUNK_EMBEDDING_DIMENSIONS,
    EMBEDDING_CONTRACT_VERSION,
)

DOCUMENT_ID = UUID("44444444-4444-4444-8444-444444444444")


class RecordingEmbeddingAdapter:
    name = "openai_embedding"
    dimensions = DOCUMENT_CHUNK_EMBEDDING_DIMENSIONS

    def __init__(self) -> None:
        self.calls: list[str] = []

    def embed_text(self, text: str) -> list[float]:
        self.calls.append(text)
        vector = [0.0 for _ in range(self.dimensions)]
        vector[0] = float(len(self.calls))
        return vector

    def embedding_metadata(self) -> dict[str, Any]:
        return {
            "provider": "openai",
            "model": "text-embedding-3-small",
            "dimensions": self.dimensions,
            "mode": "live",
            "version": EMBEDDING_CONTRACT_VERSION,
        }


class FailingEmbeddingAdapter(RecordingEmbeddingAdapter):
    def embed_text(self, text: str) -> list[float]:
        self.calls.append(text)
        raise RuntimeError("provider unavailable")


class RecordingQuery:
    def __init__(self, client: RecordingChunkClient, table_name: str) -> None:
        self.client = client
        self.table_name = table_name
        self.filters: list[tuple[str, str]] = []
        self.selected_columns: str | None = None
        self.update_payload: dict[str, Any] | None = None

    def select(self, columns: str) -> RecordingQuery:
        self.selected_columns = columns
        return self

    def eq(self, column: str, value: object) -> RecordingQuery:
        self.filters.append((column, str(value)))
        return self

    def update(self, payload: dict[str, Any]) -> RecordingQuery:
        self.update_payload = payload
        return self

    def execute(self) -> object:
        if self.update_payload is not None:
            self.client.updates.setdefault(self.table_name, []).append(
                (self.update_payload, self.filters)
            )
            rows = self._filtered_rows()
            for row in rows:
                row.update(self.update_payload)
            return type("Response", (), {"data": rows})()

        self.client.selects.append((self.table_name, self.selected_columns))
        return type("Response", (), {"data": self._filtered_rows()})()

    def _filtered_rows(self) -> list[dict[str, Any]]:
        rows = self.client.rows.get(self.table_name, [])
        return [
            row
            for row in rows
            if all(str(row.get(column)) == value for column, value in self.filters)
        ]


class RecordingChunkClient:
    def __init__(self, chunks: list[dict[str, Any]]) -> None:
        self.rows = {"document_chunks": chunks}
        self.selects: list[tuple[str, str | None]] = []
        self.updates: dict[str, list[tuple[dict[str, Any], list[tuple[str, str]]]]] = {}
        self.table_names: list[str] = []

    def table(self, table_name: str) -> RecordingQuery:
        self.table_names.append(table_name)
        return RecordingQuery(self, table_name)


def _chunk(**overrides: Any) -> dict[str, Any]:
    row = {
        "id": "chunk-missing",
        "tenant_key": "demo",
        "document_id": str(DOCUMENT_ID),
        "chunk_index": 0,
        "text": "Supplier must hold ISO 27001 certification.",
        "metadata": {"source_label": "Tender.pdf"},
        "embedding": None,
    }
    row.update(overrides)
    return row


def test_populate_embeddings_updates_missing_rows_and_skips_current() -> None:
    from bidded.documents import populate_document_chunk_embeddings

    adapter = RecordingEmbeddingAdapter()
    current_metadata = adapter.embedding_metadata()
    current_vector = [0.0 for _ in range(adapter.dimensions)]
    current_vector[3] = 1.0
    client = RecordingChunkClient(
        [
            _chunk(
                id="chunk-missing",
                chunk_index=0,
                text="Supplier must hold ISO 27001 certification.",
            ),
            _chunk(
                id="chunk-current",
                chunk_index=1,
                text="Delivery must start in September.",
                metadata={
                    "source_label": "Tender.pdf",
                    "embedding": current_metadata,
                },
                embedding=current_vector,
            ),
        ]
    )

    result = populate_document_chunk_embeddings(
        client,
        document_id=DOCUMENT_ID,
        embedding_adapter=adapter,
    )

    assert result.status == "embedded"
    assert result.total_count == 2
    assert result.embedded_count == 1
    assert result.skipped_count == 1
    assert result.failed_count == 0
    assert adapter.calls == ["Supplier must hold ISO 27001 certification."]

    update_payload, update_filters = client.updates["document_chunks"][0]
    assert ("id", "chunk-missing") in update_filters
    assert update_payload["embedding"][0] == 1.0
    assert update_payload["metadata"]["source_label"] == "Tender.pdf"
    assert update_payload["metadata"]["embedding"] == current_metadata
    assert client.rows["document_chunks"][1]["embedding"] == current_vector


def test_populate_document_chunk_embeddings_falls_back_when_generation_fails() -> None:
    from bidded.documents import populate_document_chunk_embeddings

    adapter = FailingEmbeddingAdapter()
    client = RecordingChunkClient(
        [
            _chunk(
                id="chunk-missing",
                text="Supplier must hold ISO 27001 certification.",
            ),
        ]
    )

    result = populate_document_chunk_embeddings(
        client,
        document_id=DOCUMENT_ID,
        embedding_adapter=adapter,
    )

    assert result.status == "keyword_fallback"
    assert result.embedded_count == 0
    assert result.skipped_count == 0
    assert result.failed_count == 1
    assert "provider unavailable" in str(result.error_message)
    assert client.updates == {}


def test_populate_embeddings_raises_when_required_generation_fails() -> None:
    from bidded.documents import populate_document_chunk_embeddings

    adapter = FailingEmbeddingAdapter()
    client = RecordingChunkClient([_chunk(id="chunk-missing")])

    try:
        populate_document_chunk_embeddings(
            client,
            document_id=DOCUMENT_ID,
            embedding_adapter=adapter,
            require_embeddings=True,
        )
    except ChunkEmbeddingError as exc:
        assert "provider unavailable" in str(exc)
    else:
        raise AssertionError("required embeddings should fail when generation fails")
