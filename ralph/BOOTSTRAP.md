# State Bootstrap

> This file is read ONLY when `ralph/state.json` does not exist (first session or manual invocation).

## Steps

1. Read `ralph/prd.json`
2. Find the first story where `passes: false` (lowest `priority` number)
3. Determine `nextAction`:
   - If the story has `iterationMode`: `"iteration 1/N"` (where N = `maxIterations`)
   - Otherwise: `"implement"`
4. Write `ralph/state.json`:
```json
{
  "branch": "<from prd.json branchName>",
  "currentStory": "<story id>",
  "storyTitle": "<story title>",
  "nextAction": "<determined above>",
  "progressTokens": 0,
  "compactionNeeded": false,
  "compactionThreshold": 10000,
  "lastUpdated": "<today's date>"
}
```
5. Initialize `ralph/progress.md` if it doesn't exist:
```markdown
# Ralph Progress Log
Started: [date]
---

## Codebase Patterns
> Reusable patterns discovered during implementation. Read this FIRST every session.

## Session Log

No Ralph story sessions have completed yet.
```
6. Return to **Your Task** in `ralph/CLAUDE.md`
