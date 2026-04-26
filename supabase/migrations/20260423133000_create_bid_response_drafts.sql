-- Evidence-locked draft anbud packets generated from persisted Judge decisions.

CREATE TABLE IF NOT EXISTS public.bid_response_drafts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    tenant_key text NOT NULL DEFAULT 'demo',
    tender_id uuid NOT NULL REFERENCES public.tenders(id) ON DELETE CASCADE,
    agent_run_id uuid NOT NULL REFERENCES public.agent_runs(id) ON DELETE CASCADE,
    bid_id uuid REFERENCES public.bids(id) ON DELETE SET NULL,
    status text NOT NULL,
    language text NOT NULL,
    pricing_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
    answers jsonb NOT NULL DEFAULT '[]'::jsonb,
    attachment_manifest jsonb NOT NULL DEFAULT '[]'::jsonb,
    missing_info jsonb NOT NULL DEFAULT '[]'::jsonb,
    source_evidence_keys jsonb NOT NULL DEFAULT '[]'::jsonb,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT bid_response_drafts_tenant_key_demo_check
        CHECK (tenant_key = 'demo'),
    CONSTRAINT bid_response_drafts_status_check
        CHECK (status IN ('draft', 'needs_review', 'blocked')),
    CONSTRAINT bid_response_drafts_language_check CHECK (language <> ''),
    CONSTRAINT bid_response_drafts_pricing_snapshot_object_check
        CHECK (jsonb_typeof(pricing_snapshot) = 'object'),
    CONSTRAINT bid_response_drafts_answers_array_check
        CHECK (jsonb_typeof(answers) = 'array'),
    CONSTRAINT bid_response_drafts_attachment_manifest_array_check
        CHECK (jsonb_typeof(attachment_manifest) = 'array'),
    CONSTRAINT bid_response_drafts_missing_info_array_check
        CHECK (jsonb_typeof(missing_info) = 'array'),
    CONSTRAINT bid_response_drafts_source_evidence_keys_array_check
        CHECK (jsonb_typeof(source_evidence_keys) = 'array'),
    CONSTRAINT bid_response_drafts_metadata_object_check
        CHECK (jsonb_typeof(metadata) = 'object')
);

CREATE INDEX IF NOT EXISTS bid_response_drafts_run_created_idx
    ON public.bid_response_drafts (agent_run_id, created_at DESC);

CREATE INDEX IF NOT EXISTS bid_response_drafts_tender_created_idx
    ON public.bid_response_drafts (tender_id, created_at DESC);

CREATE OR REPLACE FUNCTION public._bidded_set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS bid_response_drafts_set_updated_at
    ON public.bid_response_drafts;

CREATE TRIGGER bid_response_drafts_set_updated_at
    BEFORE UPDATE ON public.bid_response_drafts
    FOR EACH ROW EXECUTE FUNCTION public._bidded_set_updated_at();
