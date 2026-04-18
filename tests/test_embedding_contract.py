from __future__ import annotations

import pytest
from pydantic import ValidationError

from bidded.config import BiddedSettings
from bidded.embeddings import (
    DOCUMENT_CHUNK_EMBEDDING_DIMENSIONS,
    EMBEDDING_CONTRACT_VERSION,
    build_embedding_metadata,
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
