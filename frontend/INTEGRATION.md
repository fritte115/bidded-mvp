# Bidded — Lovable ↔ Supabase Integration Spec

This document is the contract between the **Lovable demo UI** (this repo) and the
**Python LangGraph worker + Supabase backend** described in `ralph/prd.json`.

The UI is intentionally thin: it **creates `pending` runs**, **uploads PDFs**, and
**reads results**. It never owns agent logic, side effects, or evidence
validation — those are the worker's responsibility.

> Status: this repo currently runs entirely on the mock data in
> `src/data/mock.ts`. Every shape below is what the UI **already consumes** —
> the backend's job is to expose views/RPCs that match these shapes.

---

## 1. High-level data flow

```
┌────────────┐   create_pending_run   ┌─────────────┐   pick up    ┌──────────────┐
│  Lovable   │───────────────────────▶│  Supabase   │◀────────────│ Python worker│
│   (UI)     │   register_tender_doc  │  (Postgres) │   write     │  (LangGraph) │
└─────┬──────┘                        │  + Storage  │   results   └──────┬───────┘
      │                               └──────┬──────┘                    │
      │  read lovable_* views                │                           │
      └──────────────────────────────────────┘                           │
                                                                         │
                                          tender PDFs (Storage)──────────┘
```

UI never writes directly to `agent_runs`, `agent_outputs`, `evidence_items`, or
`bid_decisions`. Those are worker-owned. UI writes go through **two
`SECURITY DEFINER` RPCs** (see §6).

---

## 2. Required Supabase schema

All migrations should be deterministic and demo-friendly (no Auth/RLS in v1
beyond a read-only `anon` policy on the `lovable_*` views — see §7).

### 2.1 `companies`

The seeded demo IT consultancy.

```sql
create table public.companies (
  id              uuid primary key default gen_random_uuid(),
  name            text not null,
  org_number      text not null unique,
  size_label      text,           -- e.g. "85 employees"
  hq              text,           -- e.g. "Stockholm, Sweden"
  capabilities    text[] not null default '{}',
  certifications  jsonb not null default '[]'::jsonb,  -- [{name, issuer, valid_until}]
  references      jsonb not null default '[]'::jsonb,  -- [{client, scope, value, year}]
  financial       jsonb not null default '{}'::jsonb,  -- {revenue_range, target_margin, max_contract_size}
  created_at      timestamptz not null default now()
);
```

Maps to `Company` in `src/data/mock.ts`. The seed company in v1 is
`Acme IT Consulting AB` (org `556677-1122`).

### 2.2 `tenders` (UI label: **Procurement**)

```sql
create table public.tenders (
  id                    uuid primary key default gen_random_uuid(),
  company_id            uuid not null references public.companies(id),
  name                  text not null,
  description           text,
  uploaded_at           timestamptz not null default now(),
  status                text not null default 'pending'
                        check (status in ('pending','processing','done')),
  -- Comparison metrics (UI-side; worker may overwrite once decided)
  estimated_value_msek  numeric,
  win_probability       numeric,         -- 0..1
  strategic_fit         text check (strategic_fit in ('Low','Medium','High')),
  risk_score            text check (risk_score in ('Low','Medium','High')),
  top_reason            text,
  verdict               text check (verdict in ('BID','NO_BID','CONDITIONAL_BID')),
  confidence            int check (confidence between 0 and 100)
);
```

> Naming: keep the table name `tenders` to match PRD. **All UI-facing
> views/columns must alias as `procurement_*`** (the user-facing term).

### 2.3 `documents`

```sql
create table public.documents (
  id            uuid primary key default gen_random_uuid(),
  tender_id     uuid not null references public.tenders(id) on delete cascade,
  filename      text not null,
  storage_path  text not null,                                     -- tender_documents/<tender_id>/<filename>
  content_type  text not null default 'application/pdf',
  checksum_sha256 text,
  role          text not null default 'tender'
                check (role in ('tender','annex','company_profile')),
  parse_status  text not null default 'pending'
                check (parse_status in ('pending','parsing','parsed','parser_failed')),
  parse_error   text,
  uploaded_at   timestamptz not null default now()
);
```

