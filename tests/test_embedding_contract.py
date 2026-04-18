from __future__ import annotations

import pytest
from pydantic import ValidationError

from bidded.config import BiddedSettings
from bidded.embeddings import (
    DOCUMENT_CHUNK_EMBEDDING_DIMENSIONS,
    EMBEDDING_CONTRACT_VERSION,
    OpenAIEmbeddingAdapter,
    build_embedding_metadata,
    embedding_adapter_from_settings,
)


def _settings(**overrides: object) -> BiddedSettings:
    values = {
        "embedding_mode": "mock",
        "embedding_provider": "openai",
        "embedding_model": "text-embedding-3-small",
        "embedding_dimensions": DOCUMENT_CHUNK_EMBEDDING_DIMENSIONS,
        **overrides,
    }
    return BiddedSettings(_env_file=None, **values)


def test_settings_expose_default_embedding_contract() -> None:
    settings = BiddedSettings(_env_file=None)

    assert settings.embedding_mode == "mock"
    assert settings.embedding_provider == "openai"
    assert settings.embedding_model == "text-embedding-3-small"
    assert settings.embedding_dimensions == DOCUMENT_CHUNK_EMBEDDING_DIMENSIONS


def test_live_embedding_contract_accepts_matching_openai_dimensions() -> None:
    settings = _settings(
        embedding_mode="live",
        openai_api_key="test-openai-key",
    )

    assert settings.embedding_provider == "openai"
    assert settings.embedding_model == "text-embedding-3-small"
    assert settings.embedding_dimensions == 1536


def test_embedding_contract_rejects_dimension_mismatch() -> None:
    with pytest.raises(
        ValidationError,
        match="document_chunks.embedding vector\\(1536\\)",
    ):
        _settings(embedding_dimensions=384)


def test_embedding_contract_rejects_known_model_with_different_dimensions() -> None:
    with pytest.raises(ValidationError, match="text-embedding-3-large"):
        _settings(
            embedding_mode="live",
            embedding_model="text-embedding-3-large",
            openai_api_key="test-openai-key",
        )


def test_live_embedding_contract_requires_openai_credentials() -> None:
    with pytest.raises(ValidationError, match="OPENAI_API_KEY"):
        _settings(embedding_mode="live", openai_api_key=None)


def test_disabled_embedding_contract_does_not_require_credentials() -> None:
    settings = _settings(embedding_mode="disabled", openai_api_key=None)

    assert settings.embedding_mode == "disabled"


def test_embedding_metadata_records_provider_model_dimensions_and_version() -> None:
    settings = _settings()

    metadata = build_embedding_metadata(settings)

    assert metadata == {
        "provider": "openai",
        "model": "text-embedding-3-small",
        "dimensions": 1536,
        "mode": "mock",
        "version": EMBEDDING_CONTRACT_VERSION,
    }


def test_embedding_adapter_factory_defaults_to_deterministic_mock() -> None:
    adapter = embedding_adapter_from_settings(_settings())

    assert adapter is not None
    assert adapter.embedding_metadata() == {
        "provider": "openai",
        "model": "text-embedding-3-small",
        "dimensions": DOCUMENT_CHUNK_EMBEDDING_DIMENSIONS,
        "mode": "mock",
        "version": EMBEDDING_CONTRACT_VERSION,
    }
    assert adapter.embed_text("ISO 27001 security") == adapter.embed_text(
        "ISO 27001 security"
    )


def test_openai_embedding_adapter_uses_injected_client_without_network() -> None:
    class FakeEmbeddings:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def create(self, **kwargs: object) -> object:
            self.calls.append(kwargs)
            vector = [0.0 for _ in range(DOCUMENT_CHUNK_EMBEDDING_DIMENSIONS)]
            vector[0] = 1.0
            return type(
                "EmbeddingResponse",
                (),
                {"data": [type("EmbeddingData", (), {"embedding": vector})()]},
            )()

    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.embeddings = FakeEmbeddings()

    client = FakeOpenAIClient()
    adapter = OpenAIEmbeddingAdapter(api_key="test-openai-key", client=client)

    embedding = adapter.embed_text("Supplier must provide ISO 27001 certification.")

    assert embedding[0] == 1.0
    assert len(embedding) == DOCUMENT_CHUNK_EMBEDDING_DIMENSIONS
    assert client.embeddings.calls == [
        {
            "model": "text-embedding-3-small",
            "input": "Supplier must provide ISO 27001 certification.",
        }
    ]
    assert adapter.embedding_metadata()["mode"] == "live"
