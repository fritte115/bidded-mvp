# Compaction Session

> This file is read ONLY when `scripts/ralph/state.json` has `compactionNeeded: true`.
> This session's ONLY job is compacting `scripts/ralph/progress.md`. Do NOT work on any story.

## Steps

1. Read `scripts/ralph/progress.md` in chunks (use offset/limit, ~300 lines per chunk)
2. **Promote before compacting**: scan session entries for learnings NOT already in `## Codebase Patterns`. Add any missing reusable learnings to that section before proceeding.
3. Rewrite it following these rules:
   - **Keep header** (title, start date)
   - **Keep Codebase Patterns section concise** (including any additions from step 2), merging it down to roughly 10-15 bullets by subsystem
   - **Keep only the last 2-3 session entries intact** (the most recent entries from the bottom of the file)
   - **Compact only INTERMEDIATE sessions** (between Codebase Patterns and the last 2-3 entries) to this format:
     ```markdown
     ## [Date] - [Story ID] (Iteration X/Y)
     - **Implemented**: [1 sentence]
     - **Files**: [comma-separated, or "None"]
     - **Key learnings**: [1 concise reusable insight, omit if none]
     ---
     ```
   - **Ultra-compact for verification-only sessions**:
     ```markdown
     ## [Date] - [Story ID] (Iteration X/Y)
     - **Implemented**: Verification pass — no changes needed.
     - **Files**: None
     ---
     ```
   - **Remove from intermediate sessions**: line numbers (L42, L103...), verbose audit results, citation counts, separate "quality checks" and "story status" lines, and other excessive verbosity
4. Write the compacted `scripts/ralph/progress.md`
5. Update `scripts/ralph/state.json`: set `compactionNeeded: false`, update `progressTokens` with new estimate
6. Commit: `chore: compact progress.md`
7. STOP — next session resumes story work
