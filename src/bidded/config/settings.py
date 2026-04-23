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
SwarmBackend = Literal["auto", "anthropic", "evidence_locked"]
AnthropicModelRouting = Literal["mixed", "single"]

_DEFAULT_MESSAGES_MODEL = "claude-sonnet-4-6"
_DEFAULT_FAST_MODEL = "claude-haiku-4-5"
_KNOWN_INVALID_ANTHROPIC_MODELS: dict[str, str] = {
    "claude-sonnet-4-20250514": _DEFAULT_MESSAGES_MODEL,
    "claude-3-5-sonnet-20241022": _DEFAULT_MESSAGES_MODEL,
}


class BiddedSettings(BaseSettings):
    """Runtime settings loaded from environment variables or a local .env file."""

    anthropic_api_key: str | None = None
    bidded_swarm_backend: SwarmBackend = "auto"
    bidded_anthropic_model: str = _DEFAULT_MESSAGES_MODEL
    bidded_anthropic_fast_model: str = _DEFAULT_FAST_MODEL
    bidded_anthropic_reasoning_model: str | None = None
    bidded_anthropic_model_routing: AnthropicModelRouting = "mixed"
    openai_api_key: str | None = None
    supabase_url: str | None = None
    supabase_service_role_key: str | None = None
    supabase_jwt_secret: str | None = None
    supabase_storage_bucket: str = "public-procurements"
    company_kb_storage_bucket: str = "company-knowledge"
    embedding_provider: str = DEFAULT_LIVE_EMBEDDING_PROVIDER
    embedding_model: str = DEFAULT_LIVE_EMBEDDING_MODEL
    embedding_dimensions: int = DOCUMENT_CHUNK_EMBEDDING_DIMENSIONS
    embedding_mode: EmbeddingMode = DEFAULT_EMBEDDING_MODE

    model_config = SettingsConfigDict(env_file=(".env", ".env.local"), extra="ignore")

    @field_validator(
        "bidded_swarm_backend",
        "bidded_anthropic_model_routing",
        mode="before",
    )
    @classmethod
    def _normalize_lowercase_setting(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator(
        "bidded_anthropic_model",
        "bidded_anthropic_fast_model",
        "bidded_anthropic_reasoning_model",
        mode="before",
    )
    @classmethod
    def _normalize_anthropic_model(cls, value: object) -> object:
        if value is None:
            return value
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        return _KNOWN_INVALID_ANTHROPIC_MODELS.get(stripped, stripped)

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
        if not self.bidded_anthropic_reasoning_model:
            self.bidded_anthropic_reasoning_model = self.bidded_anthropic_model
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
