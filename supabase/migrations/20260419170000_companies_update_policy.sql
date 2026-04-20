-- Allow the anon (frontend) role to read and update the demo company profile.
-- The CompanyProfile page in the UI saves edits directly to `companies` via
-- the anon Supabase client; without an UPDATE policy the write silently
-- returns zero rows under RLS and the save appears to succeed but doesn't
-- actually persist. SELECT is required alongside UPDATE for the .eq()
-- filter and for the post-save refetch.
--
-- This script is idempotent: safe to re-run in the SQL editor. It enables
-- RLS on `companies` (no-op if already enabled) and drops + recreates each
-- policy so fixes to the expression don't require manual cleanup.

alter table public.companies enable row level security;

drop policy if exists "anon can read demo companies" on public.companies;
create policy "anon can read demo companies" on public.companies for select to anon using (tenant_key = 'demo');

drop policy if exists "anon can update demo companies" on public.companies;
create policy "anon can update demo companies" on public.companies for update to anon using (tenant_key = 'demo') with check (tenant_key = 'demo');
