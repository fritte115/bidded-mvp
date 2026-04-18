# Ralph Progress Log
Started: 2026-04-18
---

## Codebase Patterns
> Reusable patterns discovered during implementation. Read this FIRST every session.

- **Ralph Directory**: Ralph files live in `ralph/`, not `scripts/ralph/`.
- **Current PRD Context**: Work from `ralph/state.json`; implement one `ralph/prd.json` story at a time in priority order.
- **Bidded Runtime Target**: Python package code belongs under `src/bidded`; tests and baseline gates must not require live Claude, live embeddings, or live Supabase.
- **Bidded Evidence Contract**: Material claims require excerpt-level `evidence_items`; unsupported points become assumptions, missing_info, validation errors, or potential blockers.
- **Bidded Orchestration Contract**: The orchestrator owns Supabase writes, validation, status transitions, and persistence; LLM agents produce validated artifacts only.
- **Bidded Quality Gates**: Use deterministic pytest tests and Ruff for story completion; live smoke checks are optional unless a story explicitly requires them.

## Session Log

No Ralph story sessions have completed yet.
