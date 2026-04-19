# Ralph Agent Instructions

> **Ralph directory: `ralph/`** — All Ralph files live here. Your working directory is the repo root; always use the `ralph/` prefix for Ralph file operations.

## Step 0: Read State

1. Read `ralph/state.json` first.
   - If it exists, orient from `currentStory`, `storyTitle`, `nextAction`, `branch`, and `compactionNeeded`.
   - If it is missing, read `ralph/BOOTSTRAP.md`, create `ralph/state.json`, then continue.
2. If `compactionNeeded` is `true`, read `ralph/COMPACTION.md`, compact progress, update state, commit that maintenance change, and stop. Do not work on a story in the same session.
3. Continue to the current story only after state is understood.

## Story Workflow

1. Confirm the current Git branch matches `state.json.branch`; create or switch only if needed.
2. Read the `## Codebase Patterns` block at the top of `ralph/progress.md`, then read the recent `## Session Log` tail. Keep reads bounded unless compacting.
3. Read only the current story from `ralph/prd.json`. Stories live under `.userStories[]`; the current story is `state.json.currentStory`; do not use `.stories[]` and do not choose a different story.
4. If the story has `iterationMode`, read `ralph/ITERATIVE.md` before implementation.
5. Implement exactly one story or one maintenance task.
6. Run the narrowest useful tests/checks, then the relevant story gate. For Bidded, normal completion must not require live Claude, live embeddings, or live Supabase unless the story explicitly says it is a smoke/manual check.
7. If UI behavior is touched, verify it in a browser when tooling is available; otherwise record the gap in `ralph/progress.md`.
8. Append a concise session entry to `ralph/progress.md` using `ralph/PROGRESS-GUIDE.md`.
9. Promote only genuinely reusable learnings to the top `## Codebase Patterns` block or to `## Institutional Memory` below.
10. When a story is complete, update `ralph/prd.json` by setting only that story's `passes` and final compact `notes`.
11. Update `ralph/state.json` using the state rules below.
12. Commit all story or maintenance changes after progress, PRD, and state are final. Every story marked complete with `passes: true` must be committed in the same session. Keep commits small, scoped, and free of secrets.
13. Stop after the commit. The shell loop starts the next session.

## State Update Rules

At the end of every non-compaction story session:

1. Scan `ralph/prd.json` for the next incomplete story, ordered by `priority`.
2. Set `currentStory` to that story ID, or `null` if all stories pass.
3. Set `storyTitle` to that story title, or `"all stories complete"`.
4. Set `nextAction`:
   - standard story: `"implement"`
   - iterative story before first pass: `"iteration 1/M"`
   - iterative story mid-stream: `"iteration N/M"` or `"iteration N/M (review pass)"`
   - all complete: `"all stories complete"`
5. Keep `branch` unless the PRD branch intentionally changes.
6. Estimate `progressTokens` from `ralph/progress.md` at roughly 15 tokens per line.
7. Set `compactionNeeded` to `true` only when `progressTokens` exceeds `compactionThreshold`.
8. Set `lastUpdated` to today's date.

## Critical Rules

1. Always read `ralph/state.json` first.
2. Always work on exactly one story per Ralph session.
3. Always append to `ralph/progress.md`; never replace it except during explicit compaction.
4. Always keep `ralph/progress.md`, `ralph/prd.json`, and `ralph/state.json` consistent before committing a completed story.
5. Never leave a completed Ralph story only in the working tree; if `passes: true` advanced, there must be a corresponding commit before the session ends.
6. Never commit `.env`, secrets, full database URLs, service role keys, private tender data, or generated files containing secrets.
7. Do not carry over conventions from old projects unless they are restated in Bidded's README, PRD, AGENTS.md, or this file.
8. The orchestrator owns Supabase writes, validation, status transitions, and persistence; LLM agents produce validated artifacts only.
9. Story tests should use deterministic mocks for Claude, embeddings, Supabase, and PDF processing unless a story explicitly calls for live smoke validation.

## Institutional Memory

> Format: `- **Name**: description` | Budget: 20 lines max.
> Store only Bidded-specific conventions or Ralph workflow gotchas that are useful across multiple future stories.

