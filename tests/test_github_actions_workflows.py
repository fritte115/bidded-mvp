from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_pr_gates_workflow_runs_deterministic_checks() -> None:
    workflow = PROJECT_ROOT / ".github" / "workflows" / "pr-gates.yml"
    assert workflow.exists()
    text = workflow.read_text()

    for required_fragment in [
        "name: PR Gates",
        "pull_request:",
        "push:",
        "permissions:",
        "contents: read",
        "name: Whitespace",
        "git diff --check",
        "name: Backend",
        'python-version: "3.12"',
        'python -m pip install -e ".[dev]"',
        "python -m pytest -q",
        "EMBEDDING_MODE: mock",
        "name: Ruff",
        "ruff check .",
        "name: Frontend",
        'node-version: "22"',
        "cache-dependency-path: frontend/package-lock.json",
        "npm ci",
        "npm run lint",
        "npm run test",
        "npm run build",
    ]:
        assert required_fragment in text


def test_pr_gates_workflow_avoids_live_service_secrets() -> None:
    text = (
        PROJECT_ROOT / ".github" / "workflows" / "pr-gates.yml"
    ).read_text().lower()

    assert "anthropic_api_key" not in text
    assert "supabase_service_role_key" not in text
    assert "supabase_jwt_secret" not in text
    assert "secrets." not in text