Maps to `Procurement.documentRefs` (see §4).

### 2.4 `document_chunks`

```sql
create table public.document_chunks (
  id            uuid primary key default gen_random_uuid(),
  document_id   uuid not null references public.documents(id) on delete cascade,
  chunk_index   int  not null,
  page          int,
  text          text not null,
  metadata      jsonb not null default '{}'::jsonb,
  embedding     vector(1536),                          -- nullable; pgvector optional
  unique (document_id, chunk_index)
);
```

UI only renders the **count** (`Procurement.chunks`). Worker owns the rows.

### 2.5 `evidence_items`

```sql
create table public.evidence_items (
  id              uuid primary key default gen_random_uuid(),
  tender_id       uuid not null references public.tenders(id) on delete cascade,
  evidence_key    text not null,                          -- e.g. TENDER.MANDATORY.ISO27001
  category        text not null,                          -- see EvidenceCategory enum
  excerpt         text not null,                          -- short, excerpt-level
  source_kind     text not null
                  check (source_kind in ('tender_document','company_profile')),
  -- tender_document refs:
  document_id     uuid references public.documents(id),
  chunk_id        uuid references public.document_chunks(id),
  page            int,
  -- company_profile refs:
  company_id      uuid references public.companies(id),
  field_path      text,                                   -- e.g. "certifications[0].name"
  source_label    text,                                   -- human label
  referenced_by   text[] not null default '{}',           -- agent role labels
  created_at      timestamptz not null default now(),
  unique (tender_id, evidence_key)
);
```

Maps to `Evidence` in `mock.ts`. The UI renders `evidence_key` as the badge
(e.g. `EVD-003`-style) **and** keeps the UUID for stable linking.

### 2.6 `agent_runs`

```sql
create type public.agent_run_status as enum
  ('pending','running','succeeded','failed','needs_human_review');

create table public.agent_runs (
  id            uuid primary key default gen_random_uuid(),
  tender_id     uuid not null references public.tenders(id),
  company_id    uuid not null references public.companies(id),
  status        public.agent_run_status not null default 'pending',
  current_stage text,
  config        jsonb not null default '{}'::jsonb,
  error         jsonb,                              -- {code, message, details}
  started_at    timestamptz,
  completed_at  timestamptz,
  duration_sec  int,
  created_at    timestamptz not null default now()
);
```

The UI now renders **all five statuses** (after this PR).

### 2.7 `agent_outputs`

Append-only, one row per (run, agent, round, output_type).

```sql
create table public.agent_outputs (
  id            uuid primary key default gen_random_uuid(),
  run_id        uuid not null references public.agent_runs(id) on delete cascade,
  agent_role    text not null,            -- 'Compliance Officer'|'Win Strategist'|'Delivery/CFO'|'Red Team'|'Evidence Scout'|'Judge'
  round         int  not null check (round between 0 and 2),  -- 0 = scout, 1 = motions, 2 = rebuttals
  output_type   text not null,            -- 'motion'|'rebuttal'|'scout_report'|'judgement'
  payload       jsonb not null,           -- validated AgentMotion / JudgeOutput shape
  validation_errors jsonb not null default '[]'::jsonb,
  model         text,
  prompt_tokens int,
  output_tokens int,
  cost_estimate_usd numeric,
  created_at    timestamptz not null default now(),
  unique (run_id, agent_role, round, output_type)
);
```

### 2.8 `bid_decisions`

```sql
create table public.bid_decisions (
  id           uuid primary key default gen_random_uuid(),
  run_id       uuid not null unique references public.agent_runs(id) on delete cascade,
  tender_id    uuid not null references public.tenders(id),
  verdict      text not null check (verdict in ('BID','NO_BID','CONDITIONAL_BID')),
  confidence   int  not null check (confidence between 0 and 100),
  payload      jsonb not null,           -- full JudgeOutput shape (see §5)
  cited_evidence_ids uuid[] not null default '{}',
  created_at   timestamptz not null default now()
);
```

---

## 3. Storage

Single bucket: **`tender_documents`**.

Object key convention:
```
tender_documents/{tender_id}/{original_filename}
```

