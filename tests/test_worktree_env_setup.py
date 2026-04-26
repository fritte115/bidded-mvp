from __future__ import annotations

import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _run_setup(
    worktree_root: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "WORKTREE_ROOT": str(worktree_root),
            "WORKTREE_SKIP_INSTALL": "1",
            "WORKTREE_SKIP_FRONTEND_INSTALL": "1",
        }
    )
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(PROJECT_ROOT / "scripts/worktree_env_setup.sh")],
        cwd=worktree_root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def _minimal_worktree(tmp_path: Path, env_text: str) -> Path:
    worktree_root = tmp_path / "repo"
    frontend_dir = worktree_root / "frontend"
    frontend_dir.mkdir(parents=True)
    (worktree_root / ".env").write_text(env_text)
    (worktree_root / ".env.example").write_text("# example\n")
    (frontend_dir / ".env.example").write_text(
        "VITE_SUPABASE_URL=https://your-project-ref.supabase.co\n"
        "VITE_SUPABASE_ANON_KEY=replace-with-your-supabase-anon-key\n"
        "VITE_AGENT_API_URL=http://localhost:8000\n"
    )
    return worktree_root


def test_worktree_setup_materializes_frontend_env_without_service_role(
    tmp_path: Path,
) -> None:
    worktree_root = _minimal_worktree(
        tmp_path,
        "\n".join(
            [
                "SUPABASE_URL=https://demo-project.supabase.co",
                "SUPABASE_ANON_KEY=anon-public-key",
                "SUPABASE_SERVICE_ROLE_KEY=service-role-secret",
                "",
            ]
        ),
    )

    result = _run_setup(worktree_root)

    assert result.returncode == 0, result.stderr
    frontend_env = (worktree_root / "frontend/.env").read_text()
    assert "VITE_SUPABASE_URL=https://demo-project.supabase.co" in frontend_env
    assert "VITE_SUPABASE_ANON_KEY=anon-public-key" in frontend_env
    assert "VITE_AGENT_API_URL=http://localhost:8000" in frontend_env
    assert "service-role-secret" not in frontend_env
    assert "SUPABASE_SERVICE_ROLE_KEY" not in frontend_env


def test_worktree_setup_preserves_existing_frontend_env(tmp_path: Path) -> None:
    worktree_root = _minimal_worktree(
        tmp_path,
        "\n".join(
            [
                "SUPABASE_URL=https://demo-project.supabase.co",
                "SUPABASE_ANON_KEY=anon-public-key",
                "",
            ]
        ),
    )
    frontend_env_path = worktree_root / "frontend/.env"
    frontend_env_path.write_text("VITE_SUPABASE_URL=https://custom.supabase.co\n")

    result = _run_setup(worktree_root)

    assert result.returncode == 0, result.stderr
    assert frontend_env_path.read_text() == "VITE_SUPABASE_URL=https://custom.supabase.co\n"


def test_worktree_setup_requires_public_frontend_key(tmp_path: Path) -> None:
    worktree_root = _minimal_worktree(
        tmp_path,
        "\n".join(
            [
                "SUPABASE_URL=https://demo-project.supabase.co",
                "SUPABASE_SERVICE_ROLE_KEY=service-role-secret",
                "",
            ]
        ),
    )

    result = _run_setup(worktree_root)

    assert result.returncode == 0, result.stderr
    assert not (worktree_root / "frontend/.env").exists()


def test_worktree_setup_hydrates_blank_env_from_source_without_overwriting(
    tmp_path: Path,
) -> None:
    source_env = tmp_path / "source.env"
    source_env.write_text(
        "\n".join(
            [
                "SUPABASE_URL=https://demo-project.supabase.co",
                "PUBLIC_SUPABASE_PUBLISHABLE_KEY=publishable-public-key",
                "SUPABASE_SERVICE_ROLE_KEY=service-role-secret",
                "ANTHROPIC_API_KEY=source-anthropic",
                "",
            ]
        )
    )
    worktree_root = _minimal_worktree(
        tmp_path,
        "\n".join(
            [
                "SUPABASE_URL=",
                "SUPABASE_SERVICE_ROLE_KEY=",
                "ANTHROPIC_API_KEY=keep-local",
                "",
            ]
        ),
    )

    result = _run_setup(
        worktree_root,
        extra_env={"WORKTREE_ENV_SOURCE": str(source_env)},
    )

    assert result.returncode == 0, result.stderr
    root_env = (worktree_root / ".env").read_text()
    assert "SUPABASE_URL=https://demo-project.supabase.co" in root_env
    assert "PUBLIC_SUPABASE_PUBLISHABLE_KEY=publishable-public-key" in root_env
    assert "SUPABASE_SERVICE_ROLE_KEY=service-role-secret" in root_env
    assert "ANTHROPIC_API_KEY=keep-local" in root_env
    assert "ANTHROPIC_API_KEY=source-anthropic" not in root_env

    frontend_env = (worktree_root / "frontend/.env").read_text()
    assert "VITE_SUPABASE_URL=https://demo-project.supabase.co" in frontend_env
    assert "VITE_SUPABASE_ANON_KEY=publishable-public-key" in frontend_env
    assert "service-role-secret" not in frontend_env
