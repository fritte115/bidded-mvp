SHELL := /bin/bash

-include .env
export ANTHROPIC_API_KEY

RALPH_MODEL ?= claude-opus-4-7
RALPH_SESSIONS ?= 10

.PHONY: ralph
ralph:
	@if [ -z "$$ANTHROPIC_API_KEY" ]; then \
		echo "Warning: ANTHROPIC_API_KEY is not set; Claude Code may fail in --bare API-key mode."; \
	fi
	RALPH_CLAUDE_CMD="claude --bare --model $(RALPH_MODEL) --dangerously-skip-permissions --print" \
		bash ./ralph/ralph.sh --tool claude $(RALPH_SESSIONS)
