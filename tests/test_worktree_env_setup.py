from __future__ import annotations

import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "worktree_env_setup.sh"


def _prepare_worktree(tmp_path: Path) -> Path:
    worktree = tmp_path / "worktree"
    frontend_dir = worktree / "frontend"
    frontend_dir.mkdir(parents=True)
    (worktree / ".env.example").write_text(
        "SUPABASE_URL=\nSUPABASE_SERVICE_ROLE_KEY=\n",
    )
    (frontend_dir / ".env.example").write_text(
        "VITE_SUPABASE_URL=https://your-project-ref.supabase.co\n"
        "VITE_SUPABASE_ANON_KEY=replace-with-your-supabase-anon-key\n",
    )
    return worktree


def _run_setup_function(
    worktree: Path,
    function_name: str,
    *,
    home: Path,
    xdg_config_home: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["WORKTREE_ROOT"] = str(worktree)
    if xdg_config_home is not None:
        env["XDG_CONFIG_HOME"] = str(xdg_config_home)
    else:
        env.pop("XDG_CONFIG_HOME", None)

    return subprocess.run(
        [
            "bash",
            "-lc",
            f"source {SCRIPT_PATH!s} >/dev/null 2>&1; {function_name}",
        ],
        cwd=worktree,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_ensure_env_file_copies_from_default_config_dir(tmp_path: Path) -> None:
    worktree = _prepare_worktree(tmp_path)
    home = tmp_path / "home"
    config_dir = home / ".config" / "bidded"
    config_dir.mkdir(parents=True)
    backend_source = config_dir / "backend.env"
    backend_source.write_text(
        "SUPABASE_URL=https://example.supabase.co\n"
        "SUPABASE_SERVICE_ROLE_KEY=test-service-role\n",
    )

    result = _run_setup_function(worktree, "ensure_env_file", home=home)

    assert result.returncode == 0, result.stderr
    assert (worktree / ".env").read_text() == backend_source.read_text()


def test_ensure_env_file_copies_from_xdg_config_dir(tmp_path: Path) -> None:
    worktree = _prepare_worktree(tmp_path)
    home = tmp_path / "home"
    xdg_config_home = tmp_path / "xdg-config"
    config_dir = xdg_config_home / "bidded"
    config_dir.mkdir(parents=True)
    backend_source = config_dir / "backend.env"
    backend_source.write_text(
        "SUPABASE_URL=https://xdg.supabase.co\n"
        "SUPABASE_SERVICE_ROLE_KEY=xdg-service-role\n",
    )

    result = _run_setup_function(
        worktree,
        "ensure_env_file",
        home=home,
        xdg_config_home=xdg_config_home,
    )

    assert result.returncode == 0, result.stderr
    assert (worktree / ".env").read_text() == backend_source.read_text()


def test_ensure_frontend_env_file_copies_from_default_config_dir(
    tmp_path: Path,
) -> None:
    worktree = _prepare_worktree(tmp_path)
    home = tmp_path / "home"
    config_dir = home / ".config" / "bidded"
    config_dir.mkdir(parents=True)
    frontend_source = config_dir / "frontend.env"
    frontend_source.write_text(
        "VITE_SUPABASE_URL=https://example.supabase.co\n"
        "VITE_SUPABASE_ANON_KEY=test-anon-key\n",
    )

    result = _run_setup_function(worktree, "ensure_frontend_env_file", home=home)

    assert result.returncode == 0, result.stderr
    expected_env = (
        "# Supabase project credentials "
        "(anon/public key only - never the service role key)\n"
        "VITE_SUPABASE_URL=https://example.supabase.co\n"
        "VITE_SUPABASE_ANON_KEY=test-anon-key\n"
        "VITE_AGENT_API_URL=http://localhost:8000\n"
    )
    assert (worktree / "frontend" / ".env").read_text() == expected_env


def test_ensure_frontend_env_file_accepts_root_public_publishable_key(
    tmp_path: Path,
) -> None:
    worktree = _prepare_worktree(tmp_path)
    home = tmp_path / "home"
    (worktree / ".env").write_text(
        "SUPABASE_URL=https://example.supabase.co\n"
        "PUBLIC_SUPABASE_PUBLISHABLE_KEY=publishable-public-key\n"
        "SUPABASE_SERVICE_ROLE_KEY=service-role-secret\n",
    )

    result = _run_setup_function(worktree, "ensure_frontend_env_file", home=home)

    assert result.returncode == 0, result.stderr
    frontend_env = (worktree / "frontend" / ".env").read_text()
    assert "VITE_SUPABASE_URL=https://example.supabase.co" in frontend_env
    assert "VITE_SUPABASE_ANON_KEY=publishable-public-key" in frontend_env
    assert "service-role-secret" not in frontend_env
    assert "SUPABASE_SERVICE_ROLE_KEY" not in frontend_env


def test_ensure_env_file_prefers_git_configured_source(tmp_path: Path) -> None:
    worktree = _prepare_worktree(tmp_path)
    home = tmp_path / "home"
    home.mkdir(parents=True)
    default_config_dir = home / ".config" / "bidded"
    default_config_dir.mkdir(parents=True)
    (default_config_dir / "backend.env").write_text(
        "SUPABASE_URL=https://default.supabase.co\n"
        "SUPABASE_SERVICE_ROLE_KEY=default-service-role\n",
    )
    configured_source = tmp_path / "configured-backend.env"
    configured_source.write_text(
        "SUPABASE_URL=https://configured.supabase.co\n"
        "SUPABASE_SERVICE_ROLE_KEY=configured-service-role\n",
    )

    git_env = os.environ.copy()
    git_env["HOME"] = str(home)
    git_env.pop("XDG_CONFIG_HOME", None)
    subprocess.run(
        [
            "git",
            "config",
            "--global",
            "bidded.backend-env-source",
            str(configured_source),
        ],
        env=git_env,
        check=True,
        capture_output=True,
        text=True,
    )

    result = _run_setup_function(worktree, "ensure_env_file", home=home)

    assert result.returncode == 0, result.stderr
    assert (worktree / ".env").read_text() == configured_source.read_text()
