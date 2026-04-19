# Bidded — Lovable Demo UI

Thin demo frontend for **Bidded**, a hackathon-scoped agent core for bid /
no-bid decisions on Swedish public procurement.

This Lovable app is the read-mostly UI surface on top of the Python LangGraph
worker + Supabase backend defined in `ralph/prd.json`. It lets an operator:

- Register a procurement and upload its PDF
- Browse the unified evidence board
- Trigger / watch agent runs (Evidence Scout → 4 specialists → rebuttals → Judge)
- Read the final `BID` / `NO_BID` / `CONDITIONAL_BID` decision with full citations
- Compare procurements side-by-side and manage downstream bids

Everything in the app today is wired against the mock data in
`src/data/mock.ts`. No live backend yet.

## Backend integration

The data shapes, Supabase schema, read views, RPCs, and answers to all open
Lovable-handoff questions are documented in:

➡️ **[INTEGRATION.md](./INTEGRATION.md)**

Read that before adding any Supabase wiring. The TS types in `src/data/mock.ts`
are the source of truth for what the UI consumes — the backend's job is to
expose `lovable_*` views matching those shapes.

## Stack

- React 18 + Vite 5 + TypeScript 5
- Tailwind CSS v3 + shadcn/ui
- React Router

## Local dev

```bash
npm install
npm run dev
```
