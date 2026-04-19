# Ralph Progress Log
Started: 2026-04-18
---

## Codebase Patterns
> Reusable patterns discovered during implementation. Read this FIRST every session.

- **Ralph Directory**: Ralph files live in `ralph/`, not `scripts/ralph/`.
- **Current PRD Context**: Work from `ralph/state.json`; implement one `ralph/prd.json` story at a time in priority order.
- **Bidded Runtime Target**: Python package code belongs under `src/bidded`; tests and baseline gates must not require live Claude, live embeddings, or live Supabase.
- **Bidded Evidence Contract**: Material claims require excerpt-level `evidence_items` with source-specific provenance, `source_metadata.source_label`, and nullable `requirement_type`; formal blockers require exclusion/qualification tender evidence, while unsupported points become assumptions, missing_info, validation errors, or potential blockers.
- **Bidded Orchestration Contract**: The orchestrator owns Supabase writes, validation, status transitions, worker lifecycle claims, and persistence; LLM agents produce validated artifacts only.
- **Bidded Quality Gates**: Use deterministic pytest tests and Ruff for story completion; live smoke checks are optional unless a story explicitly requires them.
- **Bidded Supabase Migrations**: Keep hosted Supabase SQL under `supabase/migrations/` with deterministic pytest contract tests, demo `tenant_key = 'demo'` checks, pgvector RPC/index contracts, and no Auth/RLS unless a story adds it.
- **Bidded CLI Boundary**: Keep CLI help/package imports free of live client construction; create external clients only inside real command execution paths and keep command services injectable for tests.
- **Bidded Document Pipeline Contract**: Keep tender registration, PDF ingestion, and chunk embedding persistence in `src/bidded/documents`; registered text-PDFs use mocked Storage, PyMuPDF extraction, deterministic page chunks, optional Python-owned embeddings, and parser status metadata.
- **Bidded Prepare/Pending Run Contract**: `prepare_run.py` validates uploaded tender-document sets, runs/reuses ingestion, builds tender/company evidence, records structured preparation audit warnings/errors in run metadata, and then creates one pending `agent_runs` row through `pending_run.py`; workers still claim with `status = pending` guards.
- **Bidded Agent Audit Contract**: `agent_outputs` are immutable rows keyed by `agent_role`, `round_name`, and `output_type`; audit/run metadata carries deterministic prompt/schema/retrieval/model versions; Judge `bid_decisions` surface evidence IDs, source outputs, and replayable fixtures via metadata.
- **Bidded Graph State/Routing Contract**: `BidRunState.apply_node_update` enforces node ownership and reducers; `src/bidded/orchestration/graph.py` owns the fixed LangGraph shell, preflight checks, Evidence Scout audit append, explicit edge table, bounded retry/stop policy, mocked handlers, and terminal routing.
- **Bidded Agent Tool Policy Contract**: `src/bidded/agents/tool_policy.py` is the source of truth for LLM-agent denied tools, bounded retrieval, artifact access, and orchestrator-owned side effects.
- **Bidded Agent Output Schema Contract**: `src/bidded/agents/schemas.py` is the strict Pydantic surface for RequirementType, Evidence Scout output, motions, rebuttals, Judge decisions, typed Judge reasoning details, evidence refs, material claim evidence-ID validation, validation errors, and specialist role bounds.
- **Bidded Evidence/Retrieval Contract**: `src/bidded/retrieval` returns deterministic hybrid scores; `src/bidded/evidence` builds nullable typed evidence with excerpt-scoped glossary/extracted-term metadata, clause-section metadata, and bounded contract-clause tag/classifier metadata; recall and contract-clause audit warnings compare chunk/evidence signals to board coverage before agent requests.
- **Bidded Operator Controls Contract**: `run_controls.py` owns status/demo-trace/retry/stale-reset controls; `decision_export.py` reads persisted decisions, agent outputs, and cited evidence into local Markdown/JSON without DB mutation.
- **Bidded Golden Eval Contract**: `golden_demo_cases` exposes typed core/adversarial fixture groups selected by `bidded eval-golden --fixture-group`; `golden_runner.py` compares recorded/injected outcomes and writes deterministic reports; `live_comparison.py` adds opt-in `--compare-live --confirm-live`; `decision_diff.py` compares material fields only.

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
## 2026-04-18 22:39 CEST - US-025
- **Implemented**: Added the shared nullable RequirementType contract across tender evidence payloads, graph state, Evidence Scout findings, worker loading, and Supabase migration validation.
- **Files**: src/bidded/requirements.py, src/bidded/agents/schemas.py, src/bidded/agents/__init__.py, src/bidded/evidence/tender_document.py, src/bidded/orchestration/state.py, src/bidded/orchestration/__init__.py, src/bidded/orchestration/evidence_scout.py, src/bidded/orchestration/graph.py, src/bidded/orchestration/worker.py, supabase/migrations/20260418213000_add_evidence_requirement_type.sql, tests/test_agent_output_schemas.py, tests/test_tender_evidence_board.py, tests/test_orchestration_state.py, tests/test_evidence_scout_node.py, tests/test_worker_lifecycle.py, tests/test_supabase_migrations.py, README.md, ralph/progress.md, ralph/CLAUDE.md, ralph/prd.json, ralph/state.json
- **Key learnings**: Keep procurement requirement classification as a nullable domain enum beside legacy `category` until deterministic classifiers assign values.
---
## 2026-04-18 22:46 CEST - US-026
- **Implemented**: Added deterministic tender evidence requirement-type classification for English and Swedish procurement terms while preserving null classification for ambiguous evidence.
- **Files**: src/bidded/evidence/tender_document.py, tests/test_tender_evidence_board.py, README.md, ralph/progress.md, ralph/CLAUDE.md, ralph/prd.json, ralph/state.json
- **Key learnings**: Run specific procurement-term classifiers before generic shall/must matching so financial, exclusion, document, contract, legal, and quality evidence keep precise types.
---

