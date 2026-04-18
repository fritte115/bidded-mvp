-- US-025: Add nullable requirement_type to evidence_items with allowed-value validation.
-- Legacy rows without requirement_type remain loadable (column is nullable).

ALTER TABLE evidence_items
  ADD COLUMN IF NOT EXISTS requirement_type text
    CHECK (
      requirement_type IS NULL OR requirement_type IN (
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

COMMENT ON COLUMN evidence_items.requirement_type IS
  'Typed procurement requirement classification per US-025. Nullable — legacy rows '
  'without classification remain valid.';
