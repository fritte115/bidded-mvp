insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
    'company-knowledge',
    'company-knowledge',
    false,
    52428800,
    null
)
on conflict (id) do update
set
    public = false,
    file_size_limit = coalesce(
        storage.buckets.file_size_limit,
        excluded.file_size_limit
    );

create index if not exists documents_company_profile_idx
    on public.documents (company_id, document_role, parse_status)
    where document_role = 'company_profile';

create index if not exists evidence_items_company_document_idx
    on public.evidence_items (company_id, document_id)
    where source_type = 'company_profile';

alter table if exists public.evidence_items
    drop constraint if exists evidence_items_company_profile_source_check;

alter table if exists public.evidence_items
    add constraint evidence_items_company_profile_source_check
    check (
        source_type <> 'company_profile'
        or (
            company_id is not null
            and field_path is not null
            and (
                (
                    document_id is null
                    and chunk_id is null
                    and page_start is null
                    and page_end is null
                )
                or (
                    document_id is not null
                    and chunk_id is not null
                    and page_start is not null
                    and page_end is not null
                )
            )
        )
    );
