# Demo Runbook

This runbook is for the hackathon demo operator. It assumes the Python package is
installed locally and the hosted Supabase project is the source of truth for demo
runs, agent audit rows, evidence, and final decisions.

Normal tests stay deterministic and mocked. Live Claude, live embeddings, and
live Supabase smoke checks are manual, opt-in rehearsal steps.

## Pre-Demo Setup

Run setup from the repository root:

```bash
cp .env.example .env
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

Fill `.env` locally. Do not commit `.env`, paste secrets into chat, or expose the
Supabase service role key in UI code.

| Variable | Required For | Demo Value |
| --- | --- | --- |
| `SUPABASE_URL` | All Supabase-backed CLI and worker commands | Hosted demo project URL. |
| `SUPABASE_ANON_KEY` | Browser frontend access through `frontend/.env` | Public anon/publishable key from the Supabase dashboard; never use the service role key here. |
| `SUPABASE_SERVICE_ROLE_KEY` | Local worker, seeds, Storage, and audit writes | Server-side/local-worker only. |
| `SUPABASE_STORAGE_BUCKET` | PDF registration, ingestion, doctor, smoke | Defaults to `public-procurements`. |
| `ANTHROPIC_API_KEY` | `doctor --check-anthropic` and `demo-smoke --live-llm` | Optional for mocked smoke. |
| `EMBEDDING_MODE` | Chunk embedding behavior | Keep `mock` unless live embeddings are intentional. |
| `OPENAI_API_KEY` | Live OpenAI embeddings | Only needed when `EMBEDDING_MODE=live`. |
| `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, `EMBEDDING_DIMENSIONS` | Embedding contract | `openai`, `text-embedding-3-small`, `1536`. |

Before the demo, apply every SQL file in `supabase/migrations/` to the hosted
Supabase project in timestamp order. The migration set is expected to create the
core domain tables, agent audit tables, chunk/evidence tables, nullable
`requirement_type`, and the pgvector search RPC/index contract. The demo schema
does not require Supabase Auth or RLS.

Create the Storage bucket named by `SUPABASE_STORAGE_BUCKET`. The service role
key must be able to upload and download tender documents from that bucket. Demo
input PDFs must be text-based; DOCX input requires LibreOffice/`soffice` on the
worker PATH so Bidded can convert it to PDF for page references. OCR, legacy DOC,
and RTF import are out of scope.

Use the preferred local PDF path when the file exists:

```bash
data/demo/incoming/Bilaga\ Skakrav.pdf
```

If that file is absent, `demo-smoke` can generate a small temporary text-PDF
fixture so the operator can still rehearse the flow.

## Readiness Checks

Run the deterministic gates first:

```bash
.venv/bin/pytest -q
.venv/bin/ruff check .
```

Then check the live demo environment:

```bash
.venv/bin/bidded doctor
```

Use the stricter Anthropic check only when live Claude is part of that rehearsal:

```bash
.venv/bin/bidded doctor --check-anthropic
```

Expected result: environment variables are present, required Supabase tables are
reachable, the Storage bucket probe passes, and Anthropic connectivity passes
only when explicitly checked or configured.

## Normal Live Demo Path

Start with the environment doctor:

```bash
.venv/bin/bidded doctor --check-anthropic
```

Run the full smoke path. Default smoke uses mocked graph handlers; add
`--live-llm` only for a manual live-Claude rehearsal.

```bash
.venv/bin/bidded demo-smoke \
  --pdf-path data/demo/incoming/Bilaga\ Skakrav.pdf \
  --live-llm \
  --anthropic-model claude-sonnet-4-5
```

The smoke flow seeds the demo company, registers the PDF or temporary fixture,
ingests text chunks, builds evidence, creates a pending run, executes the worker,
and reads back the persisted decision. Use the printed run ID for status and
exports.

```bash
export AGENT_RUN_ID="<run id from smoke output>"

.venv/bin/bidded run-status --run-id "$AGENT_RUN_ID" --verbose

.venv/bin/bidded export-decision \
  --run-id "$AGENT_RUN_ID" \
  --markdown-path decision-bundle.md \
  --json-path decision-bundle.json
```

If the demo needs to show the worker as a separate step, create a pending run
from known Supabase IDs, then run the worker and status commands:

```bash
.venv/bin/bidded create-pending-run \
  --tender-id "$TENDER_ID" \
  --company-id "$COMPANY_ID" \
  --document-id "$DOCUMENT_ID"

.venv/bin/bidded worker --run-id "$AGENT_RUN_ID"
.venv/bin/bidded run-status --run-id "$AGENT_RUN_ID" --verbose
```

Without `--run-id`, the worker selects the oldest pending demo run. Use
`--company-id "$COMPANY_ID"` to restrict that selection when multiple pending
runs exist.

## Fallback Replay

Seed replayable demo states before the demo or whenever live dependencies become
unreliable:

```bash
.venv/bin/bidded seed-demo-company
.venv/bin/bidded seed-demo-states
```

Use the seeded `succeeded`, `failed`, or `needs_human_review` run IDs from
Supabase or command output to demonstrate status, trace diagnostics, retry, and
export without asking Claude to produce a fresh result:

```bash
.venv/bin/bidded run-status --run-id "$SEEDED_RUN_ID" --verbose

.venv/bin/bidded export-decision \
  --run-id "$SEEDED_SUCCEEDED_RUN_ID" \
  --markdown-path decision-bundle.md \
  --json-path decision-bundle.json
```

## Recovery Matrix

| Scenario | Operator Action |
| --- | --- |
| Missing PDF | Run `demo-smoke` without relying on the preferred PDF path; it will create a temporary text-PDF fixture. For the real tender, put the text-PDF or DOCX under `data/demo/incoming/` and rerun smoke or registration. |
| Claude unavailable | Use default `demo-smoke` without `--live-llm`, or use `seed-demo-states` replay. After fixing `ANTHROPIC_API_KEY` or model access, create a retry run and execute the worker. |
| Supabase failure | Run `doctor` to isolate URL, service key, table, or Storage bucket failures. Fix migrations/bucket/env first; do not patch audit rows manually. Use seeded replay if the live project is unavailable during the talk track. |
| Stuck `running` run | Inspect `run-status --verbose`. If the worker heartbeat is stale, reset it with `reset-stale-runs`, then create a retry run. |
| UI unavailable | Continue from the CLI. `run-status --verbose` is the operator trace, and `export-decision` produces the demo Markdown/JSON bundle from persisted Supabase rows. |

Useful recovery commands:

```bash
.venv/bin/bidded retry-run \
  --run-id "$FAILED_OR_REVIEW_RUN_ID" \
  --reason "retry after fixing demo input"

.venv/bin/bidded reset-stale-runs \
  --max-age-minutes 45 \
  --reason "operator confirmed worker heartbeat is stale"

.venv/bin/bidded worker --run-id "$RETRY_RUN_ID"
.venv/bin/bidded run-status --run-id "$RETRY_RUN_ID" --verbose
```

Use `retry-run --force` only when intentionally replaying from a succeeded source
run. Normal retries should start from `failed` or `needs_human_review` runs.

## Test Policy

Story and CI-style checks should use:

```bash
.venv/bin/pytest -q
.venv/bin/ruff check .
```

Those checks must not require live Claude, live embeddings, or live Supabase.
Live smoke is an operator rehearsal, not a required automated test gate:

```bash
.venv/bin/bidded demo-smoke --pdf-path data/demo/incoming/Bilaga\ Skakrav.pdf
.venv/bin/bidded demo-smoke --pdf-path data/demo/incoming/Bilaga\ Skakrav.pdf --live-llm
```
