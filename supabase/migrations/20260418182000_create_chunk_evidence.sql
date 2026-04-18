create extension if not exists vector;

create table if not exists public.document_chunks (
    id uuid primary key default gen_random_uuid(),
    created_at timestamptz not null default now(),
    tenant_key text not null default 'demo',
    document_id uuid not null references public.documents(id) on delete cascade,
    page_start integer not null,
    page_end integer not null,
    chunk_index integer not null,
    text text not null,
    metadata jsonb not null default '{}'::jsonb,
    embedding vector(1536),
    constraint document_chunks_tenant_key_demo_check check (tenant_key = 'demo'),
    constraint document_chunks_document_chunk_index_key
        unique (document_id, chunk_index),
    constraint document_chunks_page_start_check check (page_start > 0),
    constraint document_chunks_page_end_check check (page_end >= page_start),
    constraint document_chunks_chunk_index_check check (chunk_index >= 0),
    constraint document_chunks_text_check check (text <> ''),
    constraint document_chunks_metadata_object_check
        check (jsonb_typeof(metadata) = 'object')
);

create index if not exists document_chunks_document_id_idx
    on public.document_chunks (document_id);

create index if not exists document_chunks_document_page_idx
    on public.document_chunks (document_id, page_start, page_end);

create table if not exists public.evidence_items (
    id uuid primary key default gen_random_uuid(),
    created_at timestamptz not null default now(),
    tenant_key text not null default 'demo',
    evidence_key text not null,
    source_type text not null,
    excerpt text not null,
    normalized_meaning text not null,
    category text not null,
    confidence numeric not null,
    source_metadata jsonb not null default '{}'::jsonb,
    document_id uuid references public.documents(id) on delete cascade,
    chunk_id uuid references public.document_chunks(id) on delete cascade,
    page_start integer,
    page_end integer,
    company_id uuid references public.companies(id) on delete cascade,
    field_path text,
    metadata jsonb not null default '{}'::jsonb,
    constraint evidence_items_tenant_key_demo_check check (tenant_key = 'demo'),
    constraint evidence_items_tenant_evidence_key_key
        unique (tenant_key, evidence_key),
    constraint evidence_items_source_type_check
        check (source_type in ('tender_document', 'company_profile')),
    constraint evidence_items_confidence_check
        check (confidence >= 0 and confidence <= 1),
    constraint evidence_items_evidence_key_check check (evidence_key <> ''),
    constraint evidence_items_excerpt_check check (excerpt <> ''),
    constraint evidence_items_normalized_meaning_check
        check (normalized_meaning <> ''),
    constraint evidence_items_category_check check (category <> ''),
    constraint evidence_items_field_path_check
        check (field_path is null or field_path <> ''),
    constraint evidence_items_source_metadata_object_check
        check (jsonb_typeof(source_metadata) = 'object'),
    constraint evidence_items_source_label_check
        check (source_metadata ? 'source_label'),
    constraint evidence_items_metadata_object_check
        check (jsonb_typeof(metadata) = 'object'),
    constraint evidence_items_page_start_check
        check (page_start is null or page_start > 0),
    constraint evidence_items_page_end_check
        check (
            page_end is null
            or page_start is null
            or page_end >= page_start
        ),
    constraint evidence_items_tender_document_source_check
        check (
            source_type <> 'tender_document'
            or (
                document_id is not null
                and chunk_id is not null
                and page_start is not null
                and page_end is not null
                and company_id is null
                and field_path is null
            )
        ),
    constraint evidence_items_company_profile_source_check
        check (
            source_type <> 'company_profile'
            or (
                company_id is not null
                and field_path is not null
                and document_id is null
                and chunk_id is null
                and page_start is null
                and page_end is null
            )
        )
);

create index if not exists evidence_items_source_type_category_idx
    on public.evidence_items (source_type, category);

create index if not exists evidence_items_document_chunk_idx
    on public.evidence_items (document_id, chunk_id);

create index if not exists evidence_items_company_field_path_idx
    on public.evidence_items (company_id, field_path);
