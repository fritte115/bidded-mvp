from __future__ import annotations

from typing import Any
from uuid import UUID

from bidded.retrieval import MockEmbeddingAdapter, retrieve_document_chunks

DOCUMENT_ID = UUID("55555555-5555-4555-8555-555555555555")


class RecordingQuery:
    def __init__(self, client: RecordingSupabaseClient, table_name: str) -> None:
        self.client = client
        self.table_name = table_name
        self.filters: list[tuple[str, str]] = []
        self.selected_columns: str | None = None

    def select(self, columns: str) -> RecordingQuery:
        self.selected_columns = columns
        return self

    def eq(self, column: str, value: object) -> RecordingQuery:
        self.filters.append((column, str(value)))
        return self

    def execute(self) -> object:
        self.client.selects.append((self.table_name, self.selected_columns))
        rows = self.client.rows.get(self.table_name, [])
        filtered = [
            row
            for row in rows
            if all(str(row.get(column)) == value for column, value in self.filters)
        ]
        return type("Response", (), {"data": filtered})()


class RecordingSupabaseClient:
    def __init__(self, chunks: list[dict[str, Any]]) -> None:
        self.rows = {"document_chunks": chunks}
        self.selects: list[tuple[str, str | None]] = []
        self.table_names: list[str] = []

    def table(self, table_name: str) -> RecordingQuery:
        self.table_names.append(table_name)
        return RecordingQuery(self, table_name)


def _chunk(**overrides: Any) -> dict[str, Any]:
    row = {
        "id": "chunk-default",
        "tenant_key": "demo",
        "document_id": str(DOCUMENT_ID),
        "page_start": 1,
        "page_end": 1,
        "chunk_index": 0,
        "text": "General procurement introduction with no technical requirement.",
        "metadata": {"source_label": "Tender.pdf"},
        "embedding": None,
    }
    row.update(overrides)
    return row


def test_retrieve_document_chunks_uses_keyword_fallback_without_embeddings() -> None:
    client = RecordingSupabaseClient(
        [
            _chunk(
                id="chunk-1",
                chunk_index=0,
                text="Supplier must provide ISO 27001 certification for the service.",
                page_start=3,
                page_end=3,
            ),
            _chunk(
                id="chunk-2",
                chunk_index=1,
                text="The agreement starts with a kickoff workshop.",
                page_start=8,
                page_end=8,
            ),
        ]
    )

    results = retrieve_document_chunks(
        client,
        query="ISO 27001 certification",
        document_id=DOCUMENT_ID,
        top_k=1,
    )

    assert [result.chunk_id for result in results] == ["chunk-1"]
    assert results[0].document_id == DOCUMENT_ID
    assert results[0].page_start == 3
    assert results[0].page_end == 3
    assert results[0].metadata["source_label"] == "Tender.pdf"
    assert results[0].metadata["retrieval"]["method"] == "keyword"
    assert results[0].metadata["retrieval"]["score"] > 0
    assert client.table_names == ["document_chunks"]


def test_retrieve_document_chunks_uses_mock_embedding_scores_when_configured() -> None:
    embedding_adapter = MockEmbeddingAdapter(dimensions=24)
    client = RecordingSupabaseClient(
        [
            _chunk(
                id="chunk-security",
                chunk_index=0,
                text="Information security requirements include ISO 27001 controls.",
                embedding=embedding_adapter.embed_text(
                    "Information security requirements include ISO 27001 controls."
                ),
                page_start=4,
                page_end=4,
            ),
            _chunk(
                id="chunk-commercial",
                chunk_index=1,
                text="The price schedule must include hourly consultant rates.",
                embedding=embedding_adapter.embed_text(
                    "The price schedule must include hourly consultant rates."
                ),
                page_start=9,
                page_end=9,
            ),
        ]
    )

    assert embedding_adapter.embed_text("ISO 27001 security") == (
        embedding_adapter.embed_text("ISO 27001 security")
    )

    results = retrieve_document_chunks(
        client,
        query="ISO 27001 information security",
        document_id=DOCUMENT_ID,
        top_k=1,
        embedding_adapter=embedding_adapter,
    )

    assert [result.chunk_id for result in results] == ["chunk-security"]
    assert results[0].page_start == 4
    assert results[0].metadata["retrieval"]["method"] == "mock_embedding"
    assert 0 < results[0].metadata["retrieval"]["score"] <= 1
