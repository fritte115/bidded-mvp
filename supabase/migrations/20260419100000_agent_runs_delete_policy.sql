-- Allow the anon (frontend) role to delete demo agent runs and their outputs.
-- Cascade deletes on agent_outputs and bid_decisions are handled by FK constraints.

create policy "anon can delete demo agent runs"
  on agent_runs for delete
  to anon
  using (tenant_key = 'demo');

create policy "anon can delete demo agent outputs"
  on agent_outputs for delete
  to anon
  using (tenant_key = 'demo');
