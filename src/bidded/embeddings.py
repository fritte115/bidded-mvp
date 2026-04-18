from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

DOCUMENT_CHUNK_EMBEDDING_DIMENSIONS = 1536
DEFAULT_LIVE_EMBEDDING_PROVIDER = "openai"
DEFAULT_LIVE_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_EMBEDDING_MODE = "mock"
EMBEDDING_CONTRACT_VERSION = "embedding_contract_v1"
SUPPORTED_EMBEDDING_MODES = frozenset({"disabled", "live", "mock"})

_KNOWN_MODEL_DIMENSIONS = {
    ("openai", "text-embedding-3-small"): 1536,
    ("openai", "text-embedding-3-large"): 3072,
}


class EmbeddingConfigurationError(ValueError):
    """Raised when embedding settings cannot produce comparable chunk vectors."""


class EmbeddingSettings(Protocol):
    embedding_provider: str
    embedding_model: str
    embedding_dimensions: int
    embedding_mode: str


@dataclass(frozen=True)
class EmbeddingContract:
    provider: str
    model: str
    dimensions: int
    mode: str
    version: str = EMBEDDING_CONTRACT_VERSION

    def metadata(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "dimensions": self.dimensions,
            "mode": self.mode,
            "version": self.version,
        }


def embedding_contract_from_settings(settings: EmbeddingSettings) -> EmbeddingContract:
    return EmbeddingContract(
        provider=_normalize_text(settings.embedding_provider, "EMBEDDING_PROVIDER"),
        model=_normalize_text(settings.embedding_model, "EMBEDDING_MODEL"),
        dimensions=int(settings.embedding_dimensions),
        mode=_normalize_text(settings.embedding_mode, "EMBEDDING_MODE"),
    )


def build_embedding_metadata(
    settings_or_contract: EmbeddingSettings | EmbeddingContract,
) -> dict[str, Any]:
    contract = (
        settings_or_contract
        if isinstance(settings_or_contract, EmbeddingContract)
        else embedding_contract_from_settings(settings_or_contract)
    )
    return contract.metadata()


def merge_embedding_metadata(
    metadata: Mapping[str, Any],
    settings_or_contract: EmbeddingSettings | EmbeddingContract,
) -> dict[str, Any]:
    merged = dict(metadata)
    merged["embedding"] = build_embedding_metadata(settings_or_contract)
    return merged


def validate_embedding_contract(
    *,
    provider: str,
    model: str,
    dimensions: int,
    mode: str,
    openai_api_key: str | None,
) -> None:
    normalized_provider = _normalize_text(provider, "EMBEDDING_PROVIDER")
    normalized_model = _normalize_text(model, "EMBEDDING_MODEL")
    normalized_mode = _normalize_text(mode, "EMBEDDING_MODE")

    if normalized_mode not in SUPPORTED_EMBEDDING_MODES:
        raise EmbeddingConfigurationError(
            "EMBEDDING_MODE must be one of disabled, live, or mock."
        )

    if dimensions != DOCUMENT_CHUNK_EMBEDDING_DIMENSIONS:
        raise EmbeddingConfigurationError(
            "EMBEDDING_DIMENSIONS must match document_chunks.embedding "
            f"vector({DOCUMENT_CHUNK_EMBEDDING_DIMENSIONS}); got {dimensions}."
        )

    model_dimensions = _KNOWN_MODEL_DIMENSIONS.get(
        (normalized_provider, normalized_model)
    )
    if model_dimensions is not None and model_dimensions != dimensions:
        raise EmbeddingConfigurationError(
            f"Embedding model {normalized_provider}/{normalized_model} has "
            f"{model_dimensions} dimensions, but document_chunks.embedding "
            f"vector({DOCUMENT_CHUNK_EMBEDDING_DIMENSIONS}) requires "
            f"{DOCUMENT_CHUNK_EMBEDDING_DIMENSIONS}."
        )

    if normalized_mode != "live":
        return

    if model_dimensions is None:
        raise EmbeddingConfigurationError(
            "Unsupported live embedding provider/model: "
            f"{normalized_provider}/{normalized_model}."
        )

    if normalized_provider == "openai" and not _has_value(openai_api_key):
        raise EmbeddingConfigurationError(
            "OPENAI_API_KEY is required when EMBEDDING_MODE=live and "
            "EMBEDDING_PROVIDER=openai."
        )


def _normalize_text(value: object, field_name: str) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        raise EmbeddingConfigurationError(f"{field_name} must not be empty.")
    return normalized


def _has_value(value: str | None) -> bool:
    return isinstance(value, str) and bool(value.strip())


__all__ = [
    "DEFAULT_EMBEDDING_MODE",
    "DEFAULT_LIVE_EMBEDDING_MODEL",
    "DEFAULT_LIVE_EMBEDDING_PROVIDER",
    "DOCUMENT_CHUNK_EMBEDDING_DIMENSIONS",
    "EMBEDDING_CONTRACT_VERSION",
    "EmbeddingConfigurationError",
    "EmbeddingContract",
    "EmbeddingSettings",
    "SUPPORTED_EMBEDDING_MODES",
    "build_embedding_metadata",
    "embedding_contract_from_settings",
    "merge_embedding_metadata",
    "validate_embedding_contract",
]
