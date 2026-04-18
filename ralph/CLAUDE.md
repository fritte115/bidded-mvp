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