The UI uploads directly via the JS client; the worker reads via service role.

---

## 4. Read views the UI expects

The UI does not query base tables directly — it reads four views. Column names
match exactly what `mock.ts` exports.

### 4.1 `lovable_run_summary` (run list)

| Column              | Type        | Maps to (`Run`)     |
|---------------------|-------------|---------------------|
| `id`                | uuid        | `id`                |
| `procurement_id`    | uuid        | `tenderId`          |
| `procurement_name`  | text        | `tenderName`        |
| `company`           | text        | `company`           |
| `status`            | enum        | `status`            |
| `stage`             | text        | `stage`             |
| `started_at`        | timestamptz | `startedAt`         |
| `completed_at`      | timestamptz | `completedAt`       |
| `duration_sec`      | int         | `durationSec`       |
| `decision`          | text/null   | `decision`          |
| `confidence`        | int/null    | `confidence`        |

### 4.2 `lovable_run_detail` (single run, all relations)

Same columns as `lovable_run_summary` plus:

| Column          | Type   | Notes                                     |
|-----------------|--------|-------------------------------------------|
| `evidence`      | jsonb  | array of `Evidence` (§5.1)                |
| `round1`        | jsonb  | array of `AgentMotion` (§5.2)             |
| `round2`        | jsonb  | array of `AgentMotion` (§5.2)             |
| `judge`         | jsonb  | `JudgeOutput` (§5.3) or `null`            |

### 4.3 `lovable_evidence_board`

Flat list for the Evidence Board page, one row per `evidence_items` row, joined
to its document/chunk for tender evidence and to company facts for company
evidence. Returns the §5.1 shape directly.

### 4.4 `lovable_agent_outputs`

Joins `agent_outputs` rows for a run. Used by Run Detail's timeline view.

| Column         | Type   |
|----------------|--------|
| `run_id`       | uuid   |
| `agent_role`   | text   |
| `round`        | int    |
| `output_type`  | text   |
| `payload`      | jsonb  |
| `created_at`   | timestamptz |

### 4.5 `lovable_decision_detail`

One row per `bid_decisions`. Returns `JudgeOutput` (§5.3) under `payload`,
plus `cited_evidence` denormalized as an array of `Evidence` for fast render.

---

## 5. JSON shapes (UI ↔ worker contract)

These match `src/data/mock.ts` byte-for-byte and **must not drift**.

### 5.1 `Evidence`

```ts
{
  id: string;                        // uuid as string
  key: string;                       // "TENDER.MANDATORY.ISO27001"
  category:
    | "Deadlines"
    | "Mandatory Requirements"
    | "Qualification Criteria"
    | "Evaluation Criteria"
    | "Contract Risks"
    | "Required Submission Documents";
  excerpt: string;
  source: string;                    // doc filename OR company source label
  page: number;                      // 0 for company_profile
  referencedBy: AgentName[];
  // Optional, additive — backend may include both kinds:
  kind?: "tender_document" | "company_profile";
  companyFieldPath?: string;
}
```

### 5.2 `AgentMotion` (Round 1 + Round 2)

```ts
{
  agent: "Compliance Officer" | "Win Strategist" | "Delivery/CFO" | "Red Team";
  verdict: "BID" | "NO_BID" | "CONDITIONAL_BID";
  confidence: number;                // 0..100
  findings: string[];                // each line should reference (EVD-xxx) where material
  rebuttalFocus?: string[];          // round 2 only
  challenges?: string[];             // round 2 only
}
```

### 5.3 `JudgeOutput`

```ts
{
  verdict: "BID" | "NO_BID" | "CONDITIONAL_BID";
  confidence: number;
  voteSummary: { BID: number; NO_BID: number; CONDITIONAL_BID: number };
  disagreement: string;
  citedMemo: string;
  complianceMatrix: Array<{
    requirement: string;
    status: "Met" | "Partial" | "Not Met" | "Unknown";
    evidence: string[];              // human keys like "EVD-003"
  }>;
  complianceBlockers: string[];
  potentialBlockers: string[];
  riskRegister: Array<{
    risk: string;
    severity: "Low" | "Medium" | "High";
    mitigation: string;
  }>;
  missingInfo: string[];
  recommendedActions: string[];
  evidenceIds: string[];
}
```

