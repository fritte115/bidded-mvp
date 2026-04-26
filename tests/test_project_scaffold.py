from __future__ import annotations

import importlib
import os
import subprocess
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
        "bidded.doctor",
        "bidded.embeddings",
        "bidded.evidence",
        "bidded.retrieval",
        "bidded.agents",
        "bidded.llm",
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
        "OPENAI_API_KEY",
        "SUPABASE_URL",
        "SUPABASE_ANON_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_STORAGE_BUCKET",
        "EMBEDDING_MODE",
        "EMBEDDING_PROVIDER",
        "EMBEDDING_MODEL",
        "EMBEDDING_DIMENSIONS",
    ]:
        assert f"{setting_name}=" in env_example


def test_settings_load_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-service-role")
    monkeypatch.setenv("SUPABASE_STORAGE_BUCKET", "demo-bucket")
    monkeypatch.setenv("EMBEDDING_MODE", "mock")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
    monkeypatch.setenv("EMBEDDING_MODEL", "text-embedding-3-small")
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "1536")

    settings = BiddedSettings(_env_file=None)

    assert settings.anthropic_api_key == "test-anthropic"
    assert settings.supabase_url == "https://example.supabase.co"
    assert settings.supabase_service_role_key == "test-service-role"
    assert settings.supabase_storage_bucket == "demo-bucket"
    assert settings.embedding_mode == "mock"
    assert settings.embedding_provider == "openai"
    assert settings.embedding_model == "text-embedding-3-small"
    assert settings.embedding_dimensions == 1536


def test_worktree_setup_writes_frontend_env_from_public_supabase_source(
    tmp_path: Path,
) -> None:
    worktree = tmp_path / "worktree"
    frontend = worktree / "frontend"
    frontend.mkdir(parents=True)
    (frontend / ".env.example").write_text(
        "VITE_SUPABASE_URL=https://your-project-ref.supabase.co\n"
        "VITE_SUPABASE_ANON_KEY=replace-with-your-supabase-anon-key\n"
        "VITE_AGENT_API_URL=http://localhost:8000\n"
    )
    source_env = tmp_path / "public-frontend.env"
    source_env.write_text(
        "VITE_SUPABASE_URL=https://example.supabase.co\n"
        "SUPABASE_ANON_KEY=test-anon-key\n"
        "SUPABASE_SERVICE_ROLE_KEY=must-not-be-copied\n"
        "VITE_AGENT_API_URL=http://127.0.0.1:8002\n"
    )

    subprocess.run(
        [
            "bash",
            "-c",
            (
                f"source {PROJECT_ROOT / 'scripts/worktree_env_setup.sh'}; "
                "ensure_frontend_env_file"
            ),
        ],
        check=True,
        env={
            **os.environ,
            "WORKTREE_ROOT": str(worktree),
            "FRONTEND_ENV_SOURCE": str(source_env),
        },
    )

    frontend_env = (frontend / ".env").read_text()
    assert "VITE_SUPABASE_URL=https://example.supabase.co" in frontend_env
    assert "VITE_SUPABASE_ANON_KEY=test-anon-key" in frontend_env
    assert "VITE_AGENT_API_URL=http://127.0.0.1:8002" in frontend_env
    assert "SUPABASE_SERVICE_ROLE_KEY" not in frontend_env
