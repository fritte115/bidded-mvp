from __future__ import annotations

import importlib
import tomllib
from pathlib import Path

import pytest

from bidded.config import BiddedSettings

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "module_name",
    [
        "bidded.config",
        "bidded.db",
        "bidded.documents",
        "bidded.evidence",
        "bidded.retrieval",
        "bidded.agents",
        "bidded.orchestration",
        "bidded.cli",
    ],
)
def test_required_package_domains_are_importable(module_name: str) -> None:
    assert importlib.import_module(module_name)


def test_project_declares_scaffold_dependencies() -> None:
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text())

    dependency_names = {
        dependency.split(";", maxsplit=1)[0]
        .split("[", maxsplit=1)[0]
        .split("<", maxsplit=1)[0]
        .split(">", maxsplit=1)[0]
        .split("=", maxsplit=1)[0]
        .split("~", maxsplit=1)[0]
        .strip()
        .lower()
        for dependency_group in [
            pyproject["project"]["dependencies"],
            pyproject["project"]["optional-dependencies"]["dev"],
            pyproject["project"]["optional-dependencies"]["embeddings"],
        ]
        for dependency in dependency_group
    }

    assert {
        "anthropic",
        "fastapi",
        "langgraph",
        "pydantic",
        "pydantic-settings",
        "pymupdf",
        "pytest",
        "python-dotenv",
        "ruff",
        "supabase",
        "uvicorn",
    }.issubset(dependency_names)
    assert "openai" in dependency_names


def test_env_example_documents_required_runtime_settings() -> None:
    env_example = (PROJECT_ROOT / ".env.example").read_text()

    for setting_name in [
        "ANTHROPIC_API_KEY",
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_STORAGE_BUCKET",
        "EMBEDDING_PROVIDER",
    ]:
        assert f"{setting_name}=" in env_example


def test_settings_load_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-service-role")
    monkeypatch.setenv("SUPABASE_STORAGE_BUCKET", "demo-bucket")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "mock")

    settings = BiddedSettings()

    assert settings.anthropic_api_key == "test-anthropic"
    assert settings.supabase_url == "https://example.supabase.co"
    assert settings.supabase_service_role_key == "test-service-role"
    assert settings.supabase_storage_bucket == "demo-bucket"
    assert settings.embedding_provider == "mock"
