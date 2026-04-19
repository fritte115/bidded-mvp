-- Tender PDF uploads from the anon-key frontend (see frontend/src/lib/api.ts).
-- Without a bucket row and storage.objects policies, uploads return 400/403.

-- allowed_mime_types null = no restriction (avoids 400 if Content-Type differs slightly)
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
    'public-procurements',
    'public-procurements',
    true,
    52428800, -- 50 MB
    null
)
on conflict (id) do update
set
    public = excluded.public,
    file_size_limit = coalesce(
        storage.buckets.file_size_limit,
        excluded.file_size_limit
    );

-- Idempotent policy refresh (safe if you re-run this script in the SQL editor)
drop policy if exists "bidded_demo_public_procurements_select" on storage.objects;
drop policy if exists "bidded_demo_public_procurements_insert" on storage.objects;
drop policy if exists "bidded_demo_public_procurements_update" on storage.objects;
drop policy if exists "bidded_demo_public_procurements_delete" on storage.objects;

-- Scope: bucket + paths under demo/... (buildStoragePath in frontend/src/lib/api.ts).
-- Use ~ '^/?demo/' so a leading slash on `name` (some stacks store '/demo/...') does not fail RLS.
-- Omit TO clause so the policy applies to PUBLIC (all roles). "TO anon, authenticated"
-- can miss the role the Storage API evaluates for RLS → 403 on INSERT.
create policy "bidded_demo_public_procurements_select"
    on storage.objects
    for select
    using (
        bucket_id = 'public-procurements'
        and name ~ '^/?demo/'
    );

create policy "bidded_demo_public_procurements_insert"
    on storage.objects
    for insert
    with check (
        bucket_id = 'public-procurements'
        and name ~ '^/?demo/'
    );

create policy "bidded_demo_public_procurements_update"
    on storage.objects
    for update
    using (
        bucket_id = 'public-procurements'
        and name ~ '^/?demo/'
    )
    with check (
        bucket_id = 'public-procurements'
        and name ~ '^/?demo/'
    );

create policy "bidded_demo_public_procurements_delete"
    on storage.objects
    for delete
    using (
        bucket_id = 'public-procurements'
        and name ~ '^/?demo/'
    );