> Note: `verdict` is **uppercase enum** in JSON. The string
> `"NEEDS_HUMAN_REVIEW"` is **never** a verdict — that is a **run status only**.

---

## 6. RPCs the UI calls (write path)

Only two write paths exist for the UI in v1, both `SECURITY DEFINER`.

### 6.1 `create_pending_run(p_tender_id uuid, p_company_id uuid) returns uuid`

- Validates tender belongs to company.
- Inserts `agent_runs` row with `status='pending'`.
- Returns the new `run_id`.

### 6.2 `register_tender_document(p_tender_id uuid, p_storage_path text, p_filename text) returns uuid`

- Inserts a `documents` row with `parse_status='pending'`.
- Worker picks up and parses asynchronously.

### 6.3 (Demo helper) `create_demo_run_from_fixture(p_name text) returns uuid`

- Inserts a frozen `agent_run` + `bid_decision` from a JSONB fixture stored
  server-side, so the UI is always demoable even if Claude / the worker is down.

---

## 7. Demo security model

PRD says no Auth/RLS in v1. For Lovable's browser client we still need a safe
default:

- Use the **anon key** in the browser.
- Enable RLS on **all base tables** with **no policies** (deny by default).
- Enable RLS on **`lovable_*` views** with a single `select` policy `using (true)`.
- The two write RPCs are `SECURITY DEFINER` and validate inputs.
- Tenant scoping: a single `company_id` constant in v1; later passed by RPC.

This means: browser can read everything in the views, can call exactly two
RPCs, and cannot mutate base tables. Worker uses the **service role key**
(server-side only).

---

## 8. Status flow (UI rendering)

```
pending ──▶ running ──┬──▶ succeeded
                      ├──▶ failed                (red banner on RunDetail, "Re-run" button)
                      └──▶ needs_human_review    (amber banner, "Mark resolved" / "Request override")
```

All five are now rendered by `StatusBadge` and propagated through:

- `PipelineStep` (states: `completed | running | pending | failed | needs_human_review`)
- `RunDetail` (top-level banners + per-step state derived from `run.stage`)
- `Procurements` (the `done` filter includes all three terminal statuses)
- `Dashboard` "Active analyses" lane (recent terminal runs, any of the three statuses)

`needs_human_review` is **terminal until a human acts** — no automatic retry.

---

## 9. Field mapping cheatsheet

| UI (`mock.ts`)              | Supabase                                         |
|-----------------------------|--------------------------------------------------|
| `Procurement.id`            | `tenders.id`                                     |
| `Procurement.name`          | `tenders.name`                                   |
| `Procurement.documents`     | `documents.filename` (aggregated)                |
| `Procurement.documentRefs`  | rows from `documents` (id, filename, parse_status) |
| `Procurement.chunks`        | `count(document_chunks)` per tender              |
| `Procurement.status`        | derived: pending/processing/done from doc parse  |
| `Procurement.estimatedValueMSEK` | `tenders.estimated_value_msek`              |
| `Procurement.winProbability`| `tenders.win_probability`                        |
| `Procurement.verdict/confidence` | latest `bid_decisions.verdict/confidence`   |
| `Run.id`                    | `agent_runs.id`                                  |
| `Run.tenderId/tenderName`   | `agent_runs.tender_id` + join                    |
| `Run.status`                | `agent_runs.status`                              |
| `Run.stage`                 | `agent_runs.current_stage`                       |
| `Run.evidence`              | `lovable_evidence_board(run_id)`                 |
| `Run.round1/round2`         | `agent_outputs` filtered by round                |
| `Run.judge`                 | `bid_decisions.payload`                          |
| `Evidence.id`               | `evidence_items.id`                              |
| `Evidence.key`              | `evidence_items.evidence_key`                    |
| `Evidence.source/page`      | join to `documents.filename` / chunk page        |
| `Company.*`                 | `companies.*`                                    |

---

## 10. Answers to the 12 open questions in the README

