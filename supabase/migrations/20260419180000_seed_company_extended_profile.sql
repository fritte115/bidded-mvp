-- Populate `companies.profile_details` with the extended fields the new
-- CompanyProfile page renders (hero, KPI strip, tabs: Overview / Capabilities
-- / References / Financials / Security & ESG). Adds contact info, leadership,
-- office list, industry tags, multi-year financial history, team composition,
-- insurance, framework agreements, security posture, sustainability metrics,
-- and bid pipeline stats.
--
-- The UI reads these via `mapDbCompany` in frontend/src/lib/api.ts — shape the
-- JSONB exactly as that reader expects (snake_case keys, the mapper converts
-- to camelCase for the React layer).
--
-- This is an UPDATE (merge) on the single demo row, not a row replacement.
-- Uses `||` so any keys already present in profile_details keep their values
-- unless they overlap with keys written here, which will be overwritten.
-- The seeded_it_consultancy profile_label is the current demo company.
--
-- Reference_projects is also enriched in-place so the Reference tab can show
-- sector / duration / outcome for each case. We rewrite the array in full to
-- keep ordering deterministic — the ralph seed remains the source of truth
-- for the *structure* of reference rows; this migration only adds UI-surface
-- metadata (`sector`, `duration`, `outcome`).

update public.companies
set
    profile_details = coalesce(profile_details, '{}'::jsonb) || jsonb_build_object(
        'legal_name', 'Acme IT Consulting Sverige AB',
        'vat_number', 'SE556677112201',
        'founded', 2008,
        'headcount', 85,
        'offices', jsonb_build_array('Stockholm (HQ)', 'Göteborg', 'Malmö', 'Linköping'),
        'website', 'https://acme-it.se',
        'email', 'tenders@acme-it.se',
        'phone', '+46 8 555 010 10',
        'description',
            'Acme IT Consulting AB is a mid-sized Swedish technology partner specialising in secure cloud transformation, identity management and platform engineering for the public sector. We combine certified delivery processes with deep regulatory expertise (NIS2, GDPR, OSL) to help authorities modernise critical systems with minimal risk.',
        'leadership', jsonb_build_array(
            jsonb_build_object('name', 'Anna Lindberg', 'title', 'CEO & Founder', 'email', 'anna.lindberg@acme-it.se'),
            jsonb_build_object('name', 'Johan Eriksson', 'title', 'CTO', 'email', 'johan.eriksson@acme-it.se'),
            jsonb_build_object('name', 'Sara Bergström', 'title', 'Head of Public Sector', 'email', 'sara.bergstrom@acme-it.se'),
            jsonb_build_object('name', 'Mikael Nyström', 'title', 'CFO', 'email', 'mikael.nystrom@acme-it.se'),
            jsonb_build_object('name', 'Linnea Holm', 'title', 'Head of Bid Management', 'email', 'linnea.holm@acme-it.se')
        ),
        'industries', jsonb_build_array(
            'Public sector', 'Healthcare', 'Transport & infrastructure', 'Defence & security', 'Municipalities'
        ),
        'financials', jsonb_build_array(
            jsonb_build_object('year', 2021, 'revenue_msek', 92, 'ebit_margin_pct', 8.4, 'headcount', 62),
            jsonb_build_object('year', 2022, 'revenue_msek', 108, 'ebit_margin_pct', 9.7, 'headcount', 71),
            jsonb_build_object('year', 2023, 'revenue_msek', 124, 'ebit_margin_pct', 11.2, 'headcount', 78),
            jsonb_build_object('year', 2024, 'revenue_msek', 138, 'ebit_margin_pct', 12.6, 'headcount', 85)
        ),
        'team_composition', jsonb_build_array(
            jsonb_build_object('role', 'Cloud & platform engineers', 'count', 24, 'avg_years', 9),
            jsonb_build_object('role', 'Cybersecurity specialists',    'count', 14, 'avg_years', 11),
            jsonb_build_object('role', 'Solution architects',          'count', 12, 'avg_years', 14),
            jsonb_build_object('role', 'Data engineers',               'count',  9, 'avg_years', 7),
            jsonb_build_object('role', 'Project & delivery managers',  'count', 11, 'avg_years', 12),
            jsonb_build_object('role', 'Bid & sales',                  'count',  6, 'avg_years', 10),
            jsonb_build_object('role', 'Support & operations',         'count',  9, 'avg_years', 6)
        ),
        'insurance', jsonb_build_array(
            jsonb_build_object('type', 'Professional liability (konsultansvar)', 'insurer', 'If Skadeförsäkring', 'coverage', '20 MSEK / claim'),
            jsonb_build_object('type', 'Cyber liability',                        'insurer', 'AIG',                'coverage', '15 MSEK / year'),
            jsonb_build_object('type', 'General liability',                      'insurer', 'If Skadeförsäkring', 'coverage', '10 MSEK / claim')
        ),
        'framework_agreements', jsonb_build_array(
            jsonb_build_object('name', 'Kammarkollegiet — IT-konsulttjänster Resurskonsulter 2023', 'authority', 'Kammarkollegiet',     'valid_until', '2027-03-31', 'status', 'Active'),
            jsonb_build_object('name', 'SKL Kommentus — Programvaror och tjänster',                 'authority', 'SKL Kommentus',       'valid_until', '2026-12-31', 'status', 'Active'),
            jsonb_build_object('name', 'Adda — Managed Security Services',                         'authority', 'Adda Inköpscentral',  'valid_until', '2026-04-30', 'status', 'Expiring')
        ),
        'security_posture', jsonb_build_array(
            jsonb_build_object('item', 'Background checks (SUA Nivå 2) for cleared staff', 'status', 'Implemented', 'note', '23 cleared consultants'),
            jsonb_build_object('item', '24/7 SOC monitoring',                              'status', 'Implemented', 'note', 'Outsourced to Truesec'),
            jsonb_build_object('item', 'Penetration testing — annual',                    'status', 'Implemented', 'note', 'Last test 2025-02'),
            jsonb_build_object('item', 'Data residency: EU/Sweden only',                  'status', 'Implemented'),
            jsonb_build_object('item', 'NIS2 readiness program',                          'status', 'Partial',     'note', 'Tracking to Q3 2026 completion'),
            jsonb_build_object('item', 'FIPS 140-3 cryptographic modules',                'status', 'Planned',     'note', 'Roadmap H2 2026')
        ),
        'sustainability', jsonb_build_object(
            'co2_reduction_pct', 38,
            'renewable_energy_pct', 100,
            'diversity_pct', 41,
            'code_of_conduct_signed', true
        ),
        'bid_stats', jsonb_build_object(
            'total_bids', 42,
            'won', 18,
            'lost', 17,
            'in_progress', 7,
            'win_rate_pct', 43,
            'avg_contract_msek', 14
        )
    ),
    -- Enrich seeded reference_projects with UI-surface fields (duration,
    -- outcome, prettier `sector` label). Keep reference_id-based identity;
    -- match each row by its reference_id and merge UI fields in.
    reference_projects = (
        select jsonb_agg(
            case
                when r->>'reference_id' = 'ref-public-cloud-01' then
                    r || jsonb_build_object(
                        'sector', 'Public services',
                        'duration', '24 mo',
                        'outcome', 'Migrated 42 workloads to Azure, zero unplanned downtime'
                    )
                when r->>'reference_id' = 'ref-health-data-02' then
                    r || jsonb_build_object(
                        'sector', 'Healthcare',
                        'duration', '18 mo',
                        'outcome', 'GDPR-compliant analytics serving 12 regional hospitals'
                    )
                when r->>'reference_id' = 'ref-municipal-digital-03' then
                    r || jsonb_build_object(
                        'sector', 'Municipality',
                        'duration', '36 mo',
                        'outcome', 'Shared permit services live across 14 municipalities'
                    )
                else r
            end
            order by r->>'reference_id'
        )
        from jsonb_array_elements(reference_projects) r
    )
where tenant_key = 'demo';
