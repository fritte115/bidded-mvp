# Ralph Progress Log
Started: 2026-04-18
---

## Codebase Patterns
> Reusable patterns discovered during implementation. Read this FIRST every session.
- **Current PRD Context**: This repo is for Bidded branch `ralph/bidded-swarm-core`; implement stories from `ralph/prd.json` in priority order.
- **Bidded Scope**: Build a hackathon-scoped Python + LangGraph agent core backed by hosted Supabase; do not build full Next.js/React UI, auth/RLS, OCR, DOCX, live embedding dependency, or tender search in this PRD.
- **Bidded Data Contract**: Use Supabase SQL migrations and Storage with hybrid tables `companies`, `tenders`, `documents`, `document_chunks`, `evidence_items`, `agent_runs`, `agent_outputs`, and `bid_decisions`.
- **Bidded Evidence Policy**: All material agent claims must cite excerpt-level `evidence_items`; unsupported material claims belong in `assumptions`, `missing_info`, validation errors, or potential blockers.
- **Bidded Evidence Sources**: v1 evidence source types are exactly `tender_document` and `company_profile`; tender evidence must cite document/chunk/page/excerpt/source label, while company evidence must cite company/field_path/excerpt/source label.
- **Bidded Evidence Board Ownership**: Evidence Scout may propose evidence candidates, but validation and persistence are owned by the orchestrator; specialist agents must not mutate the evidence board.
- **Bidded State Model**: Use typed shared `BidRunState` as the runtime source of truth. Handoffs are validated artifacts in state, not free-form private context passed between agents.
- **Bidded Node Ownership**: Each graph node may write only its owned fields; validated evidence, motions, rebuttals, validation errors, agent outputs, and final decisions are append-only artifacts unless a typed reducer explicitly merges parallel outputs.
- **Bidded Overwrite Policy**: Only runtime control fields such as `status`, `current_step`, `retry_counts`, `last_error`, and working retrieval results may be overwritten during a run.
- **Bidded Swarm Flow**: Evidence Scout runs first, then Compliance, Win, Delivery/CFO, and Red Team Round 1 motions run independently, then focused rebuttals, then Judge decision.
- **Bidded Round Visibility**: Round 1 specialists read the same shared evidence board and do not see each other's motions; Round 2 is the first point where specialists can read other agents' validated motions.
- **Bidded Tool Policy**: LLM agents do not get arbitrary web search, filesystem access, code execution, direct database mutation, or permission to introduce new external sources in v1; retrieval tools must be bounded to the current `agent_run`, `tender_id`, and `company_id`, while the orchestrator owns Supabase writes, status transitions, validation, and persistence.
- **Bidded Routing Preconditions**: Document registration, PDF ingestion/chunking, and evidence-board preparation happen before the LangGraph swarm starts; graph preflight verifies parsed documents and non-empty evidence but does not run ingestion.
- **Bidded Routing & Stops**: LangGraph routing is fixed and orchestrator-controlled with an explicit edge table. END only after a validated Judge decision is persisted; fail on missing inputs, unparsed/parser_failed documents, empty evidence board, invalid required artifacts after retries, or persistence failure.
- **Bidded Join & Retry Policy**: Max 2 retries per LLM node, scoped per agent role for parallel Round 1 and Round 2. Judge runs only after all four required motions and all four required rebuttals are valid.
- **Bidded Conditional vs Review**: Use `conditional_bid` when Judge can make a defensible bid recommendation with explicit next actions; use `needs_human_review` only when a technically valid run has critical missing or conflicting evidence that prevents a defensible final verdict.
- **Bidded Quality Gates**: Prefer deterministic mocked LLM/embedding tests with `pytest` plus `ruff check`; live Claude smoke is optional and must not be required for story completion.
