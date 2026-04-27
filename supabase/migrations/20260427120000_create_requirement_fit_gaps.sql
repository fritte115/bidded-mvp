create table if not exists public.requirement_fit_gaps (
    id uuid primary key default gen_random_uuid(),
    created_at timestamptz not null default now(),
    tenant_key text not null default 'demo',
    agent_run_id uuid not null references public.agent_runs(id) on delete cascade,
    tender_id uuid not null references public.tenders(id) on delete cascade,
    company_id uuid not null references public.companies(id) on delete cascade,
    requirement_key text not null,
    requirement text not null,
    requirement_type text not null,
    match_status text not null,
    risk_level text not null,
    confidence numeric not null,
    assessment text not null,
    tender_evidence_refs jsonb not null default '[]'::jsonb,
    company_evidence_refs jsonb not null default '[]'::jsonb,
    tender_evidence_ids uuid[] not null default '{}'::uuid[],
    company_evidence_ids uuid[] not null default '{}'::uuid[],
    missing_info jsonb not null default '[]'::jsonb,
    recommended_actions jsonb not null default '[]'::jsonb,
    metadata jsonb not null default '{}'::jsonb,
    constraint requirement_fit_gaps_tenant_key_demo_check check (tenant_key = 'demo'),
    constraint requirement_fit_gaps_run_requirement_key
        unique (agent_run_id, requirement_key),
    constraint requirement_fit_gaps_requirement_key_check
        check (requirement_key <> ''),
    constraint requirement_fit_gaps_requirement_check check (requirement <> ''),
    constraint requirement_fit_gaps_requirement_type_check
        check (requirement_type in (
            'shall_requirement',
            'qualification_requirement',
            'exclusion_ground',
            'financial_standing',
            'legal_or_regulatory_reference',
            'quality_management',
            'submission_document',
            'contract_obligation'
        )),
    constraint requirement_fit_gaps_match_status_check
        check (match_status in ('matched', 'partial_match', 'missing_company_evidence', 'conflicting_evidence', 'stale_evidence', 'not_applicable', 'needs_human_review')),
    constraint requirement_fit_gaps_risk_level_check
        check (risk_level in ('low', 'medium', 'high')),
    constraint requirement_fit_gaps_confidence_check
        check (confidence >= 0 and confidence <= 1),
    constraint requirement_fit_gaps_assessment_check check (assessment <> ''),
    constraint requirement_fit_gaps_tender_refs_array_check
        check (jsonb_typeof(tender_evidence_refs) = 'array'),
    constraint requirement_fit_gaps_company_refs_array_check
        check (jsonb_typeof(company_evidence_refs) = 'array'),
    constraint requirement_fit_gaps_missing_info_array_check
        check (jsonb_typeof(missing_info) = 'array'),
    constraint requirement_fit_gaps_recommended_actions_array_check
        check (jsonb_typeof(recommended_actions) = 'array'),
    constraint requirement_fit_gaps_metadata_object_check
        check (jsonb_typeof(metadata) = 'object')
);

create index if not exists requirement_fit_gaps_agent_run_id_idx
    on public.requirement_fit_gaps (agent_run_id);

create index if not exists requirement_fit_gaps_run_status_idx
    on public.requirement_fit_gaps (agent_run_id, match_status);

create index if not exists requirement_fit_gaps_tender_company_idx
    on public.requirement_fit_gaps (tender_id, company_id);
