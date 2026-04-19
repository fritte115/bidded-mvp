# Frontend–backend integration (PRD as truth, no PRD story implementation)

## Constraints (authoritative)

- **`ralph/prd.json` is the source of truth** for what the product will do and in what order. Use it to **avoid** building features that duplicate or preempt upcoming stories.
- **Do not implement anything that is defined as a user story in `prd.json`** in this track — in particular **do not** ship US-013+ behavior (pending runs, ingestion, retrieval, evidence board population, swarm, judge, worker, handoff fixtures, etc.).
- Assume **through US-012** is what exists operationally: core schema, audit/evidence **tables** from migrations, seeded company, company evidence conversion, **register-demo-tender** CLI path — not the LangGraph worker or run lifecycle.

## What stays mock / deferred (by PRD)

| UI area | Why |
|--------|-----|
| Start Run, Re-run | US-013 |
| Verdicts, Decisions list/detail, Dashboard “Latest Verdicts” | US-021+ (data + worker) |
| Run detail timeline, Evidence board from DB | US-014–US-020+ |
| “Compare” procurement metrics not in migrations | Out of scope unless a non-PRD migration is explicitly approved |

Keep mock data or explicit **empty states** for these; do not add RPCs/migrations whose **purpose** is to unlock those PRD stories.

## Safe integration work (does not implement PRD backlog)

These **only deepen** the connection to artifacts **already** covered by US-001–US-012:

1. **Procurements + documents (US-002 / US-012)**
   - Continue using `tenders`, `documents`, Storage as today.
   - Optional UX: surface **`documents.parse_status`** (and `parse_error` if any) per file so the UI honestly shows “pending” until a future ingest story runs — **display only**, no PDF pipeline.

2. **Company profile (US-010 / US-011)**
   - Keep read/update against `companies` as today; no new tables.

3. **Dashboard stats that do not imply worker**
   - Counts from `tenders` / `documents` are fine.
   - **Avoid** wiring “decisions made” / “avg confidence” to `bid_decisions` if that implies expecting real rows — either leave as mock, hide, or show “—” until PRD work exists (otherwise it’s pretending US-021 landed).

4. **Docs hygiene (non-code or minimal)**
   - Align comments in [`frontend/src/lib/api.ts`](frontend/src/lib/api.ts) / [`frontend/INTEGRATION.md`](frontend/INTEGRATION.md) with “contract deferred until US-025” vs **current** migrations — **documentation only**, no new `lovable_*` or RPCs **for** US-013+.

## What not to add in this track

- Migrations for `create_pending_run`, `lovable_*` views, or any write path whose **reason** is US-013 or later.
- Frontend calls that **insert** into `agent_runs` or mutate worker-owned tables.
- Replacing mock verdicts with live `bid_decisions` queries (that’s post–US-021).

## Summary

**Use `prd.json` to know what’s coming; implement only frontend/backend glue that sits entirely inside US-012-and-earlier surfaces (core domain, storage registration, seeded company/evidence as already seeded by CLI).** Everything that needs a new Ralph story stays mock or clearly labeled “not available yet.”
