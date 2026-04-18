# Ralph Progress Log
Started: 2026-04-18
---

## Codebase Patterns
> Reusable patterns discovered during implementation. Read this FIRST every session.

- **Ralph Directory**: Ralph files live in `ralph/`, not `scripts/ralph/`.
- **Current PRD Context**: Work from `ralph/state.json`; implement one `ralph/prd.json` story at a time in priority order.
- **Bidded Runtime Target**: Python package code belongs under `src/bidded`; tests and baseline gates must not require live Claude, live embeddings, or live Supabase.
- **Bidded Evidence Contract**: Material claims require excerpt-level `evidence_items` with source-specific provenance and `source_metadata.source_label`; unsupported points become assumptions, missing_info, validation errors, or potential blockers.
- **Bidded Orchestration Contract**: The orchestrator owns Supabase writes, validation, status transitions, and persistence; LLM agents produce validated artifacts only.
- **Bidded Quality Gates**: Use deterministic pytest tests and Ruff for story completion; live smoke checks are optional unless a story explicitly requires them.
- **Bidded Supabase Migrations**: Keep hosted Supabase SQL under `supabase/migrations/` with deterministic pytest contract tests, demo `tenant_key = 'demo'` checks, and no Auth/RLS unless a story adds it.
- **Bidded CLI Boundary**: Keep CLI help and package imports free of live Supabase/Claude client construction; create external clients only inside real command execution paths.
- **Bidded Agent Audit Contract**: `agent_outputs` are immutable rows keyed by `agent_role`, `round_name`, and `output_type`; `bid_decisions` surface Judge `evidence_ids`.
- **Bidded Graph State Contract**: `BidRunState` lives under `src/bidded/orchestration`; runtime control fields stay separate from persisted audit artifacts.

## Session Log

No Ralph story sessions have completed yet.

## 2026-04-18 17:33 CEST - US-001
- **Implemented**: Scaffolded the Python package, dependency metadata, Pydantic settings, import-light CLI help, deterministic tests, and README status updates.
- **Files**: pyproject.toml, src/bidded/, tests/, .gitignore, README.md, ralph/prd.json, ralph/state.json, ralph/progress.md, ralph/CLAUDE.md
- **Key learnings**: Keep CLI help/import paths free of live Supabase or Claude client construction so scaffold tests stay deterministic.
---

## 2026-04-18 17:44 CEST - US-002
- **Implemented**: Added the core Supabase domain migration for companies, tenders, and documents with deterministic migration contract tests and README status updates.
- **Files**: supabase/migrations/20260418180000_create_core_domain.sql, tests/test_supabase_migrations.py, README.md, ralph/prd.json, ralph/state.json, ralph/progress.md, ralph/CLAUDE.md
- **Key learnings**: Contract-test migration files directly so core Supabase storage assumptions stay deterministic without a live database.
---

## 2026-04-18 17:51 CEST - US-003
- **Implemented**: Added the agent audit Supabase migration for runs, immutable role/round outputs, and final decisions with contract tests.
- **Files**: supabase/migrations/20260418181000_create_agent_audit.sql, tests/test_supabase_migrations.py, README.md, ralph/prd.json, ralph/state.json, ralph/progress.md, ralph/CLAUDE.md
- **Key learnings**: Persist agent outputs by `agent_role`, `round_name`, and `output_type` so future graph nodes can write stable audit rows.
---

## 2026-04-18 17:57 CEST - US-004
- **Implemented**: Added document chunk and evidence item Supabase schema with pgvector-ready embeddings and source-specific provenance constraints.
- **Files**: supabase/migrations/20260418182000_create_chunk_evidence.sql, tests/test_supabase_migrations.py, README.md, ralph/prd.json, ralph/state.json, ralph/progress.md, ralph/CLAUDE.md
- **Key learnings**: Keep evidence provenance explicit in columns while preserving flexible source labels and extra context in JSONB metadata.
---

## 2026-04-18 18:05 CEST - US-005
- **Implemented**: Added the typed graph state schema, serialization round-trip tests, and README status update.
- **Files**: src/bidded/orchestration/state.py, src/bidded/orchestration/__init__.py, tests/test_orchestration_state.py, README.md, ralph/prd.json, ralph/state.json, ralph/progress.md, ralph/CLAUDE.md
- **Key learnings**: Keep graph runtime control fields explicit and separate from persisted audit artifacts before ownership enforcement.
---
