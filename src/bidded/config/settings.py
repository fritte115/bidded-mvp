from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class BiddedSettings(BaseSettings):
    """Runtime settings loaded from environment variables or a local .env file."""

    anthropic_api_key: str | None = None
    #: ``evidence_locked`` (default, deterministic) or ``anthropic`` (Claude API).
    bidded_swarm_backend: str = "evidence_locked"
    #: Model id for Messages API; must exist for your Anthropic account.
    anthropic_model: str = "claude-3-5-sonnet-20241022"
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