- **Ralph Directory**: This repo uses `ralph/`, not `scripts/ralph/`; all Ralph instructions, PRD, state, and progress paths must use the root-level `ralph/` prefix.
- **PRD Shape**: Ralph PRD stories live under `.userStories[]`, not `.stories[]`; queries and scripts must select the current story from `.userStories[]`.
- **Bidded Source Target**: Application code for PRD stories should be scaffolded under `src/bidded` with tests that can run without live external services.
- **Bidded Gate Baseline**: Until a full `make check` exists, story completion should at minimum satisfy deterministic `pytest` coverage for touched behavior plus `ruff check`.
- **Bidded Supabase Migrations**: Timestamped SQL files live under `supabase/migrations/`; contract-test schema assumptions, keep v1 demo tables pinned to `tenant_key = 'demo'`, and avoid Auth/RLS unless a story adds it.
- **Bidded CLI Boundary**: Keep CLI help/package imports free of live client construction; create external clients only inside real command execution paths and keep command services injectable for tests.
- **Bidded Agent Audit Contract**: Persist agent outputs as immutable audit rows keyed by `agent_role`, `round_name`, and `output_type`; final decisions expose Judge `evidence_ids`, and replayable fixtures must be scoped through metadata.
- **Bidded Evidence Schema Contract**: `evidence_items` use `tender_document`/`company_profile` source types with explicit nullable provenance columns, `source_metadata.source_label`, and nullable `requirement_type`; `document_chunks` keep nullable pgvector embeddings.
- **Bidded Graph State/Routing Contract**: `BidRunState.apply_node_update` enforces node ownership and reducers; `src/bidded/orchestration/graph.py` owns the fixed LangGraph shell, preflight prerequisite checks, explicit edge table, bounded retry/stop policy, mocked handlers, and terminal routing.
- **Bidded Agent Tool Policy Contract**: `src/bidded/agents/tool_policy.py` defines LLM-agent denied tools, bounded retrieval scope, artifact read/write policy, and orchestrator-owned side effects.
- **Bidded Agent Output Schema Contract**: `src/bidded/agents/schemas.py` defines `RequirementType` plus strict Pydantic artifact schemas for scout findings, specialist motions, rebuttals, Judge decisions, typed Judge reasoning details, evidence refs, material claim evidence-ID validation, typed evidence gaps, validation errors, and specialist role bounds.
- **Bidded Company Evidence Contract**: `src/bidded/evidence/company_profile.py` builds deterministic `company_profile` evidence rows from the seeded company payload, with `field_path` provenance and idempotent `tenant_key,evidence_key` upserts.
- **Bidded Tender Evidence Contract**: `src/bidded/evidence/tender_document.py` keeps retrieved chunk extraction side-effect-free, applies glossary-first nullable requirement-type classification, builds stable citation keys, annotates regulatory glossary metadata, and exposes orchestrator-owned upsert/lookup helpers.
- **Bidded Document Pipeline Contract**: `src/bidded/documents` owns tender registration and PDF ingestion; use mocked Storage in tests, PyMuPDF for text-PDF extraction, deterministic page chunks, and parser status metadata on documents.
- **Bidded Pending Run Contract**: `pending_run.py` inserts deterministic `pending` `agent_runs`; `worker.py` claims with a `status = pending` update before graph execution so duplicate workers do not touch audit artifacts.
- **Bidded Retrieval/Recall Contract**: `src/bidded/embeddings.py` owns the 1536-dimension provider/model contract, `src/bidded/retrieval` ranks hybrid keyword/glossary/embedding candidates, and evidence recall warnings compare chunk/glossary signals to evidence-board requirement coverage before agent requests.
- **Bidded Evidence Scout Contract**: `src/bidded/orchestration/evidence_scout.py` builds six-pack retrieval requests and validates mocked Claude output against resolved evidence-board IDs; `graph.py` appends the `evidence_scout`/`evidence` audit row only after validation.
- **Bidded Round 1 Motion Contract**: `src/bidded/orchestration/specialist_motions.py` builds specialist requests from shared evidence plus scout output and requirement glossary context only, validates strict `Round1Motion` artifacts, limits formal blockers to exclusion/qualification tender evidence, and graph persistence appends `round_1_motion` rows only after all four roles validate.
- **Bidded Round 2 Rebuttal Contract**: `src/bidded/orchestration/specialist_rebuttals.py` is the first cross-motion read point; it builds focused rebuttal requests from shared evidence and all validated motions, then appends `round_2_rebuttal` rows only after all four roles validate.
- **Bidded Judge Decision Contract**: `src/bidded/orchestration/judge.py` builds Judge requests with requirement glossary context, validates strict `JudgeDecision` artifacts against the evidence board, gates only typed formal compliance blockers to `no_bid`, appends the Judge `final_decision` output, and builds `bid_decisions` rows with source output metadata.
