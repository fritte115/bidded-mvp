from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Legacy / retired snapshot IDs → current Claude API id (see Anthropic models overview).
_DEFAULT_MESSAGES_MODEL = "claude-sonnet-4-6"
_KNOWN_INVALID_ANTHROPIC_MODELS: dict[str, str] = {
    "claude-sonnet-4-20250514": _DEFAULT_MESSAGES_MODEL,
    "claude-3-5-sonnet-20241022": _DEFAULT_MESSAGES_MODEL,
}


class BiddedSettings(BaseSettings):
    """Runtime settings loaded from environment variables or a local .env file."""

    anthropic_api_key: str | None = None
    #: ``evidence_locked`` (default, deterministic) or ``anthropic`` (Claude API).
    bidded_swarm_backend: str = "evidence_locked"
    #: Messages API model id. Env var: ``BIDDED_ANTHROPIC_MODEL`` only (not ``ANTHROPIC_MODEL``).
    bidded_anthropic_model: str = _DEFAULT_MESSAGES_MODEL
    supabase_url: str | None = None
    supabase_service_role_key: str | None = None
    supabase_storage_bucket: str = "public-procurements"
    embedding_provider: str = "mock"

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        extra="ignore",
    )

    @field_validator("bidded_anthropic_model", mode="after")
    @classmethod
    def _normalize_anthropic_model(cls, value: str) -> str:
        stripped = value.strip()
        return _KNOWN_INVALID_ANTHROPIC_MODELS.get(stripped, stripped)


def load_settings() -> BiddedSettings:
    return BiddedSettings()
