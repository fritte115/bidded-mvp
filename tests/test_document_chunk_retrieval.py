from __future__ import annotations

from typing import Any
from uuid import UUID

from bidded.embeddings import (
    DOCUMENT_CHUNK_EMBEDDING_DIMENSIONS,
    EMBEDDING_CONTRACT_VERSION,
)
from bidded.retrieval import (
    HYBRID_RETRIEVAL_WEIGHTS,
    MockEmbeddingAdapter,
    retrieve_document_chunks,
)

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


class RecordingRpcQuery:
    def __init__(
        self,
        client: RecordingSupabaseClient,
        function_name: str,
        params: dict[str, Any],
    ) -> None:
        self.client = client
        self.function_name = function_name
        self.params = params

    def execute(self) -> object:
        self.client.rpcs.append((self.function_name, self.params))
        if self.client.rpc_error is not None:
            raise self.client.rpc_error
        return type("Response", (), {"data": self.client.rpc_rows})()


class RecordingSupabaseClient:
    def __init__(
        self,
        chunks: list[dict[str, Any]],
        *,
        rpc_rows: list[dict[str, Any]] | None = None,
        rpc_error: Exception | None = None,
    ) -> None:
        self.rows = {"document_chunks": chunks}
        self.rpc_rows = list(rpc_rows or [])
        self.rpc_error = rpc_error
        self.selects: list[tuple[str, str | None]] = []
        self.rpcs: list[tuple[str, dict[str, Any]]] = []
        self.table_names: list[str] = []

    def table(self, table_name: str) -> RecordingQuery:
        self.table_names.append(table_name)
        return RecordingQuery(self, table_name)

    def rpc(self, function_name: str, params: dict[str, Any]) -> RecordingRpcQuery:
        return RecordingRpcQuery(self, function_name, params)


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


def _assert_final_score_uses_hybrid_weights(retrieval: dict[str, Any]) -> None:
    assert retrieval["final_score"] == round(
        HYBRID_RETRIEVAL_WEIGHTS["embedding_score"] * retrieval["embedding_score"]
        + HYBRID_RETRIEVAL_WEIGHTS["keyword_score"] * retrieval["keyword_score"]
        + HYBRID_RETRIEVAL_WEIGHTS["glossary_score"] * retrieval["glossary_score"]
        + HYBRID_RETRIEVAL_WEIGHTS["requirement_type"]
        * retrieval["requirement_type_score"],
        6,
    )
    assert retrieval["score"] == retrieval["final_score"]


class RecordingLiveEmbeddingAdapter:
    name = "openai_embedding"
    dimensions = DOCUMENT_CHUNK_EMBEDDING_DIMENSIONS
    mode = "live"

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.vector = [0.0 for _ in range(self.dimensions)]
        self.vector[0] = 1.0

    def embed_text(self, text: str) -> list[float]:
        self.calls.append(text)
        return self.vector


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
    retrieval = results[0].metadata["retrieval"]
    assert retrieval["method"] == "hybrid"
    assert retrieval["keyword_score"] > 0
    assert retrieval["embedding_score"] == 0
    assert "keyword" in retrieval["candidate_methods"]
    _assert_final_score_uses_hybrid_weights(retrieval)
    assert client.table_names == ["document_chunks"]


def test_retrieve_document_chunks_returns_hybrid_keyword_glossary_metadata() -> None:
    client = RecordingSupabaseClient(
        [
            _chunk(
                id="chunk-submission",
                chunk_index=0,
                text="Submission must include a signed data processing agreement.",
            )
        ]
    )

    results = retrieve_document_chunks(
        client,
        query="submission documents signed data processing agreement",
        document_id=DOCUMENT_ID,
        top_k=1,
    )

    assert [result.chunk_id for result in results] == ["chunk-submission"]
    retrieval = results[0].metadata["retrieval"]
    assert retrieval["method"] == "hybrid"
    assert retrieval["weights"] == HYBRID_RETRIEVAL_WEIGHTS
    assert retrieval["keyword_score"] > 0
    assert retrieval["embedding_score"] == 0
    assert retrieval["glossary_score"] > 0
    assert retrieval["glossary_matches"][0]["entry_id"] == "submission_documents"
    _assert_final_score_uses_hybrid_weights(retrieval)


