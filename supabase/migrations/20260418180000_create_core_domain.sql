create extension if not exists pgcrypto;

create table if not exists public.companies (
    id uuid primary key default gen_random_uuid(),
    created_at timestamptz not null default now(),
    tenant_key text not null default 'demo',
    name text not null,
    profile_label text not null default 'seeded_it_consultancy',
    organization_number text,
    headquarters_country text not null default 'SE',
    employee_count integer,
    annual_revenue_sek numeric,
    capabilities jsonb not null default '{}'::jsonb,
    certifications jsonb not null default '[]'::jsonb,
    reference_projects jsonb not null default '[]'::jsonb,
    financial_assumptions jsonb not null default '{}'::jsonb,
    profile_details jsonb not null default '{}'::jsonb,
    metadata jsonb not null default '{}'::jsonb,
    constraint companies_tenant_key_demo_check check (tenant_key = 'demo'),
    constraint companies_tenant_name_key unique (tenant_key, name),
    constraint companies_employee_count_check
        check (employee_count is null or employee_count > 0),
    constraint companies_annual_revenue_sek_check
        check (annual_revenue_sek is null or annual_revenue_sek >= 0)
);

create table if not exists public.tenders (
    id uuid primary key default gen_random_uuid(),
    created_at timestamptz not null default now(),
    tenant_key text not null default 'demo',
    title text not null,
    issuing_authority text not null,
    procurement_reference text,
    procurement_context jsonb not null default '{}'::jsonb,
    language_policy jsonb not null default '{}'::jsonb,
    metadata jsonb not null default '{}'::jsonb,
    constraint tenders_tenant_key_demo_check check (tenant_key = 'demo'),
    constraint tenders_tenant_title_authority_key
        unique (tenant_key, title, issuing_authority)
);

create table if not exists public.documents (
    id uuid primary key default gen_random_uuid(),
    created_at timestamptz not null default now(),
    tenant_key text not null default 'demo',
    tender_id uuid references public.tenders(id) on delete cascade,
    company_id uuid references public.companies(id) on delete cascade,
    storage_path text not null,
    checksum_sha256 text not null,
    content_type text not null default 'application/pdf',
    document_role text not null,
    parse_status text not null default 'pending',
    original_filename text not null,
    metadata jsonb not null default '{}'::jsonb,
    constraint documents_storage_path_key unique (storage_path),
    constraint documents_checksum_sha256_check
        check (checksum_sha256 ~ '^[a-f0-9]{64}$'),
    constraint documents_document_role_check
        check (document_role in ('tender_document', 'company_profile')),
    constraint documents_parse_status_check
        check (parse_status in ('pending', 'parsing', 'parsed', 'parser_failed')),
    constraint documents_tenant_key_demo_check check (tenant_key = 'demo'),
    constraint documents_role_link_check
        check (
            (
                document_role = 'tender_document'
                and tender_id is not null
                and company_id is null
            )
            or (
                document_role = 'company_profile'
                and company_id is not null
                and tender_id is null
            )
        )
);
