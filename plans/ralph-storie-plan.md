# PRD Plan: Bidded Swarm Core

## Summary
Write `ralph/prd.json` for a hackathon-scoped, Supabase-driven agent core for **bidded**. The system ingests a user-provided English text-PDF for a Swedish public procurement, uses seeded company facts for a larger IT consultancy, builds a validated shared evidence board, runs an evidence-locked LangGraph swarm, and persists a traceable bid/no-bid/conditional decision.

The story plan is intentionally modular: data schema, graph state, tool policy, evidence validation, routing, stop conditions, agent nodes, worker lifecycle, and Lovable handoff are separate stories. This gives Ralph enough room to implement thoughtfully while preventing it from inventing risky swarm-control assumptions.

## Key Interfaces
- **Runtime**: Python + LangGraph worker, Claude via `ANTHROPIC_API_KEY`, hosted Supabase demo project.
- **Supabase tables**: `companies`, `tenders`, `documents`, `document_chunks`, `evidence_items`, `agent_runs`, `agent_outputs`, `bid_decisions`.
- **Evidence source types**: v1 supports exactly `tender_document` and `company_profile`.
- **Evidence board**: Evidence Scout may propose candidates; validation and persistence are owned by the orchestrator.
- **State model**: typed shared `BidRunState`; handoffs are validated artifacts in state, not free-form private context.
- **Overwrite policy**: only runtime control fields like `status`, `current_step`, `retry_counts`, `last_error`, and working retrieval results may be overwritten.
- **Routing precondition**: document registration, PDF ingestion/chunking, and evidence-board preparation happen before the LangGraph swarm starts.
- **Swarm policy**: Round 1 specialists read the same evidence board independently; Round 2 is the first point where agents see each other's motions.
- **Tool policy**: LLM agents do not get arbitrary web, filesystem, code execution, direct database mutation, or permission to introduce new external sources in v1; retrieval is bounded to the current `agent_run`, `tender_id`, and `company_id`.
- **Stop policy**: max 2 retries per LLM node; Judge runs only after all required motions/rebuttals are valid; END only after a validated Judge decision is persisted.
- **Conditional vs review**: use `conditional_bid` when Judge can make a defensible recommendation with next actions; use `needs_human_review` only when critical missing or conflicting evidence prevents a defensible verdict.

## User Stories
| ID | Title | Description |
|---|---|---|
| US-001 | Scaffold Python agent core | Create Python package, dependencies, config, CLI shell, `pytest`, and `ruff`. |
| US-002 | Add core Supabase schema | Create `companies`, `tenders`, and `documents` with Storage metadata and demo-tenant assumptions. |
| US-003 | Add agent audit schema | Create `agent_runs`, `agent_outputs`, and `bid_decisions` for status, outputs, decisions, validation errors, and metadata. |
| US-004 | Add chunk evidence schema | Create `document_chunks` and `evidence_items`, including source metadata and nullable/vector-ready embedding support. |
| US-005 | Define graph state schema | Define typed `BidRunState`, runtime vs persisted fields, statuses, and serialization behavior. |
| US-006 | Enforce state ownership rules | Define node read/write ownership, append-only artifacts, overwrite policy, and parallel reducers. |
| US-007 | Define agent tool policies | Lock which nodes can retrieve, read evidence, call Claude, create evidence candidates, write outputs, and mutate Supabase. |
| US-008 | Define agent output schemas | Define schemas for motions, rebuttals, Judge decisions, votes, blockers, confidence, missing info, and next actions. |
| US-009 | Validate evidence claims | Require evidence IDs for material claims and route unsupported points to assumptions, missing info, evidence gaps, or errors. |
| US-010 | Seed demo company profile | Seed one larger IT consultancy with certifications, references, CV summaries, revenue, capacity, geography, and economics. |
| US-011 | Convert company facts to evidence | Convert seeded company facts into stable `company_profile` evidence items with traceable source metadata. |
| US-012 | Register demo tender PDF | Upload a user-provided English text-PDF to Supabase Storage and create tender/document rows. |
| US-013 | Create pending run context | Create a pending `agent_run` linked to tender/company with English output and Swedish procurement context. |
| US-014 | Ingest PDF chunks | Extract text from text-based PDFs, store deterministic page-referenced chunks, and mark parse success/failure. |
| US-015 | Add retrieval fallback | Implement keyword/full-text top-K retrieval plus deterministic mock embedding support without requiring a live provider. |
| US-016 | Build tender evidence board | Validate and persist excerpt-level tender evidence from chunks with stable evidence keys and duplicate prevention. |
| US-017 | Add graph routing shell | Implement fixed LangGraph topology with preflight checks, an explicit edge table, conditional edges, retry routing, failure routing, and END. |
| US-018 | Implement Evidence Scout node | Extract deadlines, shall requirements, qualification criteria, evaluation criteria, contract risks, and required submission docs with citations. |
| US-019 | Implement specialist motions | Run Compliance, Win, Delivery/CFO, and Red Team Round 1 motions independently from the shared evidence board. |
| US-020 | Implement focused rebuttals | Run Round 2 focused critiques over top disagreements, blockers, unsupported claims, and missing information. |
| US-021 | Implement Judge decision | Produce final `bid`, `no_bid`, or `conditional_bid` using formal compliance gates and evidence-backed discretion. |
| US-022 | Add worker lifecycle CLI | Run a specific or oldest pending `agent_run`, transition statuses, log progress, and persist outputs via the orchestrator. |
| US-023 | Add retry stop policy | Enforce bounded retries and stop conditions for success, failed, and needs-human-review outcomes. |
| US-024 | Test mocked end-to-end run | Verify the full mocked flow: seed, tender, chunks, evidence, motions, rebuttals, Judge, persistence, and evidence-lock behavior. |
| US-025 | Prepare Lovable handoff | Document Supabase contract, run statuses, display sections, demo fixtures, and UI non-goals for Lovable. |

## Evidence Rules
- `tender_document` evidence requires `document_id`, `chunk_id`, page reference, excerpt, and source label.
- `company_profile` evidence requires `company_id`, `field_path`, excerpt, and source label.
- Specialist agents may not mutate the shared evidence board.
- Validated evidence, motions, rebuttals, validation errors, agent outputs, and final decisions are append-only unless a typed reducer explicitly merges parallel outputs.
- If a specialist lacks a source, it must write `missing_info` or `potential_evidence_gaps`, not invent evidence.
- Claims comparing a tender requirement to company capability should cite both tender and company evidence when both are available.

## Test Plan
- Use `pytest` for deterministic unit/integration tests with mocked LLM outputs and mocked/deterministic embeddings.
- Use `ruff check` as the lint quality gate for Python stories.
- Add tests for graph state ownership, reducers, append-only behavior, routing, retry exhaustion, empty evidence board, failed status, needs-human-review, and final END.
- Add routing tests proving the swarm graph does not run ingestion, fails on missing/unparsed/parser_failed documents or empty evidence, and only runs Judge after all required Round 1 motions and Round 2 rebuttals are valid.
- Do not require live Claude, live embedding provider, OCR, DOCX, auth/RLS, or Next.js/React for story completion.

## Assumptions
- Input/output language is English, but procurement logic is Swedish public procurement.
- The real procurement PDF is supplied by the user; no tender search/import integration is in v1.
- Company data is seeded structured mock data for a larger IT consultancy.
- Hosted Supabase is the demo backend; worker uses service credentials locally.
- Lovable is used as a later thin UI layer over Supabase, not as the agent runtime.