def test_retrieve_document_chunks_returns_glossary_only_candidates() -> None:
    client = RecordingSupabaseClient(
        [
            _chunk(
                id="chunk-swedish-submission",
                chunk_index=0,
                text="Anbudet ska innehålla undertecknad bilaga.",
            ),
            _chunk(
                id="chunk-unrelated",
                chunk_index=1,
                text="The implementation starts with a planning workshop.",
            ),
        ]
    )

    results = retrieve_document_chunks(
        client,
        query="submission documents",
        document_id=DOCUMENT_ID,
        top_k=1,
    )

    assert [result.chunk_id for result in results] == ["chunk-swedish-submission"]
    retrieval = results[0].metadata["retrieval"]
    assert retrieval["method"] == "hybrid"
    assert retrieval["keyword_score"] == 0
    assert retrieval["embedding_score"] == 0
    assert retrieval["glossary_score"] > 0
    assert retrieval["requirement_type_score"] == 1.0
    assert retrieval["candidate_methods"] == ["glossary"]
    assert retrieval["glossary_matches"][0]["entry_id"] == "submission_documents"
    _assert_final_score_uses_hybrid_weights(retrieval)


def test_retrieve_document_chunks_returns_embedding_only_candidates() -> None:
    embedding_adapter = MockEmbeddingAdapter(dimensions=24)
    client = RecordingSupabaseClient(
        [
            _chunk(
                id="chunk-embedded",
                chunk_index=0,
                text="Transition planning and onboarding approach.",
                embedding=embedding_adapter.embed_text("security certification"),
            ),
            _chunk(
                id="chunk-unrelated",
                chunk_index=1,
                text="The kickoff workshop agenda is attached.",
                embedding=embedding_adapter.embed_text("commercial pricing"),
            ),
        ]
    )

    results = retrieve_document_chunks(
        client,
        query="security certification",
        document_id=DOCUMENT_ID,
        top_k=1,
        embedding_adapter=embedding_adapter,
    )

    assert [result.chunk_id for result in results] == ["chunk-embedded"]
    retrieval = results[0].metadata["retrieval"]
    assert retrieval["method"] == "hybrid"
    assert retrieval["embedding_score"] == 1.0
    assert retrieval["keyword_score"] == 0
    assert retrieval["glossary_score"] == 0
    assert retrieval["candidate_methods"] == ["embedding"]
    _assert_final_score_uses_hybrid_weights(retrieval)


def test_retrieve_document_chunks_merges_duplicate_hybrid_candidates() -> None:
    embedding_adapter = RecordingLiveEmbeddingAdapter()
    client = RecordingSupabaseClient(
        [
            _chunk(
                id="chunk-submission",
                chunk_index=0,
                text="Submission must include a signed data processing agreement.",
            )
        ],
        rpc_rows=[
            {
                "chunk_id": "chunk-submission",
                "chunk_document_id": str(DOCUMENT_ID),
                "page_start": 1,
                "page_end": 1,
                "chunk_index": 0,
                "text": "Submission must include a signed data processing agreement.",
                "metadata": {"source_label": "Tender.pdf"},
                "similarity": 0.8,
            }
        ],
    )

    results = retrieve_document_chunks(
        client,
        query="submission documents signed data processing agreement",
        document_id=DOCUMENT_ID,
        top_k=5,
        embedding_adapter=embedding_adapter,
    )

    assert [result.chunk_id for result in results] == ["chunk-submission"]
    retrieval = results[0].metadata["retrieval"]
    assert retrieval["candidate_methods"] == ["embedding", "glossary", "keyword"]
    assert retrieval["embedding_score"] == 0.8
    assert retrieval["keyword_score"] > 0
    assert retrieval["glossary_score"] > 0
    _assert_final_score_uses_hybrid_weights(retrieval)


def test_retrieve_document_chunks_uses_deterministic_tie_breaks() -> None:
    client = RecordingSupabaseClient(
        [
            _chunk(
                id="chunk-z",
                chunk_index=2,
                text="Supplier support desk.",
            ),
            _chunk(
                id="chunk-b",
                chunk_index=1,
                text="Supplier support desk.",
            ),
            _chunk(
                id="chunk-a",
                chunk_index=1,
                text="Supplier support desk.",
            ),
        ]
    )

    results = retrieve_document_chunks(
        client,
        query="supplier support",
        document_id=DOCUMENT_ID,
        top_k=3,
    )

    assert [result.chunk_id for result in results] == [
        "chunk-a",
        "chunk-b",
        "chunk-z",
    ]


