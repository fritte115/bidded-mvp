-- Bid pipeline table — tracks commercial bid submissions per tender.
-- This is a UI-side tracking table; the agent decision lives in bid_decisions.

CREATE TABLE bids (
  id              uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at      timestamptz  NOT NULL DEFAULT now(),
  updated_at      timestamptz  NOT NULL DEFAULT now(),
  tenant_key      text         NOT NULL DEFAULT 'demo' CHECK (tenant_key = 'demo'),
  tender_id       uuid         NOT NULL REFERENCES tenders(id) ON DELETE CASCADE,
  agent_run_id    uuid         REFERENCES agent_runs(id) ON DELETE SET NULL,
  rate_sek        numeric      NOT NULL CHECK (rate_sek > 0),
  margin_pct      numeric      NOT NULL DEFAULT 12 CHECK (margin_pct >= 0),
  hours_estimated integer      NOT NULL DEFAULT 1600 CHECK (hours_estimated > 0),
  status          text         NOT NULL DEFAULT 'draft'
                               CHECK (status IN ('draft','review','submitted','won','lost')),
  notes           text         NOT NULL DEFAULT '',
  metadata        jsonb        NOT NULL DEFAULT '{}'
);

CREATE INDEX ON bids (tenant_key, status);
CREATE INDEX ON bids (tender_id);
CREATE INDEX ON bids (agent_run_id);

-- Auto-update updated_at on every row change
CREATE OR REPLACE FUNCTION _bidded_set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

CREATE TRIGGER bids_set_updated_at
  BEFORE UPDATE ON bids
  FOR EACH ROW EXECUTE FUNCTION _bidded_set_updated_at();

-- RLS — same pattern as core domain tables
ALTER TABLE bids ENABLE ROW LEVEL SECURITY;

CREATE POLICY "anon can read demo bids"
  ON bids FOR SELECT USING (tenant_key = 'demo');

CREATE POLICY "anon can insert demo bids"
  ON bids FOR INSERT WITH CHECK (tenant_key = 'demo');

CREATE POLICY "anon can update demo bids"
  ON bids FOR UPDATE USING (tenant_key = 'demo');

CREATE POLICY "anon can delete demo bids"
  ON bids FOR DELETE USING (tenant_key = 'demo');