1. **Pending run creation** — Lovable calls
   `rpc('create_pending_run', { p_tender_id, p_company_id })`. The UI never
   inserts into `agent_runs` directly. The worker polls/listens for `pending`.

2. **PDF upload flow** — Lovable owns it (already wired in
   `RegisterProcurement.tsx`). Steps: (a) `supabase.storage.from('tender_documents').upload(...)`,
   (b) `rpc('register_tender_document', { p_tender_id, p_storage_path, p_filename })`.
   Parsing is async on the worker.

3. **Read views** — Yes, four are required: `lovable_run_summary`,
   `lovable_run_detail`, `lovable_evidence_board`, `lovable_agent_outputs`,
   plus `lovable_decision_detail` for the judge breakdown. Schemas in §4.

4. **Statuses rendered** — `pending`, `running`, `succeeded`, `failed`,
   `needs_human_review`. All five live in `RunStatus` and `StatusBadge` after
   this PR.

5. **Decision shape** — Single denormalized JSON object on
   `lovable_decision_detail.payload` for fast render of the Decision page,
   **plus** raw `agent_outputs` rows queryable for the Run Detail timeline.
   Both are needed.

6. **Round 1 / Round 2 / Judge JSON shapes** — see §5.2 and §5.3. Field-by-field
   match with `AgentMotion` and `JudgeOutput`. Verdicts are the uppercase
   enums `BID | NO_BID | CONDITIONAL_BID`.

7. **Evidence citations** — **Both**. The UI links via UUID (stable, safe for
   refactors) and renders the badge text from `evidence_key` (human-readable
   for the operator). Components like `EvidenceBadge` already follow this.

8. **Tender vs company evidence** — Yes, both are first-class. `Evidence.kind`
   is additive (`tender_document` | `company_profile`). For tender evidence
   the UI shows `source` (filename) + `page`. For company evidence the UI
   shows `source` (label) + `companyFieldPath`. The Evidence Board groups
   by category; source kind is a small icon/tag.

9. **`failed` and `needs_human_review`** — different affordances:
   - `failed` → **red banner + Re-run button** (already in Run Detail).
   - `needs_human_review` → **amber banner + "Mark resolved" / "Request override"
     actions**, no automatic retry. Status badge shows "Needs review".

10. **Demo security** — Anon key in browser; **RLS deny-by-default on base
    tables**, **RLS allow-select on `lovable_*` views**, and exactly two
    `SECURITY DEFINER` RPCs (`create_pending_run`,
    `register_tender_document`). Worker uses the service role server-side
    only. No auth/users in v1.

11. **Demo run from fixture** — Yes, `create_demo_run_from_fixture(name)` RPC
    inserts a frozen `agent_run` + `bid_decision` from a server-side JSONB
    fixture so the UI is always demoable even if Claude or the worker is
    offline. The current mock run `run_8f42b1c3` is a good fixture template.

12. **Naming conventions to honour** — From the live UI:
    - **`Procurement`** is the user-facing term. Tables stay `tenders`; views
      alias columns as `procurement_id` / `procurement_name`.
    - **Verdicts are uppercase enums** (`BID`, `NO_BID`, `CONDITIONAL_BID`),
      matching `Verdict` in `mock.ts`.
    - **Agent role names** are the four strings in `AgentName` exactly:
      `"Compliance Officer"`, `"Win Strategist"`, `"Delivery/CFO"`, `"Red Team"`.
      Plus `"Evidence Scout"` and `"Judge"` for round 0 and final.
    - **Evidence categories** are the six strings in `EvidenceCategory`.
    - **Status values** match `RunStatus` and `DocumentParseStatus`.
    - **Statuses, verdicts, categories** should be Postgres enums or
      `check`-constrained text — the UI relies on these literals.

---

## 11. Out of scope for v1 backend

These are **explicitly not** required by the current UI:

- Supabase Auth / per-user RLS
- OCR / DOCX parsing
- Tender search/import from external sources
- Live embeddings (UI works with chunk count only)
- Storing full raw LLM prompts as the default audit artifact
- Lovable as agent runtime (UI is read-mostly)