def test_retrieve_document_chunks_calls_rpc_for_live_embeddings() -> None:
    embedding_adapter = RecordingLiveEmbeddingAdapter()
    client = RecordingSupabaseClient(
        [],
        rpc_rows=[
            {
                "chunk_id": "chunk-security",
                "chunk_document_id": str(DOCUMENT_ID),
                "page_start": 4,
                "page_end": 4,
                "chunk_index": 0,
                "text": "Information security requirements include ISO 27001.",
                "metadata": {"source_label": "Tender.pdf"},
                "similarity": 0.917423,
            }
        ],
    )

    results = retrieve_document_chunks(
        client,
        query="ISO 27001 information security",
        document_id=DOCUMENT_ID,
        top_k=1,
        tenant_key="demo",
        embedding_adapter=embedding_adapter,
        match_threshold=0.25,
    )

    assert [result.chunk_id for result in results] == ["chunk-security"]
    assert results[0].document_id == DOCUMENT_ID
    retrieval = results[0].metadata["retrieval"]
    assert retrieval["method"] == "hybrid"
    assert retrieval["embedding_score"] == 0.917423
    assert retrieval["keyword_score"] == 0
    assert retrieval["glossary_score"] == 0
    assert retrieval["candidate_methods"] == ["embedding"]
    _assert_final_score_uses_hybrid_weights(retrieval)
    assert embedding_adapter.calls == ["ISO 27001 information security"]
    assert client.table_names == ["document_chunks"]

    assert len(client.rpcs) == 1
    function_name, params = client.rpcs[0]
    assert function_name == "match_document_chunks"
    assert params["query_embedding"] == embedding_adapter.vector
    assert params["match_count"] == 1
    assert params["match_threshold"] == 0.25
    assert params["tenant_key"] == "demo"
    assert params["document_id"] == str(DOCUMENT_ID)


def test_retrieve_document_chunks_falls_back_when_live_rpc_unavailable() -> None:
    embedding_adapter = RecordingLiveEmbeddingAdapter()
    client = RecordingSupabaseClient(
        [
            _chunk(
                id="chunk-keyword",
                text="Supplier must provide ISO 27001 certification.",
            ),
            _chunk(
                id="chunk-other",
                text="The project begins with onboarding workshops.",
            ),
        ],
        rpc_error=RuntimeError("match_document_chunks unavailable"),
    )

    results = retrieve_document_chunks(
        client,
        query="ISO 27001 certification",
        document_id=DOCUMENT_ID,
        top_k=1,
        embedding_adapter=embedding_adapter,
    )

    assert [result.chunk_id for result in results] == ["chunk-keyword"]
    retrieval = results[0].metadata["retrieval"]
    assert retrieval["method"] == "hybrid"
    assert retrieval["keyword_score"] > 0
    assert retrieval["embedding_score"] == 0
    _assert_final_score_uses_hybrid_weights(retrieval)
    assert client.rpcs[0][0] == "match_document_chunks"
    assert client.table_names == ["document_chunks"]


def test_retrieve_document_chunks_falls_back_when_rpc_has_no_embeddings() -> None:
    embedding_adapter = RecordingLiveEmbeddingAdapter()
    client = RecordingSupabaseClient(
        [
            _chunk(
                id="chunk-keyword",
                text="Supplier must provide ISO 27001 certification.",
                embedding=None,
            )
        ],
        rpc_rows=[],
    )

    results = retrieve_document_chunks(
        client,
        query="ISO 27001 certification",
        document_id=DOCUMENT_ID,
        top_k=1,
        embedding_adapter=embedding_adapter,
    )

    assert [result.chunk_id for result in results] == ["chunk-keyword"]
    retrieval = results[0].metadata["retrieval"]
    assert retrieval["method"] == "hybrid"
    assert retrieval["keyword_score"] > 0
    assert retrieval["embedding_score"] == 0
    _assert_final_score_uses_hybrid_weights(retrieval)
    assert client.rpcs[0][0] == "match_document_chunks"
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
    retrieval = results[0].metadata["retrieval"]
    assert retrieval["method"] == "hybrid"
    assert 0 < retrieval["embedding_score"] <= 1
    assert "embedding" in retrieval["candidate_methods"]
    _assert_final_score_uses_hybrid_weights(retrieval)


def test_mock_embedding_adapter_exposes_generation_metadata() -> None:
    embedding_adapter = MockEmbeddingAdapter()

    assert len(embedding_adapter.embed_text("ISO 27001 security")) == (
        DOCUMENT_CHUNK_EMBEDDING_DIMENSIONS
    )
    assert embedding_adapter.embedding_metadata() == {
        "provider": "openai",
        "model": "text-embedding-3-small",
        "dimensions": DOCUMENT_CHUNK_EMBEDDING_DIMENSIONS,
        "mode": "mock",
        "version": EMBEDDING_CONTRACT_VERSION,
    }
