from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from math import sqrt
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


class EmbeddingGenerationError(RuntimeError):
    """Raised when an embedding adapter returns an unusable vector."""


class EmbeddingSettings(Protocol):
    embedding_provider: str
    embedding_model: str
    embedding_dimensions: int
    embedding_mode: str
    openai_api_key: str | None


class TextEmbeddingAdapter(Protocol):
    name: str
    dimensions: int

    def embed_text(self, text: str) -> list[float]: ...

    def embedding_metadata(self) -> dict[str, Any]: ...


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


@dataclass(frozen=True)
class MockEmbeddingAdapter:
    dimensions: int = DOCUMENT_CHUNK_EMBEDDING_DIMENSIONS
    name: str = "mock_embedding"
    provider: str = DEFAULT_LIVE_EMBEDDING_PROVIDER
    model: str = DEFAULT_LIVE_EMBEDDING_MODEL
    mode: str = DEFAULT_EMBEDDING_MODE
    version: str = EMBEDDING_CONTRACT_VERSION

    def embed_text(self, text: str) -> list[float]:
        """Create deterministic token vectors without a hosted embedding service."""

        if self.dimensions <= 0:
            raise EmbeddingGenerationError(
                "embedding dimensions must be greater than zero."
            )

        vector = [0.0 for _ in range(self.dimensions)]
        for token, count in Counter(_tokens(text)).items():
            digest = sha256(token.encode("utf-8")).digest()
            vector_index = int.from_bytes(digest[:4], byteorder="big") % (
                self.dimensions
            )
            vector[vector_index] += float(count)
        return _normalize_vector(vector)

    def embedding_metadata(self) -> dict[str, Any]:
        return build_embedding_metadata(
            EmbeddingContract(
                provider=self.provider,
                model=self.model,
                dimensions=self.dimensions,
                mode=self.mode,
                version=self.version,
            )
        )


@dataclass(frozen=True)
class OpenAIEmbeddingAdapter:
    api_key: str
    model: str = DEFAULT_LIVE_EMBEDDING_MODEL
    dimensions: int = DOCUMENT_CHUNK_EMBEDDING_DIMENSIONS
    provider: str = DEFAULT_LIVE_EMBEDDING_PROVIDER
    name: str = "openai_embedding"
    mode: str = "live"
    version: str = EMBEDDING_CONTRACT_VERSION
    client: Any | None = None

    def embed_text(self, text: str) -> list[float]:
        normalized_text = str(text or "").strip()
        if not normalized_text:
            raise EmbeddingGenerationError("embedding text must not be empty.")

        client = self.client or self._create_openai_client()
        response = client.embeddings.create(
            model=self.model,
            input=normalized_text,
        )
        embedding = _response_embedding(response)
        if len(embedding) != self.dimensions:
            raise EmbeddingGenerationError(
                f"{self.name} returned {len(embedding)} dimensions; "
                f"expected {self.dimensions}."
            )
        return embedding

    def embedding_metadata(self) -> dict[str, Any]:
        return build_embedding_metadata(
            EmbeddingContract(
                provider=self.provider,
                model=self.model,
                dimensions=self.dimensions,
                mode=self.mode,
                version=self.version,
            )
        )

    def _create_openai_client(self) -> Any:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - optional dependency path
            raise EmbeddingConfigurationError(
                "Install bidded[embeddings] to use EMBEDDING_MODE=live."
            ) from exc
        return OpenAI(api_key=self.api_key)


def embedding_contract_from_settings(settings: EmbeddingSettings) -> EmbeddingContract:
    return EmbeddingContract(
        provider=_normalize_text(settings.embedding_provider, "EMBEDDING_PROVIDER"),
        model=_normalize_text(settings.embedding_model, "EMBEDDING_MODEL"),
        dimensions=int(settings.embedding_dimensions),
        mode=_normalize_text(settings.embedding_mode, "EMBEDDING_MODE"),
    )


def embedding_adapter_from_settings(
    settings: EmbeddingSettings,
    *,
    openai_client: Any | None = None,
) -> TextEmbeddingAdapter | None:
    contract = embedding_contract_from_settings(settings)
    if contract.mode == "disabled":
        return None
    if contract.mode == "mock":
        return MockEmbeddingAdapter(
            provider=contract.provider,
            model=contract.model,
            dimensions=contract.dimensions,
            mode=contract.mode,
            version=contract.version,
        )
    if contract.provider == "openai" and contract.mode == "live":
        return OpenAIEmbeddingAdapter(
            api_key=str(settings.openai_api_key or ""),
            provider=contract.provider,
            model=contract.model,
            dimensions=contract.dimensions,
            mode=contract.mode,
            version=contract.version,
            client=openai_client,
        )
    raise EmbeddingConfigurationError(
        f"Unsupported embedding adapter: {contract.provider}/{contract.mode}."
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


def _tokens(text: str) -> list[str]:
    import re

    return re.findall(r"[a-z0-9]+", text.lower())


def _normalize_vector(vector: list[float]) -> list[float]:
    norm = sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def _response_embedding(response: Any) -> list[float]:
    data = _get_value(response, "data")
    if not isinstance(data, list) or not data:
        raise EmbeddingGenerationError("embedding response did not include data.")

    raw_embedding = _get_value(data[0], "embedding")
    if not isinstance(raw_embedding, list):
        raise EmbeddingGenerationError("embedding response did not include a vector.")
    try:
        return [float(value) for value in raw_embedding]
    except (TypeError, ValueError) as exc:
        raise EmbeddingGenerationError(
            "embedding response vector must contain numeric values."
        ) from exc


def _get_value(value: Any, key: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(key)
    return getattr(value, key, None)


__all__ = [
    "DEFAULT_EMBEDDING_MODE",
    "DEFAULT_LIVE_EMBEDDING_MODEL",
    "DEFAULT_LIVE_EMBEDDING_PROVIDER",
    "DOCUMENT_CHUNK_EMBEDDING_DIMENSIONS",
    "EMBEDDING_CONTRACT_VERSION",
    "EmbeddingConfigurationError",
    "EmbeddingContract",
    "EmbeddingGenerationError",
    "EmbeddingSettings",
    "MockEmbeddingAdapter",
    "OpenAIEmbeddingAdapter",
    "SUPPORTED_EMBEDDING_MODES",
    "TextEmbeddingAdapter",
    "build_embedding_metadata",
    "embedding_adapter_from_settings",
    "embedding_contract_from_settings",
    "merge_embedding_metadata",
    "validate_embedding_contract",
]
