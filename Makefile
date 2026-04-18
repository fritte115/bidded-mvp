SHELL := /bin/bash

-include .env
export ANTHROPIC_API_KEY
export SUPABASE_URL
export SUPABASE_SERVICE_ROLE_KEY
export SUPABASE_STORAGE_BUCKET

RALPH_CODEX_MODEL ?= gpt-5.4
RALPH_CODEX_CMD ?= codex exec --model $(RALPH_CODEX_MODEL) --dangerously-bypass-approvals-and-sandbox
RALPH_SESSIONS ?= 10

PYTEST ?= .venv/bin/pytest
RUFF ?= .venv/bin/ruff
MYPY ?= .venv/bin/mypy
COVERAGE_PACKAGE ?= bidded
COVERAGE_FAIL_UNDER ?= 80
MYPY_TARGETS ?= src/bidded tests

.PHONY: ralph lint format-check test test-cov typecheck check check-fast
ralph:
	RALPH_CODEX_CMD='$(RALPH_CODEX_CMD)' \
		bash ./ralph/ralph.sh --tool codex $(RALPH_SESSIONS)

lint:
	$(RUFF) check .

format-check:
	$(RUFF) format --check .

test:
	$(PYTEST) -q

test-cov:
	$(PYTEST) -q --cov=$(COVERAGE_PACKAGE) --cov-report=term-missing --cov-fail-under=$(COVERAGE_FAIL_UNDER)

typecheck:
	$(MYPY) $(MYPY_TARGETS)

check-fast: lint format-check typecheck test

check: lint format-check typecheck test-cov
