#!/usr/bin/env bash
set -euo pipefail

WORKTREE_ROOT="${WORKTREE_ROOT:-$PWD}"
VENV_DIR="${WORKTREE_ROOT}/.venv"
STAMP_FILE="${VENV_DIR}/.codex-dev-install.stamp"
FRONTEND_DIR="${WORKTREE_ROOT}/frontend"
FRONTEND_STAMP_FILE="${FRONTEND_DIR}/node_modules/.codex-npm-install.stamp"


bidded_config_dir() {
  if [ -n "${XDG_CONFIG_HOME:-}" ]; then
    printf '%s\n' "${XDG_CONFIG_HOME}/bidded"
    return 0
  fi

  printf '%s\n' "${HOME}/.config/bidded"
}


git_config_path() {
  local key="$1"

  if ! command -v git >/dev/null 2>&1; then
    return 1
  fi

  git config --path --get "${key}" 2>/dev/null
}


copy_backend_env_from_known_sources() {
  local source_path

  for source_path in \
    "${ENV_SOURCE:-}" \
    "$(git_config_path "bidded.backend-env-source" || true)" \
    "$(bidded_config_dir)/backend.env"; do
    [ -n "${source_path}" ] || continue
    copy_backend_env_if_valid "${source_path}" && return 0
  done

  return 1
}


copy_frontend_env_from_known_sources() {
  local source_path

  for source_path in \
    "${FRONTEND_ENV_SOURCE:-}" \
    "$(git_config_path "bidded.frontend-env-source" || true)" \
    "$(bidded_config_dir)/frontend.env"; do
    [ -n "${source_path}" ] || continue
    copy_frontend_env_if_valid "${source_path}" && return 0
  done

  return 1
}


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
  if [ ! -f "${WORKTREE_ROOT}/.env.example" ]; then
    return 0
  fi

  if backend_env_has_live_credentials "${WORKTREE_ROOT}/.env"; then
    return 0
  fi

  copy_backend_env_from_known_sources && return 0

  copy_backend_env_from_worktrees && return 0

  if [ ! -f "${WORKTREE_ROOT}/.env" ]; then
    cp "${WORKTREE_ROOT}/.env.example" "${WORKTREE_ROOT}/.env"
  fi
}