## 2026-04-18 22:53 CEST - US-027
- **Implemented**: Added a curated regulatory glossary with diacritic-insensitive matching, glossary-first tender classification, and evidence metadata annotations.
- **Files**: src/bidded/evidence/regulatory_glossary.py, src/bidded/evidence/tender_document.py, src/bidded/evidence/__init__.py, tests/test_regulatory_glossary.py, tests/test_tender_evidence_board.py, README.md, ralph/progress.md, ralph/CLAUDE.md, ralph/prd.json, ralph/state.json
- **Key learnings**: Keep regulatory glossary matches inside evidence item `metadata` so source provenance remains limited to tender or company evidence.
---

## 2026-04-18 23:06 CEST - US-028
- **Implemented**: Added requirement/glossary context to Compliance and Judge requests, typed Judge reasoning details, formal-blocker requirement-type gating, and regression coverage for exclusion, financial, quality/SOSFS, submission-document, and non-gating missing-evidence cases.
- **Files**: src/bidded/agents/schemas.py, src/bidded/agents/__init__.py, src/bidded/orchestration/requirement_context.py, src/bidded/orchestration/specialist_motions.py, src/bidded/orchestration/judge.py, tests/test_agent_output_schemas.py, tests/test_specialist_motion_node.py, tests/test_judge_decision_node.py, tests/test_mocked_end_to_end_run.py, README.md, ralph/progress.md, ralph/CLAUDE.md, ralph/prd.json, ralph/state.json
- **Key learnings**: Keep formal no-bid gates tied to typed exclusion or hard qualification tender evidence; route financial, quality, and submission-document gaps through missing info, actions, or potential blockers.
---

