# Ralph Progress Log
Started: 2026-04-18
---

## Codebase Patterns
> Reusable patterns discovered during implementation. Read this FIRST every session.

- **Ralph Directory**: Ralph files live in `ralph/`, not `scripts/ralph/`.
- **Current PRD Context**: Work from `ralph/state.json`; implement one `ralph/prd.json` story at a time in priority order.
- **Bidded Runtime Target**: Python package code belongs under `src/bidded`; tests and baseline gates must not require live Claude, live embeddings, or live Supabase.
- **Bidded Evidence Contract**: Material claims require excerpt-level `evidence_items` with source-specific provenance and `source_metadata.source_label`; unsupported points become assumptions, missing_info, validation errors, or potential blockers.
- **Bidded Orchestration Contract**: The orchestrator owns Supabase writes, validation, status transitions, worker lifecycle, and persistence; LLM agents produce validated artifacts only.
- **Bidded Quality Gates**: Use deterministic pytest tests and Ruff for story completion; live smoke checks are optional unless a story explicitly requires them.
- **Bidded Supabase Migrations**: Keep hosted Supabase SQL under `supabase/migrations/` with deterministic pytest contract tests, demo `tenant_key = 'demo'` checks, and no Auth/RLS unless a story adds it.
- **Bidded CLI Boundary**: Keep CLI help/package imports free of live client construction; create external clients only inside real command execution paths and keep command services injectable for tests.
- **Bidded Document Pipeline Contract**: Keep tender registration and PDF ingestion in `src/bidded/documents`; registered text-PDFs use mocked Storage, PyMuPDF extraction, deterministic page chunks, and parser status metadata.
- **Bidded Pending Run Contract**: Create `agent_runs` through an orchestration service that validates demo company, tender, and tender document rows, inserts `pending`, and leaves processing for later graph steps.
- **Bidded Agent Audit Contract**: `agent_outputs` are immutable rows keyed by `agent_role`, `round_name`, and `output_type`; Judge `bid_decisions` surface evidence IDs and link source agent outputs through metadata.
- **Bidded Graph State/Routing Contract**: `BidRunState.apply_node_update` enforces node ownership and reducers; `src/bidded/orchestration/graph.py` owns the fixed LangGraph shell, preflight checks, Evidence Scout audit append, explicit edge table, bounded retry/stop policy, mocked handlers, and terminal routing.
- **Bidded Agent Tool Policy Contract**: `src/bidded/agents/tool_policy.py` is the source of truth for LLM-agent denied tools, bounded retrieval, artifact access, and orchestrator-owned side effects.
- **Bidded Agent Output Schema Contract**: `src/bidded/agents/schemas.py` is the strict Pydantic surface for Evidence Scout output, motions, rebuttals, Judge decisions, evidence refs, material claim evidence-ID validation, typed evidence gaps, validation errors, specialist role bounds, and Round 1 motion audit rows.
- **Bidded Evidence Builder Contract**: `src/bidded/evidence` converts company profile facts and retrieved tender chunks into validated Supabase-ready evidence rows with stable `tenant_key,evidence_key` upserts.

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
## 2026-04-18 19:27 CEST - US-014
- **Implemented**: Added registered tender PDF ingestion with PyMuPDF extraction, deterministic page chunks, parser status persistence, and mocked Supabase/Storage tests.
- **Files**: src/bidded/documents/pdf_ingestion.py, src/bidded/documents/__init__.py, tests/test_pdf_ingestion.py, README.md, ralph/prd.json, ralph/state.json, ralph/progress.md, ralph/CLAUDE.md
- **Key learnings**: Keep parser outcome metadata on the `documents` row while preserving page/source metadata on every `document_chunks` row for later evidence citation.
---
## 2026-04-18 19:34 CEST - US-015
- **Implemented**: Added deterministic document chunk retrieval with keyword fallback and optional mock embedding scoring.
- **Files**: src/bidded/retrieval/__init__.py, tests/test_document_chunk_retrieval.py, tests/test_project_scaffold.py, README.md, ralph/prd.json, ralph/state.json, ralph/progress.md, ralph/CLAUDE.md
- **Key learnings**: Keep retrieval usable without embedding settings while returning method and score metadata whenever chunks are ranked.
---
## 2026-04-18 19:42 CEST - US-016
- **Implemented**: Added tender evidence candidate extraction, strict validation, stable evidence-key row building, idempotent upsert persistence, and citation lookup.
- **Files**: src/bidded/evidence/tender_document.py, src/bidded/evidence/__init__.py, tests/test_tender_evidence_board.py, README.md, ralph/prd.json, ralph/state.json, ralph/progress.md, ralph/CLAUDE.md
- **Key learnings**: Keep tender evidence-board persistence behind orchestrator-callable services; candidate extraction should stay side-effect-free for Evidence Scout.
---
## 2026-04-18 19:53 CEST - US-017
- **Implemented**: Added the fixed LangGraph routing shell with preflight prerequisite validation, mocked node handlers, explicit edge-table documentation, retry routing, failed, needs_human_review, and END paths.
- **Files**: src/bidded/orchestration/graph.py, src/bidded/orchestration/__init__.py, tests/test_graph_routing_shell.py, README.md, ralph/prd.json, ralph/state.json, ralph/progress.md, ralph/CLAUDE.md
- **Key learnings**: Keep graph routing separate from real agent behavior so future node stories can replace handlers without changing topology.
---
## 2026-04-18 20:03 CEST - US-018
- **Implemented**: Added Evidence Scout six-pack retrieval requests, strict mocked Claude output validation, graph-level evidence-board citation checks, and `evidence_scout`/`evidence` agent output persistence.
- **Files**: src/bidded/agents/schemas.py, src/bidded/agents/__init__.py, src/bidded/orchestration/evidence_scout.py, src/bidded/orchestration/graph.py, tests/test_evidence_scout_node.py, README.md, ralph/prd.json, ralph/state.json, ralph/progress.md, ralph/CLAUDE.md
- **Key learnings**: Keep Evidence Scout model output validation separate from graph persistence; the graph appends audit rows only after evidence refs resolve against the board.
---
## 2026-04-18 20:24 CEST - US-019
- **Implemented**: Added evidence-locked Round 1 specialist motion handling with strict validation, formal-blocker role enforcement, and `round_1_motion` audit rows.
- **Files**: src/bidded/orchestration/specialist_motions.py, src/bidded/orchestration/graph.py, src/bidded/orchestration/__init__.py, tests/test_specialist_motion_node.py, README.md, ralph/prd.json, ralph/state.json, ralph/progress.md, ralph/CLAUDE.md
- **Key learnings**: Keep Round 1 specialist requests limited to shared evidence and scout output; append motion rows only after all four independent specialists validate.
---
## 2026-04-18 20:33 CEST - US-020
- **Implemented**: Added focused Round 2 rebuttal orchestration with cross-motion requests, Red Team focus points, strict evidence validation, and `round_2_rebuttal` audit rows.
- **Files**: src/bidded/orchestration/specialist_rebuttals.py, src/bidded/orchestration/graph.py, src/bidded/orchestration/__init__.py, tests/test_specialist_rebuttal_node.py, README.md, ralph/prd.json, ralph/state.json, ralph/progress.md
- **Key learnings**: Persist Round 2 rebuttals at the join only after all four focused outputs validate, mirroring Round 1 audit-row behavior.
---
## 2026-04-18 20:46 CEST - US-021
- **Implemented**: Added Judge decision orchestration with formal-blocker `no_bid` gating, evidence-backed verdict validation, `final_decision` audit rows, and `bid_decisions` persistence payloads.
- **Files**: src/bidded/orchestration/judge.py, src/bidded/orchestration/graph.py, src/bidded/orchestration/state.py, src/bidded/orchestration/__init__.py, tests/test_judge_decision_node.py, README.md, ralph/prd.json, ralph/state.json, ralph/progress.md, ralph/CLAUDE.md
- **Key learnings**: Keep Judge artifact validation separate from orchestrator-owned `bid_decisions` persistence and link source `agent_outputs` through metadata.
---
## 2026-04-18 20:59 CEST - US-022
- **Implemented**: Added a local worker lifecycle service and CLI that executes pending runs, persists normalized audit rows, and records terminal run status.
- **Files**: src/bidded/orchestration/worker.py, src/bidded/orchestration/__init__.py, src/bidded/cli/__init__.py, tests/test_worker_lifecycle.py, tests/test_cli.py, README.md, ralph/prd.json, ralph/state.json, ralph/progress.md
- **Key learnings**: Keep worker persistence outside LLM nodes by loading Supabase rows into typed graph state, then writing only validated agent outputs and final decisions.
---
## 2026-04-18 21:11 CEST - US-023
- **Implemented**: Added bounded two-retry stop policy for LLM graph nodes, per-role specialist retry accounting, stricter joins, persistence failure routing, and needs_human_review guardrails.
- **Files**: src/bidded/orchestration/graph.py, tests/test_graph_routing_shell.py, tests/test_evidence_scout_node.py, tests/test_specialist_motion_node.py, tests/test_specialist_rebuttal_node.py, README.md, ralph/prd.json, ralph/state.json, ralph/progress.md, ralph/CLAUDE.md
- **Key learnings**: Keep graph retry counts keyed by route node so parallel specialist retries stay role-scoped and joins remain deterministic.
---
## 2026-04-18 21:23 CEST - US-024
- **Implemented**: Added deterministic mocked worker-level end-to-end coverage for seeded demo company, fixture tender evidence, all swarm rounds, final persistence, unsupported-claim handling, and blocker gating.
- **Files**: tests/test_mocked_end_to_end_run.py, README.md, ralph/prd.json, ralph/state.json, ralph/progress.md
- **Key learnings**: Run mocked E2E coverage through `run_worker_once` with graph handlers injected and leave graph persistence as the default no-op so the worker owns `bid_decisions`.
---
## 2026-04-19 - US-025 + Anthropic agent flow fixes
- **Implemented**: Added RequirementType enum (8 values), nullable `requirement_type` on EvidenceScoutFinding and EvidenceItemState/ScoutFindingState, Supabase migration. Also fixed real-Claude flow: board-aware coercion layers (auto-resolve null evidence_id from catalog) for Evidence Scout, Round 1, Round 2, and Judge; coerce SupportedClaim title/detail → claim; skip empty-text chunks in worker; improved Anthropic system prompts with explicit JSON schema and evidence_ref examples.
- **Files**: src/bidded/agents/schemas.py, src/bidded/orchestration/state.py, src/bidded/orchestration/evidence_scout.py, src/bidded/orchestration/specialist_motions.py, src/bidded/orchestration/specialist_rebuttals.py, src/bidded/orchestration/judge.py, src/bidded/llm/anthropic_swarm.py, src/bidded/orchestration/worker.py, supabase/migrations/20260419000000_add_requirement_type.sql, ralph/prd.json, ralph/state.json, ralph/progress.md
- **Key learnings**: Pre-resolve null evidence_ids in coercion before Pydantic model_validate() so `_require_resolved_evidence_ids` passes; keep `_matching_evidence_item` as strict 3-way (reject wrong UUIDs) but let coercion fill null ones from the board. Wrong UUIDs are still rejected — only missing UUIDs are auto-resolved.
---
