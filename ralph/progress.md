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
- **Bidded CLI Boundary**: Keep CLI help/package imports free of live client construction; create external clients only inside real command execution paths and keep seed helpers injectable for tests.
- **Bidded Tender Registration Contract**: Register demo tender PDFs through injected Supabase clients, deterministic checksum storage paths, demo-company metadata, and mocked Storage in tests.
- **Bidded Pending Run Contract**: Create `agent_runs` through an orchestration service that validates demo company, tender, and tender document rows, inserts `pending`, and leaves processing for later graph steps.
- **Bidded Agent Audit Contract**: `agent_outputs` are immutable rows keyed by `agent_role`, `round_name`, and `output_type`; `bid_decisions` surface Judge `evidence_ids`.
- **Bidded Graph State Contract**: `BidRunState.apply_node_update` enforces `GraphNodeName` ownership, append-only audit artifacts, write-once decisions, and role-keyed specialist reducers.
- **Bidded Agent Tool Policy Contract**: `src/bidded/agents/tool_policy.py` is the source of truth for LLM-agent denied tools, bounded retrieval, artifact access, and orchestrator-owned side effects.
- **Bidded Agent Output Schema Contract**: `src/bidded/agents/schemas.py` is the strict Pydantic surface for motions, rebuttals, Judge decisions, evidence refs, material claim evidence-ID validation, typed evidence gaps, validation errors, and specialist role bounds.
- **Bidded Company Evidence Builder Contract**: `src/bidded/evidence/company_profile.py` converts seeded company JSON into Supabase-ready `company_profile` rows and uses stable `tenant_key,evidence_key` upserts for idempotence.

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

## 2026-04-18 18:13 CEST - US-006
- **Implemented**: Added graph node ownership contracts, append-only/write-once state update enforcement, role-keyed specialist reducers, and deterministic tests.
- **Files**: src/bidded/orchestration/state.py, src/bidded/orchestration/__init__.py, tests/test_orchestration_state.py, README.md, ralph/prd.json, ralph/state.json, ralph/progress.md, ralph/CLAUDE.md
- **Key learnings**: Route graph mutations through `BidRunState.apply_node_update` so node ownership and reducer policy stay centralized.
---

## 2026-04-18 18:21 CEST - US-007
- **Implemented**: Added immutable agent tool policy contracts for Evidence Scout, specialists, Judge, and orchestrator side effects with deterministic tests.
- **Files**: src/bidded/agents/tool_policy.py, src/bidded/agents/__init__.py, tests/test_agent_tool_policies.py, README.md, ralph/prd.json, ralph/state.json, ralph/progress.md, ralph/CLAUDE.md
- **Key learnings**: Keep LLM-agent permissions separate from graph-node state reducers so tool access and orchestrator persistence remain independently testable.
---
## 2026-04-18 18:29 CEST - US-008
- **Implemented**: Added strict Pydantic schemas for Round 1 motions, Round 2 rebuttals, and Judge decisions with deterministic serialization tests.
- **Files**: src/bidded/agents/schemas.py, src/bidded/agents/__init__.py, tests/test_agent_output_schemas.py, README.md, ralph/prd.json, ralph/state.json, ralph/progress.md, ralph/CLAUDE.md
- **Key learnings**: Keep agent artifact schemas in `src/bidded/agents/schemas.py`; future node logic should consume validated artifacts instead of inventing per-node payload shapes.
---
## 2026-04-18 18:37 CEST - US-009
- **Implemented**: Added resolved evidence-ID validation for material agent claims, typed evidence gaps, and structured validation error fields.
- **Files**: src/bidded/agents/schemas.py, tests/test_agent_output_schemas.py, README.md, ralph/prd.json, ralph/state.json, ralph/progress.md, ralph/CLAUDE.md
- **Key learnings**: Material claim validation belongs in the agent schema containers so graph nodes can retry invalid LLM artifacts before persistence.
---
## 2026-04-18 18:54 CEST - US-010
- **Implemented**: Added an idempotent Supabase seed command for the synthetic larger IT consultancy demo profile.
- **Files**: src/bidded/db/seed_demo_company.py, src/bidded/cli/__init__.py, tests/test_demo_company_seed.py, tests/test_cli.py, README.md, ralph/prd.json, ralph/state.json, ralph/progress.md, ralph/CLAUDE.md
- **Key learnings**: Keep seeded data builders deterministic and inject the persistence client so Supabase behavior is testable without a live backend.
---
## 2026-04-18 19:02 CEST - US-011
- **Implemented**: Added deterministic company-profile evidence conversion and idempotent `evidence_items` upsert coverage for seeded facts.
- **Files**: src/bidded/evidence/company_profile.py, src/bidded/evidence/__init__.py, tests/test_company_profile_evidence.py, README.md, ralph/prd.json, ralph/state.json, ralph/progress.md, ralph/CLAUDE.md
- **Key learnings**: Use stable company evidence keys and `field_path` provenance so later graph code can cite seeded facts without live Supabase in tests.
---
## 2026-04-18 19:09 CEST - US-012
- **Implemented**: Added demo tender PDF registration with CLI parsing, deterministic storage uploads, tender/document upserts, and validation errors.
- **Files**: src/bidded/documents/tender_registration.py, src/bidded/documents/__init__.py, src/bidded/cli/__init__.py, tests/test_tender_pdf_registration.py, tests/test_cli.py, README.md, ralph/prd.json, ralph/state.json, ralph/progress.md, ralph/CLAUDE.md
- **Key learnings**: Keep tender registration idempotent by deriving storage paths from file checksum plus normalized filename and persisting demo-company linkage in metadata.
---
## 2026-04-18 19:20 CEST - US-013
- **Implemented**: Added pending agent run creation with deterministic evidence-locked run config, Supabase row validation, and CLI wiring.
- **Files**: src/bidded/orchestration/pending_run.py, src/bidded/orchestration/__init__.py, src/bidded/cli/__init__.py, tests/test_pending_run_context.py, tests/test_cli.py, README.md, ralph/prd.json, ralph/state.json, ralph/progress.md, ralph/CLAUDE.md
- **Key learnings**: Keep pending run creation side-effect-light by validating existing Supabase rows before inserting `agent_runs` and deferring all processing to later graph steps.
---