## 2026-04-19 01:02 CEST - US-029
- **Implemented**: Added the fixed embedding model contract with settings validation, deterministic metadata helpers, mock adapter metadata, env docs, and contract tests.
- **Files**: src/bidded/embeddings.py, src/bidded/config/settings.py, src/bidded/retrieval/__init__.py, tests/test_embedding_contract.py, tests/test_document_chunk_retrieval.py, tests/test_project_scaffold.py, .env.example, README.md, ralph/progress.md, ralph/CLAUDE.md, ralph/prd.json, ralph/state.json
- **Key learnings**: Keep embedding provider/model/dimension validation separate from retrieval so ingestion and pgvector search can share the same 1536-dimension contract.
---
## 2026-04-19 01:19 CEST - US-030
- **Implemented**: Added Python-owned document chunk embedding generation, live adapter construction with mocked-call coverage, idempotent metadata skips, ingestion integration, and keyword fallback behavior.
- **Files**: src/bidded/embeddings.py, src/bidded/documents/chunk_embeddings.py, src/bidded/documents/pdf_ingestion.py, src/bidded/documents/__init__.py, src/bidded/retrieval/__init__.py, tests/test_chunk_embedding_generation.py, tests/test_embedding_contract.py, tests/test_pdf_ingestion.py, tests/test_document_chunk_retrieval.py, README.md, ralph/progress.md, ralph/CLAUDE.md, ralph/prd.json, ralph/state.json
- **Key learnings**: Store chunk embedding provenance under `document_chunks.metadata.embedding` and treat generation failures as keyword fallback unless embeddings are required.
---
## 2026-04-19 01:29 CEST - US-031
- **Implemented**: Added Supabase pgvector HNSW search migration and live retrieval RPC path with deterministic keyword fallback.
- **Files**: supabase/migrations/20260419013000_add_pgvector_search.sql, src/bidded/retrieval/__init__.py, tests/test_supabase_migrations.py, tests/test_document_chunk_retrieval.py, ralph/progress.md, ralph/CLAUDE.md, ralph/prd.json, ralph/state.json
- **Key learnings**: Keep live semantic retrieval in Supabase via `match_document_chunks`, and preserve keyword fallback when RPC/embeddings are unavailable or no embedded chunks match.
---
## 2026-04-19 01:40 CEST - US-032
- **Implemented**: Added hybrid document chunk retrieval that merges keyword, regulatory glossary, and embedding/pgvector candidates with deterministic scoring metadata and Evidence Scout request integration.
- **Files**: src/bidded/retrieval/__init__.py, src/bidded/orchestration/evidence_scout.py, tests/test_document_chunk_retrieval.py, tests/test_evidence_scout_node.py, README.md, ralph/progress.md, ralph/CLAUDE.md, ralph/prd.json, ralph/state.json
- **Key learnings**: Keep retrieval scoring centralized so graph request builders and evidence extraction share the same hybrid metadata contract.
---
## 2026-04-19 02:22 CEST - US-033
- **Implemented**: Added deterministic evidence recall warnings for important missing requirement coverage and exposed them to Evidence Scout, Compliance, and Judge requests.
- **Files**: src/bidded/orchestration/evidence_recall.py, src/bidded/orchestration/evidence_scout.py, src/bidded/orchestration/specialist_motions.py, src/bidded/orchestration/judge.py, src/bidded/orchestration/__init__.py, tests/test_evidence_recall_audit.py, tests/test_evidence_scout_node.py, tests/test_specialist_motion_node.py, tests/test_judge_decision_node.py, ralph/progress.md, ralph/CLAUDE.md, ralph/prd.json, ralph/state.json
- **Key learnings**: Keep recall audit output as structured warning/missing_info context so missing evidence coverage informs agents without becoming an automatic hard blocker.
---
## 2026-04-19 02:31 CEST - US-034
- **Implemented**: Added a demo environment doctor command for env, Supabase table, Storage probe, Anthropic availability, and secret-redacted output.
- **Files**: src/bidded/doctor.py, src/bidded/cli/__init__.py, tests/test_demo_environment_doctor.py, tests/test_cli.py, tests/test_project_scaffold.py, README.md, ralph/prd.json, ralph/state.json, ralph/progress.md
- **Key learnings**: Keep demo-health checks injectable and output-only redacted so live readiness can be tested without constructing external clients during import or help.
---
## 2026-04-19 02:49 CEST - US-035
- **Implemented**: Added deterministic replayable demo-state seeding for pending, succeeded, failed, and needs_human_review runs with fixture-owned metadata, valid evidence refs, decisions, and CLI wiring.
- **Files**: src/bidded/db/seed_demo_states.py, src/bidded/cli/__init__.py, tests/test_demo_state_seed.py, tests/test_cli.py, README.md, ralph/prd.json, ralph/state.json, ralph/progress.md
- **Key learnings**: Seed immutable audit fixtures by selecting existing fixture rows first and inserting only missing `agent_outputs`, while upserting deterministic fixture-owned source rows by ID.
---
## 2026-04-19 02:58 CEST - US-036
- **Implemented**: Hardened worker startup with a conditional pending-to-running claim, terminal/double-claim no-op handling, and deterministic lifecycle coverage.
- **Files**: src/bidded/orchestration/worker.py, tests/test_worker_lifecycle.py, README.md, ralph/prd.json, ralph/state.json, ralph/progress.md, ralph/CLAUDE.md
- **Key learnings**: Claim agent runs with a `status = pending` compare-and-swap before loading graph state so duplicate workers stop without touching audit artifacts.
---
## 2026-04-19 03:09 CEST - US-037
- **Implemented**: Added local operator run controls for status snapshots, retry-run lineage, stale running-run reset, succeeded-run force protection, and mocked persistence failures.
- **Files**: src/bidded/orchestration/run_controls.py, src/bidded/orchestration/__init__.py, src/bidded/cli/__init__.py, tests/test_operator_run_controls.py, tests/test_cli.py, README.md, ralph/prd.json, ralph/state.json, ralph/progress.md
- **Key learnings**: Keep operator recovery separate from worker execution; retries create new pending rows, while stale resets use guarded status updates with explicit operator reasons.
---
## 2026-04-19 03:23 CEST - US-038
- **Implemented**: Added an injectable `demo-smoke` flow and CLI covering seed, PDF fallback/registration, ingestion, evidence creation, pending run, worker execution, and decision readback with mocked-default/live-LLM flag handling.
- **Files**: src/bidded/demo_smoke.py, src/bidded/cli/__init__.py, tests/test_demo_smoke.py, tests/test_cli.py, README.md, ralph/prd.json, ralph/state.json, ralph/progress.md
- **Key learnings**: Keep smoke orchestration injectable and read verdicts back from `bid_decisions` instead of treating worker return values as persisted readback.
---
## 2026-04-19 03:35 CEST - US-039
- **Implemented**: Added compact worker `demo_trace` metadata, parsed run-status trace snapshots, and verbose CLI rendering that highlights the latest failed or incomplete step.
- **Files**: src/bidded/orchestration/worker.py, src/bidded/orchestration/run_controls.py, src/bidded/orchestration/__init__.py, src/bidded/cli/__init__.py, tests/test_worker_lifecycle.py, tests/test_operator_run_controls.py, tests/test_cli.py, README.md, ralph/prd.json, ralph/state.json, ralph/progress.md
- **Key learnings**: Keep demo traces as compact top-level run metadata with sanitized step/status/timing/error-code fields, leaving raw prompts and private context out of operator diagnostics.
---
## 2026-04-19 03:46 CEST - US-040
- **Implemented**: Added `export-decision` to write persisted final decisions as readable Markdown and stable JSON with cited evidence and audit-output summaries.
- **Files**: src/bidded/orchestration/decision_export.py, src/bidded/orchestration/__init__.py, src/bidded/cli/__init__.py, tests/test_decision_export.py, tests/test_cli.py, README.md, ralph/prd.json, ralph/state.json, ralph/progress.md
- **Key learnings**: Keep decision exports read-only over `bid_decisions`, `agent_outputs`, and `evidence_items`, with local files as the only side effect.
---
## 2026-04-19 03:53 CEST - US-041
- **Implemented**: Added a demo operator runbook for setup, live smoke, worker/status/export flow, recovery, fallback replay, and mocked-vs-live test policy.
- **Files**: docs/demo-runbook.md, README.md, ralph/prd.json, ralph/state.json, ralph/progress.md
- **Key learnings**: Keep demo operations CLI-first and document live smoke as manual opt-in while deterministic gates stay mocked.
---
## 2026-04-19 04:00 CEST - US-042
- **Implemented**: Added typed deterministic golden demo cases covering core verdict paths, missing evidence handling, conflicting evidence review, and unsupported-claim rejection.
- **Files**: src/bidded/fixtures/golden_cases.py, src/bidded/fixtures/__init__.py, tests/test_golden_demo_cases.py, README.md, ralph/prd.json, ralph/state.json, ralph/progress.md
- **Key learnings**: Keep golden eval fixtures typed as evidence-board cases so future eval runners can validate verdicts and evidence refs without live services.
---
## 2026-04-19 04:10 CEST - US-043
- **Implemented**: Added deterministic golden eval execution, mismatch reporting, stable JSON output, and the `eval-golden` CLI for all cases or one selected case.
- **Files**: src/bidded/evals/, src/bidded/cli/__init__.py, tests/test_golden_eval_runner.py, tests/test_cli.py, README.md, ralph/prd.json, ralph/state.json, ralph/progress.md
- **Key learnings**: Keep eval runners live-service-free by comparing recorded or injected outcomes against typed golden fixture expectations before later scorer/export stories deepen the metrics.
---
## 2026-04-19 04:21 CEST - US-044
- **Implemented**: Added golden eval evidence coverage scoring for material claims, tender/company/comparison citation requirements, unsupported claim counts, JSON/CLI reporting, and deterministic tests.
- **Files**: src/bidded/evals/golden_runner.py, src/bidded/evals/__init__.py, src/bidded/cli/__init__.py, tests/test_golden_eval_runner.py, tests/test_cli.py, README.md, ralph/progress.md, ralph/prd.json, ralph/state.json
- **Key learnings**: Treat assumptions, missing_info, and potential_evidence_gaps as allowed uncited notes while material findings, blockers, Judge decisions, risks, and actions require scored citation coverage.
---
## 2026-04-19 04:37 CEST - US-045
- **Implemented**: Added allowed-verdict regression checks, formal blocker no-bid enforcement, missing-evidence non-gating outcomes, and CLI diagnostics for golden eval failures.
- **Files**: src/bidded/fixtures/golden_cases.py, src/bidded/evals/golden_runner.py, src/bidded/cli/__init__.py, tests/test_golden_demo_cases.py, tests/test_golden_eval_runner.py, tests/test_cli.py, README.md, ralph/prd.json, ralph/state.json, ralph/progress.md
- **Key learnings**: Model multi-verdict eval tolerance explicitly in fixture expectations instead of weakening blocker, missing-info, or evidence-reference assertions.
---
## 2026-04-19 04:43 CEST - US-046
- **Implemented**: Added deterministic prompt/schema/retrieval/model version metadata for worker audit rows and golden eval JSON/CLI output, with non-blocking eval warnings for legacy missing metadata.
- **Files**: src/bidded/versioning.py, src/bidded/orchestration/worker.py, src/bidded/evals/golden_runner.py, src/bidded/cli/__init__.py, tests/test_worker_lifecycle.py, tests/test_golden_eval_runner.py, tests/test_cli.py, ralph/prd.json, ralph/state.json, ralph/progress.md
- **Key learnings**: Keep version provenance centralized and normalize legacy/missing eval metadata to defaults while surfacing warnings only in eval output.
---
## 2026-04-19 04:57 CEST - US-047
- **Implemented**: Added normalized decision diffing for eval JSON, exported decisions, and persisted run IDs with text/JSON CLI output and strict exit behavior.
- **Files**: src/bidded/evals/decision_diff.py, src/bidded/evals/golden_runner.py, src/bidded/evals/__init__.py, src/bidded/cli/__init__.py, tests/test_decision_diff.py, tests/test_golden_eval_runner.py, tests/test_cli.py, README.md, ralph/prd.json, ralph/state.json, ralph/progress.md
- **Key learnings**: Keep eval comparison on normalized structured decision fields so prose and ordering changes do not create material diffs.
---
## 2026-04-19 05:07 CEST - US-048
- **Implemented**: Added adversarial golden fixture groups, six category-specific synthetic cases, eval/CLI group selection, and failing-output regression examples for each category.
- **Files**: src/bidded/fixtures/golden_cases.py, src/bidded/fixtures/__init__.py, src/bidded/evals/golden_runner.py, src/bidded/cli/__init__.py, tests/test_golden_demo_cases.py, tests/test_golden_eval_runner.py, tests/test_cli.py, README.md, ralph/prd.json, ralph/state.json, ralph/progress.md
- **Key learnings**: Keep adversarial eval pressure as typed fixture metadata plus injected bad outcomes so edge-case regressions stay deterministic and live-service-free.
---
## 2026-04-19 05:18 CEST - US-049
- **Implemented**: Added deterministic golden eval JSON/Markdown report exports with aggregate summaries, failed-case details, CLI wiring, and regression coverage.
- **Files**: src/bidded/evals/golden_runner.py, src/bidded/evals/__init__.py, src/bidded/cli/__init__.py, tests/test_golden_eval_runner.py, tests/test_cli.py, README.md, ralph/prd.json, ralph/state.json, ralph/progress.md
- **Key learnings**: Keep eval report exports as pure render/write helpers over `GoldenEvalReport` so CLI and tests share deterministic report payloads.
---
## 2026-04-19 05:36 CEST - US-050
- **Implemented**: Added opt-in live-vs-mock golden eval comparison with Anthropic adapter injection, unavailable-credential handling, JSON/Markdown reports, CLI flags, and deterministic tests.
- **Files**: src/bidded/evals/live_comparison.py, src/bidded/evals/__init__.py, src/bidded/cli/__init__.py, tests/test_live_golden_eval_comparison.py, tests/test_cli.py, README.md, ralph/prd.json, ralph/state.json, ralph/progress.md
- **Key learnings**: Keep live eval rehearsal behind explicit CLI confirmation and model it as a comparison report over the deterministic mock baseline so normal evals remain live-service-free.
---
## 2026-04-19 05:45 CEST - US-051
- **Implemented**: Added deterministic clause-aware tender segmentation and clause-section metadata on tender evidence items while preserving source provenance.
- **Files**: src/bidded/evidence/tender_document.py, src/bidded/evidence/__init__.py, tests/test_tender_evidence_board.py, README.md, ralph/progress.md, ralph/CLAUDE.md, ralph/prd.json, ralph/state.json
- **Key learnings**: Store clause context under evidence item metadata so `source_metadata` remains the source-label provenance contract.
---
## 2026-04-19 05:53 CEST - US-052
- **Implemented**: Added the fixed contract clause tag taxonomy, deterministic diacritic-insensitive matching, and evidence metadata annotations without widening `RequirementType`.
- **Files**: src/bidded/evidence/contract_clause_tags.py, src/bidded/evidence/tender_document.py, src/bidded/evidence/__init__.py, tests/test_contract_clause_tags.py, tests/test_tender_evidence_board.py, README.md, ralph/progress.md, ralph/CLAUDE.md, ralph/prd.json, ralph/state.json
- **Key learnings**: Keep contract-clause specificity in evidence metadata (`contract_clause_ids`/`contract_clause_matches`) while `requirement_type` stays broad and stable.
---
## 2026-04-19 06:01 CEST - US-053
- **Implemented**: Added deterministic structured contract-term extraction for SEK/Mkr amounts, recurrence/cap phrases, and day deadlines on tender evidence metadata.
- **Files**: src/bidded/evidence/contract_terms.py, src/bidded/evidence/tender_document.py, src/bidded/evidence/__init__.py, tests/test_tender_evidence_board.py, README.md, ralph/progress.md, ralph/CLAUDE.md, ralph/prd.json, ralph/state.json
- **Key learnings**: Keep numeric/timing contract facts under `metadata.extracted_terms` so agents and later audits can reason over terms without parsing prose again.
---
## 2026-04-19 06:07 CEST - US-054
- **Implemented**: Annotated tender evidence clause tags from clause context so rows can carry clause-section, contract-clause, extracted-term, and glossary metadata while citations stay excerpt-level.
- **Files**: src/bidded/evidence/tender_document.py, tests/test_tender_evidence_board.py, ralph/progress.md, ralph/CLAUDE.md, ralph/prd.json, ralph/state.json
- **Key learnings**: Match deterministic contract-clause tags against clause heading/body context, but keep extracted terms and glossary matches excerpt-scoped to avoid changing citation provenance.
---
## 2026-04-19 06:24 CEST - US-055
- **Implemented**: Added bounded contract-clause classifier request/response schemas, deterministic mock adapter, citation and allow-list validation, low-confidence unknown fallback, and tender evidence metadata integration.
- **Files**: src/bidded/evidence/contract_clause_classifier.py, src/bidded/evidence/__init__.py, src/bidded/evidence/tender_document.py, tests/test_contract_clause_classifier.py, tests/test_tender_evidence_board.py, ralph/progress.md, ralph/CLAUDE.md, ralph/prd.json, ralph/state.json
- **Key learnings**: Keep LLM-assisted clause classification as optional evidence-board metadata bounded by fixed taxonomy IDs and existing evidence/provenance citations.
---
## 2026-04-19 06:35 CEST - US-056
- **Implemented**: Added deterministic contract-clause coverage audit warnings for missing clause bodies, untagged contract-risk signals, and missing extracted contract terms, then exposed them to Scout, Round 1 specialists, and Judge requests.
- **Files**: src/bidded/orchestration/contract_clause_audit.py, src/bidded/orchestration/evidence_scout.py, src/bidded/orchestration/specialist_motions.py, src/bidded/orchestration/judge.py, src/bidded/orchestration/state.py, src/bidded/orchestration/worker.py, tests/test_contract_clause_coverage_audit.py, tests/test_worker_lifecycle.py, ralph/progress.md, ralph/CLAUDE.md, ralph/prd.json, ralph/state.json
- **Key learnings**: Keep contract-clause audit findings as request-scoped warning context backed by evidence metadata, not graph blockers or verdict gates.
---
## 2026-04-19 06:49 CEST - US-057
- **Implemented**: Added prepare-run orchestration and CLI for uploaded tender document sets, covering validation, ingestion reuse, evidence creation, multi-document pending runs, parser failure blocking, and no agent execution.
- **Files**: src/bidded/orchestration/prepare_run.py, src/bidded/orchestration/pending_run.py, src/bidded/orchestration/__init__.py, src/bidded/cli/__init__.py, tests/test_prepare_run.py, tests/test_pending_run_context.py, tests/test_cli.py, README.md, ralph/progress.md, ralph/CLAUDE.md, ralph/prd.json, ralph/state.json
- **Key learnings**: Keep preparation as an orchestrator-owned pre-worker step that completes evidence artifacts before inserting a pending run with the selected document set.
---
## 2026-04-19 07:04 CEST - US-058
- **Implemented**: Added structured preparation audits with info/warning/error findings, blocking error checks, warning metadata propagation, CLI rendering, and deterministic coverage.
- **Files**: src/bidded/orchestration/prepare_run.py, src/bidded/orchestration/pending_run.py, src/bidded/orchestration/worker.py, src/bidded/orchestration/__init__.py, src/bidded/cli/__init__.py, src/bidded/evidence/tender_document.py, src/bidded/evidence/company_profile.py, tests/test_prepare_run.py, tests/test_cli.py, tests/test_worker_lifecycle.py, README.md, ralph/progress.md, ralph/CLAUDE.md, ralph/prd.json, ralph/state.json
- **Key learnings**: Store preparation warnings in `agent_runs.metadata.preparation_audit` so workers can expose them through graph context without letting LLM nodes mutate preparation state.
---
