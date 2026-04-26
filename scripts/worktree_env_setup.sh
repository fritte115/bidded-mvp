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


read_env_value() {
  local key="$1"
  local file="${2:-${WORKTREE_ROOT}/.env}"
  local line
  local value

  if [ ! -f "${file}" ]; then
    return 0
  fi

  line="$(
    grep -E "^[[:space:]]*(export[[:space:]]+)?${key}=" "${file}" | tail -n 1 || true
  )"
  if [ -z "${line}" ]; then
    return 0
  fi

  value="${line#*=}"
  value="$(printf '%s' "${value}" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
  case "${value}" in
    \"*\")
      value="${value#\"}"
      value="${value%\"}"
      ;;
    \'*\')
      value="${value#\'}"
      value="${value%\'}"
      ;;
  esac

  printf '%s\n' "${value}"
}


is_placeholder_env_value() {
  local value="$1"

  case "${value}" in
    "" | \
      *your-project-ref* | \
      replace-with-* | \
      your-* | \
      changeme | \
      CHANGE_ME)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}


first_real_env_value() {
  local key
  local value

  for key in "$@"; do
    value="$(read_env_value "${key}")"
    if ! is_placeholder_env_value "${value}"; then
      printf '%s\n' "${value}"
      return 0
    fi
  done
}


env_key_names() {
  local file="$1"

  if [ ! -f "${file}" ]; then
    return 0
  fi

  awk -F= '
    /^[[:space:]]*(export[[:space:]]+)?[A-Za-z_][A-Za-z0-9_]*=/ {
      key = $1
      sub(/^[[:space:]]*export[[:space:]]+/, "", key)
      sub(/^[[:space:]]+/, "", key)
      sub(/[[:space:]]+$/, "", key)
      print key
    }
  ' "${file}" | sort -u
}


set_env_value() {
  local key="$1"
  local value="$2"
  local file="${3:-${WORKTREE_ROOT}/.env}"
  local tmp_file

  tmp_file="${file}.tmp.$$"
  if grep -Eq "^[[:space:]]*(export[[:space:]]+)?${key}=" "${file}"; then
    awk -v key="${key}" -v value="${value}" '
      $0 ~ "^[[:space:]]*(export[[:space:]]+)?" key "=" {
        print key "=" value
        next
      }
      { print }
    ' "${file}" > "${tmp_file}"
  else
    cp "${file}" "${tmp_file}"
    printf '\n%s=%s\n' "${key}" "${value}" >> "${tmp_file}"
  fi
  mv "${tmp_file}" "${file}"
}


env_source_has_real_values() {
  local file="$1"
  local key
  local value

  for key in SUPABASE_URL SUPABASE_SERVICE_ROLE_KEY SUPABASE_ANON_KEY SUPABASE_PUBLISHABLE_KEY PUBLIC_SUPABASE_PUBLISHABLE_KEY NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY; do
    value="$(read_env_value "${key}" "${file}")"
    if ! is_placeholder_env_value "${value}"; then
      return 0
    fi
  done

  return 1
}


find_env_source_file() {
  local file
  local worktree_path

  if [ -n "${WORKTREE_ENV_SOURCE:-}" ] && [ -f "${WORKTREE_ENV_SOURCE}" ]; then
    printf '%s\n' "${WORKTREE_ENV_SOURCE}"
    return 0
  fi

  if command -v git >/dev/null 2>&1; then
    while IFS= read -r line; do
      case "${line}" in
        worktree\ *)
          worktree_path="${line#worktree }"
          file="${worktree_path}/.env"
          if [ "${file}" = "${WORKTREE_ROOT}/.env" ] || [ ! -f "${file}" ]; then
            continue
          fi
          if env_source_has_real_values "${file}"; then
            printf '%s\n' "${file}"
            return 0
          fi
          ;;
      esac
    done < <(git -C "${WORKTREE_ROOT}" worktree list --porcelain 2>/dev/null || true)
  fi
}


hydrate_env_file_from_source() {
  local source_file
  local key
  local source_value
  local target_value

  source_file="$(find_env_source_file)"
  if [ -z "${source_file}" ] || [ ! -f "${WORKTREE_ROOT}/.env" ]; then
    return 0
  fi

  while IFS= read -r key; do
    source_value="$(read_env_value "${key}" "${source_file}")"
    if is_placeholder_env_value "${source_value}"; then
      continue
    fi

    target_value="$(read_env_value "${key}")"
    if is_placeholder_env_value "${target_value}"; then
      set_env_value "${key}" "${source_value}"
    fi
  done < <(env_key_names "${source_file}")
}


ensure_frontend_env_file() {
  local supabase_url
  local supabase_public_key
  local agent_api_url

  if [ ! -d "${FRONTEND_DIR}" ] || [ -f "${FRONTEND_DIR}/.env" ]; then
    return 0
  fi

  supabase_url="$(first_real_env_value VITE_SUPABASE_URL SUPABASE_URL)"
  supabase_public_key="$(
    first_real_env_value \
      VITE_SUPABASE_ANON_KEY \
      SUPABASE_ANON_KEY \
      VITE_SUPABASE_PUBLISHABLE_KEY \
      SUPABASE_PUBLISHABLE_KEY \
      NEXT_PUBLIC_SUPABASE_ANON_KEY \
      NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY \
      PUBLIC_SUPABASE_PUBLISHABLE_KEY
  )"
  agent_api_url="$(first_real_env_value VITE_AGENT_API_URL)"
  if [ -z "${agent_api_url}" ]; then
    agent_api_url="http://localhost:8000"
  fi

  if [ -z "${supabase_url}" ] || [ -z "${supabase_public_key}" ]; then
    return 0
  fi

  {
    printf '# Generated by scripts/worktree_env_setup.sh from root .env.\n'
    printf '# Browser-safe values only; never add backend service-role credentials here.\n'
    printf 'VITE_SUPABASE_URL=%s\n' "${supabase_url}"
    printf 'VITE_SUPABASE_ANON_KEY=%s\n' "${supabase_public_key}"
    printf 'VITE_AGENT_API_URL=%s\n' "${agent_api_url}"
  } > "${FRONTEND_DIR}/.env"
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
    echo "Note: frontend/.env is absent; the UI will use mock data until SUPABASE_ANON_KEY or a publishable Supabase key is present in root .env."
  fi
}


main() {
  local python_bin

  python_bin="$(pick_python_bin)"
  cd "${WORKTREE_ROOT}"
  ensure_venv "${python_bin}"
  ensure_editable_install
  ensure_env_file
  hydrate_env_file_from_source
  ensure_frontend_env_file
  ensure_worktree_dirs
  ensure_frontend_deps
  print_optional_tool_notes
}


main "$@"
