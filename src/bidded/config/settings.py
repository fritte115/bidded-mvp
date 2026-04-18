from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class BiddedSettings(BaseSettings):
    """Runtime settings loaded from environment variables or a local .env file."""

    anthropic_api_key: str | None = None
    #: ``evidence_locked`` (default, deterministic) or ``anthropic`` (Claude API).
    bidded_swarm_backend: str = "evidence_locked"
    anthropic_model: str = "claude-sonnet-4-20250514"
    supabase_url: str | None = None
    supabase_service_role_key: str | None = None
    supabase_storage_bucket: str = "public-procurements"
    embedding_provider: str = "mock"

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        extra="ignore",
    )


def load_settings() -> BiddedSettings:
    return BiddedSettings()