backend_env_has_live_credentials() {
  local env_path="$1"

  [ -f "${env_path}" ] || return 1

  awk -F= '
    /^[[:space:]]*(#|$)/ { next }
    $1 == "SUPABASE_URL" {
      url=$2
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", url)
    }
    $1 == "SUPABASE_SERVICE_ROLE_KEY" {
      service_role=$2
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", service_role)
    }
    END {
      if (url != "" && service_role != "") {
        exit 0
      }
      exit 1
    }
  ' "${env_path}"
}


copy_backend_env_if_valid() {
  local source_path="$1"

  if [ "${source_path}" = "${WORKTREE_ROOT}/.env" ]; then
    return 1
  fi

  if backend_env_has_live_credentials "${source_path}"; then
    cp "${source_path}" "${WORKTREE_ROOT}/.env"
    echo "Wrote .env from backend credentials in ${source_path}"
    return 0
  fi

  return 1
}


copy_backend_env_from_worktrees() {
  local worktree_path
  local source_path

  if ! command -v git >/dev/null 2>&1; then
    return 1
  fi

  while IFS= read -r worktree_path; do
    source_path="${worktree_path}/.env"
    copy_backend_env_if_valid "${source_path}" && return 0
  done < <(git -C "${WORKTREE_ROOT}" worktree list --porcelain 2>/dev/null | awk '/^worktree / { sub(/^worktree /, ""); print }')

  return 1
}


frontend_env_has_live_supabase() {
  local env_path="$1"

  [ -f "${env_path}" ] || return 1

  awk -F= '
    /^[[:space:]]*(#|$)/ { next }
    $1 == "VITE_SUPABASE_URL" || $1 == "SUPABASE_URL" || $1 == "NEXT_PUBLIC_SUPABASE_URL" {
      url=$2
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", url)
    }
    $1 == "VITE_SUPABASE_ANON_KEY" || $1 == "SUPABASE_ANON_KEY" || $1 == "SUPABASE_PUBLISHABLE_KEY" || $1 == "PUBLIC_SUPABASE_PUBLISHABLE_KEY" || $1 == "NEXT_PUBLIC_SUPABASE_ANON_KEY" || $1 == "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY" {
      anon=$2
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", anon)
    }
    END {
      if (url != "" && anon != "" && url !~ /your-project-ref/ && anon !~ /replace-with-your-supabase-anon-key/) {
        exit 0
      }
      exit 1
    }
  ' "${env_path}"
}


copy_frontend_env_if_valid() {
  local source_path="$1"

  if [ "${source_path}" = "${FRONTEND_DIR}/.env" ]; then
    return 1
  fi

  if frontend_env_has_live_supabase "${source_path}"; then
    write_frontend_env_from_source "${source_path}"
    echo "Wrote frontend/.env from public Supabase credentials in ${source_path}"
    return 0
  fi

  return 1
}


extract_env_value() {
  local env_path="$1"
  local key="$2"

  awk -v key="${key}" '
    BEGIN { prefix = key "=" }
    index($0, prefix) == 1 {
      value = substr($0, length(prefix) + 1)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
      print value
      exit
    }
  ' "${env_path}"
}


extract_first_env_value() {
  local env_path="$1"
  shift

  local key
  local value

  for key in "$@"; do
    value="$(extract_env_value "${env_path}" "${key}")"
    if [ -n "${value}" ]; then
      printf '%s\n' "${value}"
      return 0
    fi
  done
}


write_frontend_env_from_source() {
  local source_path="$1"
  local vite_supabase_url
  local vite_supabase_anon_key
  local vite_agent_api_url

  vite_supabase_url="$(
    extract_first_env_value \
      "${source_path}" \
      "VITE_SUPABASE_URL" \
      "SUPABASE_URL" \
      "NEXT_PUBLIC_SUPABASE_URL"
  )"
  vite_supabase_anon_key="$(
    extract_first_env_value \
      "${source_path}" \
      "VITE_SUPABASE_ANON_KEY" \
      "SUPABASE_ANON_KEY" \
      "SUPABASE_PUBLISHABLE_KEY" \
      "PUBLIC_SUPABASE_PUBLISHABLE_KEY" \
      "NEXT_PUBLIC_SUPABASE_ANON_KEY" \
      "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY"
  )"
  vite_agent_api_url="$(extract_env_value "${source_path}" "VITE_AGENT_API_URL")"
  vite_agent_api_url="${vite_agent_api_url:-http://localhost:8000}"

  cat > "${FRONTEND_DIR}/.env" <<EOF
# Supabase project credentials (anon/public key only - never the service role key)
VITE_SUPABASE_URL=${vite_supabase_url}
VITE_SUPABASE_ANON_KEY=${vite_supabase_anon_key}
VITE_AGENT_API_URL=${vite_agent_api_url}
EOF
}


copy_frontend_env_from_worktrees() {
  local worktree_path
  local source_path

  if ! command -v git >/dev/null 2>&1; then
    return 1
  fi

  while IFS= read -r worktree_path; do
    for source_path in "${worktree_path}/frontend/.env" "${worktree_path}/.env"; do
      copy_frontend_env_if_valid "${source_path}" && return 0
    done
  done < <(git -C "${WORKTREE_ROOT}" worktree list --porcelain 2>/dev/null | awk '/^worktree / { sub(/^worktree /, ""); print }')

  return 1
}


ensure_frontend_env_file() {
  if [ ! -f "${FRONTEND_DIR}/.env.example" ]; then
    return 0
  fi

  if frontend_env_has_live_supabase "${FRONTEND_DIR}/.env"; then
    return 0
  fi

  copy_frontend_env_from_known_sources && return 0

  copy_frontend_env_if_valid "${WORKTREE_ROOT}/.env" && return 0

  copy_frontend_env_from_worktrees && return 0

  if [ ! -f "${FRONTEND_DIR}/.env" ]; then
    cp "${FRONTEND_DIR}/.env.example" "${FRONTEND_DIR}/.env"
  fi
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

  if ! frontend_env_has_live_supabase "${FRONTEND_DIR}/.env"; then
    echo "Note: frontend/.env is missing live Supabase Vite credentials; login will not work until VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY are set."
  fi
}


main() {
  local python_bin

  python_bin="$(pick_python_bin)"
  cd "${WORKTREE_ROOT}"
  ensure_venv "${python_bin}"
  ensure_editable_install
  ensure_env_file
  ensure_frontend_env_file
  ensure_worktree_dirs
  ensure_frontend_deps
  print_optional_tool_notes
}


if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main "$@"
fi
