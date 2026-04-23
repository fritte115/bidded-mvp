-- Auth/RBAC baseline for the productized app.
-- Supabase Auth owns identity; Bidded owns organization membership and roles.

create extension if not exists pgcrypto;

create table if not exists public.organizations (
    id uuid primary key default gen_random_uuid(),
    created_at timestamptz not null default now(),
    tenant_key text not null unique,
    name text not null,
    metadata jsonb not null default '{}'::jsonb,
    constraint organizations_tenant_key_check check (tenant_key <> ''),
    constraint organizations_name_check check (name <> ''),
    constraint organizations_metadata_object_check
        check (jsonb_typeof(metadata) = 'object')
);

insert into public.organizations (id, tenant_key, name, metadata)
values (
    '00000000-0000-4000-8000-000000000001'::uuid,
    'demo',
    'Bidded Demo Tenant',
    jsonb_build_object('created_by_migration', '20260423120000_add_auth_rbac')
)
on conflict (id) do update
set
    tenant_key = excluded.tenant_key,
    name = excluded.name,
    metadata = public.organizations.metadata || excluded.metadata;

create table if not exists public.profiles (
    user_id uuid primary key references auth.users(id) on delete cascade,
    created_at timestamptz not null default now(),
    email text,
    display_name text,
    global_role text,
    metadata jsonb not null default '{}'::jsonb,
    constraint profiles_global_role_check
        check (global_role is null or global_role = 'superadmin'),
    constraint profiles_metadata_object_check
        check (jsonb_typeof(metadata) = 'object')
);

create table if not exists public.organization_memberships (
    id uuid primary key default gen_random_uuid(),
    created_at timestamptz not null default now(),
    organization_id uuid not null references public.organizations(id) on delete cascade,
    user_id uuid not null references auth.users(id) on delete cascade,
    role text not null,
    status text not null default 'active',
    invited_by uuid references auth.users(id) on delete set null,
    metadata jsonb not null default '{}'::jsonb,
    constraint organization_memberships_role_check check (role in ('admin', 'user')),
    constraint organization_memberships_status_check
        check (status in ('active', 'invited', 'disabled')),
    constraint organization_memberships_user_org_key unique (organization_id, user_id),
    constraint organization_memberships_metadata_object_check
        check (jsonb_typeof(metadata) = 'object')
);

create index if not exists organization_memberships_user_id_idx
    on public.organization_memberships (user_id);

create index if not exists organization_memberships_organization_id_idx
    on public.organization_memberships (organization_id);

create or replace function public.handle_new_auth_user_profile()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
    insert into public.profiles (user_id, email, display_name)
    values (
        new.id,
        new.email,
        coalesce(new.raw_user_meta_data ->> 'name', new.raw_user_meta_data ->> 'full_name')
    )
    on conflict (user_id) do nothing;

    return new;
end;
$$;

drop trigger if exists on_auth_user_created_bidded_profile on auth.users;

create trigger on_auth_user_created_bidded_profile
    after insert on auth.users
    for each row execute function public.handle_new_auth_user_profile();

create or replace function public.is_superadmin()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
    select exists (
        select 1
        from public.profiles p
        where p.user_id = auth.uid()
          and p.global_role = 'superadmin'
    );
$$;

create or replace function public.has_org_role(
    target_organization_id uuid,
    allowed_roles text[]
)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
    select public.is_superadmin()
        or exists (
            select 1
            from public.organization_memberships m
            where m.organization_id = target_organization_id
              and m.user_id = auth.uid()
              and m.status = 'active'
              and m.role = any(allowed_roles)
        );
$$;

