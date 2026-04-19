from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_PROMPT_VERSION = "bidded_prompt_v1"
DEFAULT_SCHEMA_VERSION = "bidded_agent_output_schema_v1"
DEFAULT_RETRIEVAL_VERSION = "bidded_hybrid_retrieval_v1"
DEFAULT_MODEL_NAME = "mocked_graph_shell"
GOLDEN_EVAL_FIXTURE_VERSION = "golden_demo_cases_v1"

VERSION_METADATA_FIELDS = (
    "prompt_version",
    "schema_version",
    "retrieval_version",
    "model_name",
    "eval_fixture_version",
)
REQUIRED_VERSION_METADATA_FIELDS = (
    "prompt_version",
    "schema_version",
    "retrieval_version",
    "model_name",
)


class VersionMetadata(BaseModel):
    """Deterministic prompt/schema/retrieval/model provenance for audit rows."""

    model_config = ConfigDict(extra="forbid")

    prompt_version: str = Field(min_length=1)
    schema_version: str = Field(min_length=1)
    retrieval_version: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    eval_fixture_version: str | None = Field(default=None, min_length=1)


def default_version_metadata(
    *,
    eval_fixture_version: str | None = None,
) -> VersionMetadata:
    """Return the current deterministic version metadata defaults."""

    return VersionMetadata(
        prompt_version=DEFAULT_PROMPT_VERSION,
        schema_version=DEFAULT_SCHEMA_VERSION,
        retrieval_version=DEFAULT_RETRIEVAL_VERSION,
        model_name=DEFAULT_MODEL_NAME,
        eval_fixture_version=eval_fixture_version,
    )


def normalize_version_metadata(
    value: VersionMetadata | Mapping[str, Any] | None,
    *,
    eval_fixture_version: str | None = None,
) -> VersionMetadata:
    """Fill missing version metadata fields with deterministic defaults."""

    payload = version_metadata_dict(
        default_version_metadata(eval_fixture_version=eval_fixture_version)
    )
    if isinstance(value, VersionMetadata):
        incoming = value.model_dump(mode="json", exclude_none=True)
    elif isinstance(value, Mapping):
        incoming = {
            field: str(value[field])
            for field in VERSION_METADATA_FIELDS
            if _has_text(value.get(field))
        }
    else:
        incoming = {}

    payload.update(incoming)
    if eval_fixture_version is not None:
        payload["eval_fixture_version"] = eval_fixture_version
    return VersionMetadata.model_validate(payload)


def version_metadata_dict(metadata: VersionMetadata) -> dict[str, str]:
    """Serialize version metadata for JSONB payloads, omitting unavailable fields."""

    return metadata.model_dump(mode="json", exclude_none=True)


def version_metadata_warnings(
    value: VersionMetadata | Mapping[str, Any] | None,
    *,
    require_eval_fixture_version: bool = False,
) -> tuple[str, ...]:
    """Return warning strings for missing version metadata without raising."""

    if isinstance(value, VersionMetadata):
        payload = value.model_dump(mode="json", exclude_none=True)
    elif isinstance(value, Mapping):
        payload = dict(value)
    else:
        payload = {}

    required_fields = list(REQUIRED_VERSION_METADATA_FIELDS)
    if require_eval_fixture_version:
        required_fields.append("eval_fixture_version")

    missing_fields = [
        field for field in required_fields if not _has_text(payload.get(field))
    ]
    if not missing_fields:
        return ()

    return (f"missing version metadata: {', '.join(missing_fields)}",)


def _has_text(value: object) -> bool:
    return bool(str(value or "").strip())


__all__ = [
    "DEFAULT_MODEL_NAME",
    "DEFAULT_PROMPT_VERSION",
    "DEFAULT_RETRIEVAL_VERSION",
    "DEFAULT_SCHEMA_VERSION",
    "GOLDEN_EVAL_FIXTURE_VERSION",
    "REQUIRED_VERSION_METADATA_FIELDS",
    "VERSION_METADATA_FIELDS",
    "VersionMetadata",
    "default_version_metadata",
    "normalize_version_metadata",
    "version_metadata_dict",
    "version_metadata_warnings",
]
