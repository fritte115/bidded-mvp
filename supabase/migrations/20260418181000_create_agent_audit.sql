create table if not exists public.agent_runs (
    id uuid primary key default gen_random_uuid(),
    created_at timestamptz not null default now(),
    tenant_key text not null default 'demo',
    tender_id uuid not null references public.tenders(id),
    company_id uuid not null references public.companies(id),
    status text not null default 'pending',
    run_config jsonb not null default '{}'::jsonb,
    error_details jsonb,
    started_at timestamptz,
    completed_at timestamptz,
    metadata jsonb not null default '{}'::jsonb,
    constraint agent_runs_tenant_key_demo_check check (tenant_key = 'demo'),
    constraint agent_runs_status_check
        check (status in ('pending', 'running', 'succeeded', 'failed',
        'needs_human_review')),
    constraint agent_runs_completion_time_check
        check (completed_at is null or started_at is not null),
    constraint agent_runs_terminal_completion_check
        check (
            completed_at is null
            or status in ('succeeded', 'failed', 'needs_human_review')
        )
);

create index if not exists agent_runs_tender_id_idx
    on public.agent_runs (tender_id);

create index if not exists agent_runs_company_id_idx
    on public.agent_runs (company_id);

create index if not exists agent_runs_status_idx
    on public.agent_runs (status);

create table if not exists public.agent_outputs (
    id uuid primary key default gen_random_uuid(),
    created_at timestamptz not null default now(),
    tenant_key text not null default 'demo',
    agent_run_id uuid not null references public.agent_runs(id),
    agent_role text not null,
    round_name text not null,
    output_type text not null,
    validated_payload jsonb not null,
    model_metadata jsonb not null default '{}'::jsonb,
    started_at timestamptz,
    completed_at timestamptz,
    duration_ms integer,
    input_tokens integer,
    output_tokens integer,
    estimated_cost_usd numeric,
    validation_errors jsonb not null default '[]'::jsonb,
    metadata jsonb not null default '{}'::jsonb,
    constraint agent_outputs_tenant_key_demo_check check (tenant_key = 'demo'),
    constraint agent_outputs_run_role_round_output_key
        unique (agent_run_id, agent_role, round_name, output_type),
    constraint agent_outputs_agent_role_check check (agent_role <> ''),
    constraint agent_outputs_round_name_check check (round_name <> ''),
    constraint agent_outputs_output_type_check check (output_type <> ''),
    constraint agent_outputs_completion_time_check
        check (completed_at is null or started_at is not null),
    constraint agent_outputs_duration_ms_check
        check (duration_ms is null or duration_ms >= 0),
    constraint agent_outputs_input_tokens_check
        check (input_tokens is null or input_tokens >= 0),
    constraint agent_outputs_output_tokens_check
        check (output_tokens is null or output_tokens >= 0),
    constraint agent_outputs_estimated_cost_usd_check
        check (estimated_cost_usd is null or estimated_cost_usd >= 0),
    constraint agent_outputs_model_metadata_object_check
        check (jsonb_typeof(model_metadata) = 'object'),
    constraint agent_outputs_validation_errors_array_check
        check (jsonb_typeof(validation_errors) = 'array')
);

create index if not exists agent_outputs_agent_run_id_idx
    on public.agent_outputs (agent_run_id);

create or replace function public.reject_agent_output_mutation()
returns trigger
language plpgsql
as $$
begin
    raise exception 'agent_outputs rows are immutable';
end;
$$;

create trigger agent_outputs_immutable_before_update
    before update or delete on public.agent_outputs
    for each row execute function public.reject_agent_output_mutation();

create table if not exists public.bid_decisions (
    id uuid primary key default gen_random_uuid(),
    created_at timestamptz not null default now(),
    tenant_key text not null default 'demo',
    agent_run_id uuid not null references public.agent_runs(id),
    final_decision jsonb not null,
    verdict text not null,
    confidence numeric not null,
    evidence_ids uuid[] not null default '{}'::uuid[],
    metadata jsonb not null default '{}'::jsonb,
    constraint bid_decisions_tenant_key_demo_check check (tenant_key = 'demo'),
    constraint bid_decisions_agent_run_id_key unique (agent_run_id),
    constraint bid_decisions_verdict_check
        check (verdict in ('bid', 'no_bid', 'conditional_bid',
        'needs_human_review')),
    constraint bid_decisions_confidence_check
        check (confidence >= 0 and confidence <= 1),
    constraint bid_decisions_final_decision_object_check
        check (jsonb_typeof(final_decision) = 'object')
);

create index if not exists bid_decisions_agent_run_id_idx
    on public.bid_decisions (agent_run_id);
