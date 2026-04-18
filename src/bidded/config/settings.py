from __future__ import annotations

from typing import Literal, Self

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from bidded.embeddings import (
    DEFAULT_EMBEDDING_MODE,
    DEFAULT_LIVE_EMBEDDING_MODEL,
    DEFAULT_LIVE_EMBEDDING_PROVIDER,
    DOCUMENT_CHUNK_EMBEDDING_DIMENSIONS,
    validate_embedding_contract,
)

EmbeddingMode = Literal["disabled", "live", "mock"]


class BiddedSettings(BaseSettings):
    """Runtime settings loaded from environment variables or a local .env file."""

    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    supabase_url: str | None = None
    supabase_service_role_key: str | None = None
    supabase_storage_bucket: str = "public-procurements"
    embedding_provider: str = DEFAULT_LIVE_EMBEDDING_PROVIDER
    embedding_model: str = DEFAULT_LIVE_EMBEDDING_MODEL
    embedding_dimensions: int = DOCUMENT_CHUNK_EMBEDDING_DIMENSIONS
    embedding_mode: EmbeddingMode = DEFAULT_EMBEDDING_MODE

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("embedding_mode", mode="before")
    @classmethod
    def _normalize_embedding_mode(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("embedding_provider", "embedding_model", mode="before")
    @classmethod
    def _normalize_embedding_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @model_validator(mode="after")
    def _validate_embedding_contract(self) -> Self:
        validate_embedding_contract(
            provider=self.embedding_provider,
            model=self.embedding_model,
            dimensions=self.embedding_dimensions,
            mode=self.embedding_mode,
            openai_api_key=self.openai_api_key,
        )
        return self


def load_settings() -> BiddedSettings:
    return BiddedSettings()
