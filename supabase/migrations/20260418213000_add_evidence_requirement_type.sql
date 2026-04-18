alter table if exists public.evidence_items
    add column if not exists requirement_type text;

do $$
begin
    if to_regclass('public.evidence_items') is not null and not exists (
        select 1
        from information_schema.table_constraints
        where table_schema = 'public'
          and table_name = 'evidence_items'
          and constraint_name = 'evidence_items_requirement_type_check'
    ) then
        alter table public.evidence_items
            add constraint evidence_items_requirement_type_check
            check (
                requirement_type is null
                or requirement_type in (
                    'shall_requirement',
                    'qualification_requirement',
                    'exclusion_ground',
                    'financial_standing',
                    'legal_or_regulatory_reference',
                    'quality_management',
                    'submission_document',
                    'contract_obligation'
                )
            );
    end if;
end $$;