create or replace function public.is_org_member(target_organization_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
    select public.has_org_role(target_organization_id, array['admin', 'user']::text[]);
$$;

create or replace function public.has_any_org_membership()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
    select public.is_superadmin()
        or exists (
            select 1
            from public.organization_memberships m
            where m.user_id = auth.uid()
              and m.status = 'active'
        );
$$;

create or replace function public.has_any_org_role(allowed_roles text[])
returns boolean
language sql
stable
security definer
set search_path = public
as $$
    select public.is_superadmin()
        or exists (
            select 1
            from public.organization_memberships m
            where m.user_id = auth.uid()
              and m.status = 'active'
              and m.role = any(allowed_roles)
        );
$$;

create or replace function public.shares_organization_with(target_user_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
    select public.is_superadmin()
        or target_user_id = auth.uid()
        or exists (
            select 1
            from public.organization_memberships mine
            join public.organization_memberships theirs
              on theirs.organization_id = mine.organization_id
            where mine.user_id = auth.uid()
              and mine.status = 'active'
              and theirs.user_id = target_user_id
              and theirs.status = 'active'
        );
$$;

do $$
declare
    demo_org_id constant uuid := '00000000-0000-4000-8000-000000000001'::uuid;
    table_name text;
begin
    foreach table_name in array array[
        'companies',
        'tenders',
        'documents',
        'document_chunks',
        'evidence_items',
        'agent_runs',
        'agent_outputs',
        'bid_decisions',
        'bids'
    ]
    loop
        execute format(
            'alter table if exists public.%I add column if not exists organization_id uuid references public.organizations(id)',
            table_name
        );
        execute format(
            'update public.%I set organization_id = $1 where organization_id is null',
            table_name
        )
        using demo_org_id;
        execute format(
            'alter table if exists public.%I alter column organization_id set default %L::uuid',
            table_name,
            demo_org_id
        );
        execute format(
            'alter table if exists public.%I alter column organization_id set not null',
            table_name
        );
        execute format(
            'create index if not exists %I on public.%I (organization_id)',
            table_name || '_organization_id_idx',
            table_name
        );
    end loop;
end;
$$;

alter table public.organizations enable row level security;
alter table public.profiles enable row level security;
alter table public.organization_memberships enable row level security;
alter table public.companies enable row level security;
alter table public.tenders enable row level security;
alter table public.documents enable row level security;
alter table public.document_chunks enable row level security;
alter table public.evidence_items enable row level security;
alter table public.agent_runs enable row level security;
alter table public.agent_outputs enable row level security;
alter table public.bid_decisions enable row level security;
alter table public.bids enable row level security;

drop policy if exists "anon can read demo companies" on public.companies;
drop policy if exists "anon can update demo companies" on public.companies;
drop policy if exists "anon can read demo bids" on public.bids;
drop policy if exists "anon can insert demo bids" on public.bids;
drop policy if exists "anon can update demo bids" on public.bids;
drop policy if exists "anon can delete demo bids" on public.bids;
drop policy if exists "anon can delete demo agent runs" on public.agent_runs;
drop policy if exists "anon can delete demo agent outputs" on public.agent_outputs;

drop policy if exists "members can read organizations" on public.organizations;
create policy "members can read organizations"
    on public.organizations
    for select
    to authenticated
    using (public.is_org_member(id));

drop policy if exists "superadmins can manage organizations" on public.organizations;
create policy "superadmins can manage organizations"
    on public.organizations
    for all
    to authenticated
    using (public.is_superadmin())
    with check (public.is_superadmin());

drop policy if exists "users can read shared profiles" on public.profiles;
create policy "users can read shared profiles"
    on public.profiles
    for select
    to authenticated
    using (public.shares_organization_with(user_id));

drop policy if exists "users can read memberships in their organizations" on public.organization_memberships;
create policy "users can read memberships in their organizations"
    on public.organization_memberships
    for select
    to authenticated
    using (public.is_org_member(organization_id));

drop policy if exists "admins can manage memberships" on public.organization_memberships;
create policy "admins can manage memberships"
    on public.organization_memberships
    for all
    to authenticated
    using (public.has_org_role(organization_id, array['admin']::text[]))
    with check (public.has_org_role(organization_id, array['admin']::text[]));

drop policy if exists "members can read companies" on public.companies;
create policy "members can read companies"
    on public.companies
    for select
    to authenticated
    using (public.is_org_member(organization_id));

drop policy if exists "admins can update companies" on public.companies;
create policy "admins can update companies"
    on public.companies
    for update
    to authenticated
    using (public.has_org_role(organization_id, array['admin']::text[]))
    with check (public.has_org_role(organization_id, array['admin']::text[]));

drop policy if exists "members can read tenders" on public.tenders;
create policy "members can read tenders"
    on public.tenders
    for select
    to authenticated
    using (public.is_org_member(organization_id));

drop policy if exists "members can create tenders" on public.tenders;
create policy "members can create tenders"
    on public.tenders
    for insert
    to authenticated
    with check (public.is_org_member(organization_id));

drop policy if exists "admins can update tenders" on public.tenders;
create policy "admins can update tenders"
    on public.tenders
    for update
    to authenticated
    using (public.has_org_role(organization_id, array['admin']::text[]))
    with check (public.has_org_role(organization_id, array['admin']::text[]));

drop policy if exists "admins can delete tenders" on public.tenders;
create policy "admins can delete tenders"
    on public.tenders
    for delete
    to authenticated
    using (public.has_org_role(organization_id, array['admin']::text[]));

drop policy if exists "members can read documents" on public.documents;
create policy "members can read documents"
    on public.documents
    for select
    to authenticated
    using (public.is_org_member(organization_id));

drop policy if exists "members can create documents" on public.documents;
create policy "members can create documents"
    on public.documents
    for insert
    to authenticated
    with check (
        public.is_org_member(organization_id)
        and (
            tender_id is null
            or exists (
                select 1
                from public.tenders t
                where t.id = tender_id
                  and t.organization_id = documents.organization_id
            )
        )
        and (
            company_id is null
            or exists (
                select 1
                from public.companies c
                where c.id = company_id
                  and c.organization_id = documents.organization_id
            )
        )
    );

drop policy if exists "admins can update documents" on public.documents;
create policy "admins can update documents"
    on public.documents
    for update
    to authenticated
    using (public.has_org_role(organization_id, array['admin']::text[]))
    with check (public.has_org_role(organization_id, array['admin']::text[]));

drop policy if exists "admins can delete documents" on public.documents;
create policy "admins can delete documents"
    on public.documents
    for delete
    to authenticated
    using (public.has_org_role(organization_id, array['admin']::text[]));

drop policy if exists "members can read document chunks" on public.document_chunks;
create policy "members can read document chunks"
    on public.document_chunks
    for select
    to authenticated
    using (public.is_org_member(organization_id));

drop policy if exists "members can read evidence items" on public.evidence_items;
create policy "members can read evidence items"
    on public.evidence_items
    for select
    to authenticated
    using (public.is_org_member(organization_id));

drop policy if exists "members can read agent runs" on public.agent_runs;
create policy "members can read agent runs"
    on public.agent_runs
    for select
    to authenticated
    using (public.is_org_member(organization_id));

drop policy if exists "admins can delete agent runs" on public.agent_runs;
create policy "admins can delete agent runs"
    on public.agent_runs
    for delete
    to authenticated
    using (public.has_org_role(organization_id, array['admin']::text[]));

drop policy if exists "members can read agent outputs" on public.agent_outputs;
create policy "members can read agent outputs"
    on public.agent_outputs
    for select
    to authenticated
    using (public.is_org_member(organization_id));

drop policy if exists "members can read bid decisions" on public.bid_decisions;
create policy "members can read bid decisions"
    on public.bid_decisions
    for select
    to authenticated
    using (public.is_org_member(organization_id));

drop policy if exists "members can read bids" on public.bids;
create policy "members can read bids"
    on public.bids
    for select
    to authenticated
    using (public.is_org_member(organization_id));

drop policy if exists "admins can manage bids" on public.bids;
create policy "admins can manage bids"
    on public.bids
    for all
    to authenticated
    using (public.has_org_role(organization_id, array['admin']::text[]))
    with check (
        public.has_org_role(organization_id, array['admin']::text[])
        and exists (
            select 1
            from public.tenders t
            where t.id = tender_id
              and t.organization_id = bids.organization_id
        )
    );

drop policy if exists "bidded_demo_public_procurements_select" on storage.objects;
drop policy if exists "bidded_demo_public_procurements_insert" on storage.objects;
drop policy if exists "bidded_demo_public_procurements_update" on storage.objects;
drop policy if exists "bidded_demo_public_procurements_delete" on storage.objects;

update storage.buckets
set public = false
where id = 'public-procurements';

create policy "members can read procurement storage"
    on storage.objects
    for select
    to authenticated
    using (
        bucket_id = 'public-procurements'
        and name ~ '^/?demo/'
        and public.has_any_org_membership()
    );

create policy "members can upload procurement storage"
    on storage.objects
    for insert
    to authenticated
    with check (
        bucket_id = 'public-procurements'
        and name ~ '^/?demo/'
        and public.has_any_org_membership()
    );

create policy "members can update procurement storage"
    on storage.objects
    for update
    to authenticated
    using (
        bucket_id = 'public-procurements'
        and name ~ '^/?demo/'
        and public.has_any_org_membership()
    )
    with check (
        bucket_id = 'public-procurements'
        and name ~ '^/?demo/'
        and public.has_any_org_membership()
    );

create policy "admins can delete procurement storage"
    on storage.objects
    for delete
    to authenticated
    using (
        bucket_id = 'public-procurements'
        and name ~ '^/?demo/'
        and public.has_any_org_role(array['admin']::text[])
    );
