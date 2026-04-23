#!/usr/bin/env bash
set -euo pipefail

WORKTREE_ROOT="${WORKTREE_ROOT:-$PWD}"
VENV_DIR="${WORKTREE_ROOT}/.venv"
STAMP_FILE="${VENV_DIR}/.codex-dev-install.stamp"
FRONTEND_DIR="${WORKTREE_ROOT}/frontend"
FRONTEND_STAMP_FILE="${FRONTEND_DIR}/node_modules/.codex-npm-install.stamp"


python_version_ok() {
  local candidate="$1"

  "${candidate}" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 12) else 1)
PY
}


pick_python_bin() {
  local candidate

  for candidate in "${PYTHON_BIN:-}" python3.14 python3.13 python3.12 python3; do
    if [ -z "${candidate}" ]; then
      continue
    fi
    if command -v "${candidate}" >/dev/null 2>&1 && python_version_ok "${candidate}"; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done

  echo "Python >=3.12 is required to bootstrap this worktree." >&2
  return 1
}


entrypoint_matches_worktree() {
  local script_path="$1"
  local first_line
  local file_prefix

  if [ ! -f "${script_path}" ]; then
    return 0
  fi

  file_prefix="$(LC_ALL=C head -c 2 "${script_path}" 2>/dev/null || true)"
  if [ "${file_prefix}" != "#!" ]; then
    return 0
  fi

  IFS= read -r first_line < "${script_path}" || return 1
  case "${first_line}" in
    "#!${VENV_DIR}/bin/"*)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}


venv_matches_worktree() {
  local reported_prefix

  if [ ! -f "${VENV_DIR}/pyvenv.cfg" ]; then
    return 1
  fi

  if [ ! -x "${VENV_DIR}/bin/python" ] || [ ! -f "${VENV_DIR}/bin/pip" ]; then
    return 1
  fi

  entrypoint_matches_worktree "${VENV_DIR}/bin/pip" || return 1
  if [ -f "${VENV_DIR}/bin/bidded" ]; then
    entrypoint_matches_worktree "${VENV_DIR}/bin/bidded" || return 1
  fi
  if [ -f "${VENV_DIR}/bin/pytest" ]; then
    entrypoint_matches_worktree "${VENV_DIR}/bin/pytest" || return 1
  fi
  if [ -f "${VENV_DIR}/bin/ruff" ]; then
    entrypoint_matches_worktree "${VENV_DIR}/bin/ruff" || return 1
  fi

  reported_prefix="$(
    "${VENV_DIR}/bin/python" - <<'PY'
import sys
print(sys.prefix)
PY
  )" || return 1

  [ "${reported_prefix}" = "${VENV_DIR}" ]
}


recreate_venv() {
  local python_bin="$1"

  rm -rf "${VENV_DIR}"
  "${python_bin}" -m venv "${VENV_DIR}"
  "${VENV_DIR}/bin/pip" install --upgrade pip
}


ensure_venv() {
  local python_bin="$1"

  if [ "${WORKTREE_FORCE_RECREATE_VENV:-0}" = "1" ] || ! venv_matches_worktree; then
    recreate_venv "${python_bin}"
  fi
}


ensure_editable_install() {
  if [ "${WORKTREE_SKIP_INSTALL:-0}" = "1" ]; then
    return 0
  fi

  if [ ! -f "${STAMP_FILE}" ] || [ "${WORKTREE_ROOT}/pyproject.toml" -nt "${STAMP_FILE}" ]; then
    "${VENV_DIR}/bin/pip" install -e ".[dev]"
    touch "${STAMP_FILE}"
    return 0
  fi

  if [ ! -x "${VENV_DIR}/bin/bidded" ] || \
    [ ! -x "${VENV_DIR}/bin/pytest" ] || \
    [ ! -x "${VENV_DIR}/bin/ruff" ]; then
    "${VENV_DIR}/bin/pip" install -e ".[dev]"
    touch "${STAMP_FILE}"
  fi
}


ensure_env_file() {
  if [ -f "${WORKTREE_ROOT}/.env" ] || [ ! -f "${WORKTREE_ROOT}/.env.example" ]; then
    return 0
  fi

  cp "${WORKTREE_ROOT}/.env.example" "${WORKTREE_ROOT}/.env"
}


ensure_worktree_dirs() {
  mkdir -p \
    "${WORKTREE_ROOT}/data/demo/incoming" \
    "${WORKTREE_ROOT}/output" \
    "${WORKTREE_ROOT}/tmp"
}


ensure_frontend_deps() {
  if [ "${WORKTREE_SKIP_FRONTEND_INSTALL:-0}" = "1" ]; then
    return 0
  fi

  if [ ! -f "${FRONTEND_DIR}/package-lock.json" ]; then
    return 0
  fi

  if ! command -v npm >/dev/null 2>&1; then
    echo "Warning: npm is missing; frontend dependencies were not installed." >&2
    return 0
  fi

  if [ ! -d "${FRONTEND_DIR}/node_modules" ] || \
    [ ! -f "${FRONTEND_STAMP_FILE}" ] || \
    [ "${FRONTEND_DIR}/package.json" -nt "${FRONTEND_STAMP_FILE}" ] || \
    [ "${FRONTEND_DIR}/package-lock.json" -nt "${FRONTEND_STAMP_FILE}" ]; then
    (cd "${FRONTEND_DIR}" && npm ci)
    touch "${FRONTEND_STAMP_FILE}"
  fi
}


print_optional_tool_notes() {
  if ! command -v cargo >/dev/null 2>&1; then
    echo "Note: cargo is missing; brain-in-the-fish tests will be unavailable."
  fi

  if [ ! -f "${FRONTEND_DIR}/.env" ]; then
    echo "Note: frontend/.env is absent; the UI will use mock data until live Supabase anon credentials are provided."
  fi
}


main() {
  local python_bin

  python_bin="$(pick_python_bin)"
  cd "${WORKTREE_ROOT}"
  ensure_venv "${python_bin}"
  ensure_editable_install
  ensure_env_file
  ensure_worktree_dirs
  ensure_frontend_deps
  print_optional_tool_notes
}


main "$@"
