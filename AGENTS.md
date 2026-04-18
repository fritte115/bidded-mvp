# Bidded Agent Guide

Keep `AGENTS.md` and `CLAUDE.md` identical so Codex, Claude, and Ralph follow the same workflow.

## Why
Bidded is a hackathon-scoped agent core for bid/no-bid decisions in Swedish public procurement. It ingests a user-provided English text-PDF, compares requirements against a seeded IT consultancy profile, builds a shared evidence board, runs a traceable multi-agent review, and persists `bid`, `no_bid`, or `conditional_bid`.

## Current State
- The root Python application is not scaffolded yet. Planned app code should live under `src/bidded`.
- Ralph is the active story runner. Its files live in `ralph/`.
- `brain-in-the-fish/` is a separate Rust evidence-scoring/reference codebase in this tree. Do not refactor it unless the task explicitly targets it.

## Stack
- Runtime: Python, LangGraph, Claude via Anthropic API.
- Backend/data: hosted Supabase Postgres, Supabase Storage, SQL migrations, JSONB where agent/domain payloads need flexibility.
- Schemas/validation: Pydantic.
- Documents: text-based PDF extraction only.
- Retrieval: deterministic keyword/full-text fallback, optional embeddings later.
- Quality: pytest and Ruff for Bidded; Cargo only when touching `brain-in-the-fish/`.
- Current automation: Make + Ralph + Claude CLI. `.env` carries local secrets such as `ANTHROPIC_API_KEY` and Supabase credentials.

## Workflow
- For Ralph story work, always read `ralph/state.json` first. Work only on `currentStory`.
- Then read the top `## Codebase Patterns` block and recent tail of `ralph/progress.md`, plus the matching story in `ralph/prd.json`.
- Implement one logical story/change at a time. Keep changes small and reviewable.
- TDD is mandatory for production behavior changes, especially inside the Ralph loop. Write or update the failing test first, implement the smallest passing change, then refactor.
- Do not mark a Ralph story as passing until its acceptance criteria are covered by deterministic tests or an explicitly documented exception.
- Test what you touch with the narrowest useful command, then run the relevant gate before finishing: `.venv/bin/pytest -q`, `.venv/bin/ruff check .`, or `cargo test` inside `brain-in-the-fish/` when applicable.
- Commit after each completed unit of work and after each standalone change once the relevant tests or checks have passed. Keep commits small, scoped, and free of unrelated files or secrets.
- Every Ralph story that is marked complete must be committed in the same session; never leave a completed `passes: true` story only in the working tree.
- For completed Ralph stories, append reusable learnings to `ralph/progress.md`, update `ralph/prd.json`, update `ralph/state.json`, then commit the story changes.

## TDD Policy
- Default loop: red, green, refactor.
- Start with the acceptance criteria in `ralph/prd.json` and encode the expected behavior in tests before implementation.
- If existing behavior is unclear, add characterization tests first, then continue with red-green-refactor.
- Use deterministic mocks for Claude, embeddings, Supabase, and PDF processing wherever possible.
- Exceptions: docs-only changes, formatting-only changes, generated files, and emergency hotfixes. Hotfix tests must be added immediately after the fix.

## Core Rules
- Determinism first: same inputs and source versions should produce the same outputs.
- Evidence by default: every material claim must cite excerpt-level `evidence_items`.
- Unsupported material claims belong in `assumptions`, `missing_info`, validation errors, or potential blockers, not prose that sounds factual.
- v1 evidence source types are exactly `tender_document` and `company_profile`.
- Tender evidence must trace to document, chunk, page, excerpt, and source label.
- Company evidence must trace to company, field path, excerpt, and source label.
- Use typed state and Pydantic schemas for agent outputs, verdicts, blockers, confidence, evidence refs, rebuttals, and Judge decisions.
- The orchestrator owns validation, Supabase writes, status transitions, persistence, and evidence-board mutation.
- Specialist agents read evidence and produce validated artifacts. They do not mutate the shared evidence board.

## Swarm Policy
- Ingestion, chunking, and evidence-board preparation happen before the LangGraph swarm starts.
- Evidence Scout extracts facts but does not recommend bid/no-bid.
- Round 1 specialists run independently from the same evidence board: Compliance, Win Strategist, Delivery/CFO, and Red Team.
- Round 2 is the first point where agents may read each other's validated motions.
- Judge runs only after all required motions and rebuttals are valid.
- Formal compliance blockers can gate to `no_bid`; otherwise the Judge must explain evidence-backed discretion.
- Use `conditional_bid` when a defensible recommendation exists with explicit next actions. Use `needs_human_review` only when critical missing or conflicting evidence prevents a defensible verdict.

## Operational Safety
- Never commit `.env`, secrets, full database URLs, service role keys, private customer data, or generated files containing secrets.
- Keep Supabase service role credentials server-side/local-worker only; never design them into UI code.
- Do not require live Claude, live embeddings, or live Supabase for normal tests; use deterministic mocks and fixtures.
- Schema changes go through migrations, not ad hoc database edits.
- Read existing files before editing and do not overwrite user changes in the working tree.
- If a command needs elevated permission, request the narrowest task-specific prefix.

## Do Not
- Do not build OCR, DOCX ingestion, tender search/import, auth/RLS, or a full Next.js/React UI for this PRD.
- Do not let LLM agents use arbitrary web search, filesystem access, code execution, direct database mutation, or new external sources in v1.
- Do not treat missing company evidence as automatic `no_bid`; route it to missing info, assumptions, actions, or blockers.
- Do not pass private free-form context between agents; handoffs are validated artifacts in shared state.
- Do not overwrite append-only artifacts except through explicit typed reducers.
- Do not mix broad refactors with feature or story work unless requested.

## Useful Commands
```bash
cp .env.example .env
make ralph

# After Python scaffold exists:
.venv/bin/pytest -q
.venv/bin/ruff check .

# Only when touching brain-in-the-fish:
cd brain-in-the-fish
cargo test
```
