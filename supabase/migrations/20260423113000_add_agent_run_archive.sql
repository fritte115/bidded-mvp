alter table if exists public.agent_runs
    add column if not exists archived_at timestamptz,
    add column if not exists archived_reason text;

do $$
begin
    if to_regclass('public.agent_runs') is not null and not exists (
        select 1
        from information_schema.table_constraints
        where table_schema = 'public'
          and table_name = 'agent_runs'
          and constraint_name = 'agent_runs_archived_reason_check'
    ) then
        alter table public.agent_runs
            add constraint agent_runs_archived_reason_check
            check (archived_reason is null or archived_reason <> '');
    end if;
end $$;

create index if not exists agent_runs_unarchived_status_idx
    on public.agent_runs (status, created_at desc) where archived_at is null;
