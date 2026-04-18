# Progress Guide

> Reference for writing progress reports and managing the experiential memory layer.
> Read this file when you need the full format details for `ralph/progress.md` or `ralph/prd.json` notes.

## Progress Report Format

APPEND to `ralph/progress.md` (NEVER replace, ALWAYS append):
```markdown
## [Date/Time] - [Story ID]
- **Implemented**: [1 sentence]
- **Files**: [comma-separated, or "None"]
- **Key learnings**: [1 concise reusable note, omit if none]
---
```

Keep entries lean. Do not restate fully green quality checks or PRD/story-status updates unless they failed unexpectedly or are the only important outcome.

## Codebase Patterns Section

Maintain a `## Codebase Patterns` section at the **TOP** of `ralph/progress.md` (right after the header). Create it if missing:
```markdown
## Codebase Patterns
> Reusable patterns discovered during implementation. Read this FIRST every session.

- **Pattern Name**: description
```

Budget: **15 lines max**. Merge related patterns aggressively, prefer one bullet per subsystem, and update an existing bullet before adding a sibling. Never add story-specific details or timestamps.

## Persist Learnings

After implementing a story, persist reusable discoveries to two places:

- **Codebase Patterns** (top of `ralph/progress.md`): General, reusable patterns
- **Institutional Memory** (bottom of `ralph/CLAUDE.md`): Conventions, gotchas, cross-file dependencies
- Optionally update project-level `CLAUDE.md` files in relevant directories for directory-scoped knowledge
- NEVER add: story-specific details, temporary debugging notes, or info already elsewhere
- Only add patterns that are **genuinely reusable** across stories
- Prefer one concise learning line in the session entry; move long-lived knowledge into Codebase Patterns instead of repeating it in many stories

## Notes Compaction (prd.json)

When writing the FINAL notes for a story (the one that sets `passes: true`):
- Compact ALL previous notes into a single summary
- Final `notes` field must be **max 2 lines** (~200 chars)
- Keep: what was done, files changed, key ambiguities
- Remove: line numbers, audit scores, citation counts, verification details
- Format: `"[Summary of what was integrated/changed]. [Key ambiguity if any]. Complete."`
