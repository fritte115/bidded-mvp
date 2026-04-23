#!/usr/bin/env bash
set -euo pipefail

WORKTREE_ROOT="${WORKTREE_ROOT:-$PWD}"

rm -rf \
  "${WORKTREE_ROOT}/.pytest_cache" \
  "${WORKTREE_ROOT}/.mypy_cache" \
  "${WORKTREE_ROOT}/.ruff_cache" \
  "${WORKTREE_ROOT}/htmlcov" \
  "${WORKTREE_ROOT}/build" \
  "${WORKTREE_ROOT}/dist"

rm -rf \
  "${WORKTREE_ROOT}/frontend/.vite" \
  "${WORKTREE_ROOT}/frontend/dist" \
  "${WORKTREE_ROOT}/frontend/dist-ssr"

rm -rf \
  "${WORKTREE_ROOT}/.playwright-mcp" \
  "${WORKTREE_ROOT}/tmp" \
  "${WORKTREE_ROOT}/tmp-artifacts" \
  "${WORKTREE_ROOT}/output"

find "${WORKTREE_ROOT}" -type d -name __pycache__ -prune -exec rm -rf {} +
rm -f "${WORKTREE_ROOT}/.coverage"

if [ "${WORKTREE_REMOVE_LOCAL_STATE:-0}" = "1" ]; then
  rm -rf "${WORKTREE_ROOT}/data/demo/incoming"
fi

if [ "${WORKTREE_REMOVE_LOCAL_ENV:-0}" = "1" ]; then
  rm -f "${WORKTREE_ROOT}/.env" "${WORKTREE_ROOT}/frontend/.env"
fi

if [ "${WORKTREE_REMOVE_VENV:-0}" = "1" ]; then
  rm -rf "${WORKTREE_ROOT}/.venv"
fi

if [ "${WORKTREE_REMOVE_NODE_MODULES:-0}" = "1" ]; then
  rm -rf "${WORKTREE_ROOT}/frontend/node_modules"
fi
