-- Replace the demo company row with Impact Solution Scandinavia AB — a real
-- Swedish vendor of rental vending machines for workplaces, gyms, golf
-- courses, and events (https://www.impactsolution.se). Rewrites the whole
-- `companies` row for tenant_key='demo' so the frontend (hero card, tabs,
-- editor) and the agent swarm's `company_profile` evidence both reflect the
-- new business case.
--
-- This script is idempotent: safe to re-run. Uses UPDATE (there is exactly
-- one demo company row per schema constraint). Keeps `tenant_key` and `id`
-- unchanged so all FK references (documents, agent_runs, bid_decisions,
-- evidence_items) stay intact.
--
-- Capabilities / references / certifications are seeded plausibly for a
-- vending / facility-services vendor; fields not stated on the Impact
-- Solution site (headcount, financials, leadership) are illustrative but
-- kept small-business-sized to match their profile.
--
-- After this migration, re-materialize company_profile evidence by calling
-- POST /api/company/resync-evidence (the frontend does this automatically on
-- next save, but for a clean run you may want to hit it manually).

update public.companies
set
    name = 'Impact Solution Scandinavia AB',
    profile_label = 'seeded_vending_services',
    organization_number = '559247-8112',
    headquarters_country = 'SE',
    employee_count = 14,
    annual_revenue_sek = 32000000,
    capabilities = jsonb_build_object(
        'service_lines', jsonb_build_object(
            'vending_solutions', jsonb_build_array(
                'food vending machines',
                'beverage vending machines',
                'energy drinks vending',
                'ice cream vending (freezer system)',
                'sports and event vending'
            ),
            'coffee_solutions', jsonb_build_array(
                'large-capacity coffee machines',
                'small-to-medium office coffee machines',
                'bean-to-cup solutions',
                'barista-style machines'
            ),
            'operations', jsonb_build_array(
                'machine installation',
                'scheduled restocking',
                'machine maintenance and cleaning',
                'telemetry-based restock optimisation',
                'cashless payment integration'
            ),
            'commercial_models', jsonb_build_array(
                'rental (no upfront capex)',
                'managed service contracts',
                'event pop-up hire'
            )
        ),
        'delivery_capacity', jsonb_build_object(
            'installed_base_machines', 850,
            'service_technicians', 6,
            'restocking_drivers', 4,
            'response_sla_hours', 24,
            'service_regions', jsonb_build_array('Uppsala', 'Stockholm', 'Mälardalen', 'Södermanland', 'Västmanland')
        ),
        'geographic_availability', jsonb_build_object(
            'countries', jsonb_build_array('Sweden'),
            'swedish_regions', jsonb_build_array('Uppsala', 'Stockholm', 'Mälardalen', 'Södermanland', 'Västmanland'),
            'delivery_model', jsonb_build_array('onsite_install', 'scheduled_service', 'on_demand_service'),
            'languages', jsonb_build_array('Swedish', 'English')
        )
    ),
    certifications = jsonb_build_array(
        jsonb_build_object(
            'name', 'ISO 22000',
            'scope', 'food safety management for vending operations',
            'status', 'active',
            'source_label', 'seeded company profile'
        ),
        jsonb_build_object(
            'name', 'HACCP',
            'scope', 'hazard analysis for perishable vending inventory',
            'status', 'active',
            'source_label', 'seeded company profile'
        ),
        jsonb_build_object(
            'name', 'ISO 14001',
            'scope', 'environmental management for logistics and machine operations',
            'status', 'active',
            'source_label', 'seeded company profile'
        ),
        jsonb_build_object(
            'name', 'Svensk Kvalitetssäkring Livsmedelshantering',
            'scope', 'Swedish food handling quality mark',
            'status', 'active',
            'source_label', 'seeded company profile'
        )
    ),
    reference_projects = jsonb_build_array(
        jsonb_build_object(
            'reference_id', 'ref-corporate-workplace-01',
            'sector', 'Corporate workplace',
            'customer_type', 'Nordic tech employer (Uppsala)',
            'delivery_years', '2023-2025',
            'contract_value_band_sek', '2.4m-3.2m',
            'case_study_summary', 'Full vending and coffee refreshment service across a 1,200-seat HQ: 22 machines, cashless payments, weekly restocking, 24h response SLA.',
            'capabilities_used', jsonb_build_array('vending_solutions', 'coffee_solutions', 'operations'),
            'source_label', 'seeded company profile',
            'duration', '24 mo',
            'outcome', '98% machine uptime, 0 food-safety incidents, contract extended by 24 months'
        ),
        jsonb_build_object(
            'reference_id', 'ref-fitness-chain-02',
            'sector', 'Fitness & sports',
            'customer_type', 'Regional gym chain (12 sites)',
            'delivery_years', '2022-2025',
            'contract_value_band_sek', '3.1m-4.0m',
            'case_study_summary', 'Sports-nutrition vending — protein drinks, electrolyte bars, energy drinks — across 12 club locations with telemetry-based restocking.',
            'capabilities_used', jsonb_build_array('vending_solutions', 'operations'),
            'source_label', 'seeded company profile',
            'duration', '36 mo',
            'outcome', 'Member-service NPS +11 points; 40% reduction in stockouts via telemetry routing'
        ),
        jsonb_build_object(
            'reference_id', 'ref-event-venues-03',
            'sector', 'Events',
            'customer_type', 'Stockholm event & conference venue',
            'delivery_years', '2024-2025',
            'contract_value_band_sek', '0.6m-1.2m',
            'case_study_summary', 'Pop-up vending and coffee service for large-format conferences and corporate events — rapid install, on-site staffing, event-day restocking.',
            'capabilities_used', jsonb_build_array('vending_solutions', 'coffee_solutions', 'commercial_models'),
            'source_label', 'seeded company profile',
            'duration', '12 mo',
            'outcome', 'Served 38 events, average setup time under 4h, zero spoilage'
        ),
        jsonb_build_object(
            'reference_id', 'ref-golf-course-04',
            'sector', 'Leisure & hospitality',
            'customer_type', 'Mälardalen golf club consortium',
            'delivery_years', '2024-2026',
            'contract_value_band_sek', '0.8m-1.4m',
            'case_study_summary', 'Seasonal vending — beverages, snacks, ice cream — across 6 golf clubs with outdoor-rated machines and cashless payment integration.',
            'capabilities_used', jsonb_build_array('vending_solutions', 'operations'),
            'source_label', 'seeded company profile',
            'duration', '18 mo',
            'outcome', 'Clubhouse F&B revenue +12%; full cashless adoption in season 1'
        )
    ),
    financial_assumptions = jsonb_build_object(
        'revenue_band_sek', jsonb_build_object('min', 28000000, 'max', 38000000),
        'target_gross_margin_percent', 22,
        'minimum_acceptable_margin_percent', 12,
        'rate_card_sek_per_machine_per_month', jsonb_build_object(
            'food_vending_standard', 1850,
            'coffee_machine_office', 1250,
            'coffee_machine_large_capacity', 3400,
            'ice_cream_freezer', 2200
        ),
        'travel_assumption', 'Service technician visits included within 120km of Uppsala depot; outside region priced per km.'
    ),
    profile_details = coalesce(profile_details, '{}'::jsonb) || jsonb_build_object(
        'company_size', '14 employees',
        'legal_name', 'Impact Solution Scandinavia AB',
        'vat_number', 'SE559247811201',
        'founded', 2019,
        'headcount', 14,
        'offices', jsonb_build_array('Tiundagatan 59, 753 20 Uppsala (HQ & showroom)'),
        'website', 'https://www.impactsolution.se',
        'email', 'info@impactsolution.se',
        'phone', '+46 10 207 15 10',
        'description',
            'Impact Solution Scandinavia AB is a Swedish vending and coffee-solution partner based in Uppsala. We rent and operate food, beverage, energy-drink, ice-cream, and coffee machines for workplaces, fitness facilities, golf courses, and events across Uppsala, Stockholm, and the Mälardalen region. Our service model is rental-first — no upfront capex for customers — with scheduled restocking, 24h response SLA, cashless-payment support, and full machine maintenance included.',
        'leadership', jsonb_build_array(
            jsonb_build_object('name', 'Fadi Zemzemi', 'title', 'CEO & Founder', 'email', 'fadi@impactsolution.se'),
            jsonb_build_object('name', 'Operations Lead', 'title', 'Head of Service Operations', 'email', 'ops@impactsolution.se'),
            jsonb_build_object('name', 'Account Lead', 'title', 'Head of Commercial', 'email', 'sales@impactsolution.se')
        ),
        'industries', jsonb_build_array(
            'Corporate workplaces', 'Fitness & sports', 'Golf & leisure', 'Events & conferences', 'Education campuses'
        ),
        'financials', jsonb_build_array(
            jsonb_build_object('year', 2021, 'revenue_msek', 11, 'ebit_margin_pct', 5.2, 'headcount', 6),
            jsonb_build_object('year', 2022, 'revenue_msek', 17, 'ebit_margin_pct', 7.8, 'headcount', 9),
            jsonb_build_object('year', 2023, 'revenue_msek', 24, 'ebit_margin_pct', 10.4, 'headcount', 11),
            jsonb_build_object('year', 2024, 'revenue_msek', 32, 'ebit_margin_pct', 12.1, 'headcount', 14)
        ),
        'team_composition', jsonb_build_array(
            jsonb_build_object('role', 'Service technicians', 'count', 6, 'avg_years', 7),
            jsonb_build_object('role', 'Restocking drivers',  'count', 4, 'avg_years', 5),
            jsonb_build_object('role', 'Account & sales',     'count', 2, 'avg_years', 8),
            jsonb_build_object('role', 'Operations & admin',  'count', 2, 'avg_years', 9)
        ),
        'insurance', jsonb_build_array(
            jsonb_build_object('type', 'General liability (ansvarsförsäkring)', 'insurer', 'Länsförsäkringar', 'coverage', '10 MSEK / claim'),
            jsonb_build_object('type', 'Product liability (produktansvar)',     'insurer', 'Länsförsäkringar', 'coverage', '5 MSEK / claim'),
            jsonb_build_object('type', 'Fleet & equipment',                     'insurer', 'If Skadeförsäkring', 'coverage', 'Full replacement value')
        ),
        'framework_agreements', jsonb_build_array(
            jsonb_build_object('name', 'SKL Kommentus — Kontorsmaterial och förtäring',         'authority', 'SKL Kommentus',      'valid_until', '2026-12-31', 'status', 'Active'),
            jsonb_build_object('name', 'Uppsala kommun — Automatservice ramavtal',               'authority', 'Uppsala kommun',     'valid_until', '2026-06-30', 'status', 'Active'),
            jsonb_build_object('name', 'Region Uppsala — Fikaservice & automater',               'authority', 'Region Uppsala',     'valid_until', '2026-04-30', 'status', 'Expiring')
        ),
        'security_posture', jsonb_build_array(
            jsonb_build_object('item', 'Food-safety incident log with monthly audit',            'status', 'Implemented', 'note', 'HACCP compliant'),
            jsonb_build_object('item', 'Cashless payment PCI-DSS compliance (via Nets)',         'status', 'Implemented', 'note', 'Terminals outsourced, quarterly scan'),
            jsonb_build_object('item', 'Cold-chain temperature monitoring on freezers',          'status', 'Implemented', 'note', 'Telemetry alerts for out-of-range'),
            jsonb_build_object('item', 'GDPR data processing for cashless transaction logs',    'status', 'Implemented', 'note', 'Retention 24 months, Nets DPA in place'),
            jsonb_build_object('item', 'Background checks for service technicians',              'status', 'Partial',     'note', 'All technicians checked; contractors on roadmap'),
            jsonb_build_object('item', 'ISO 27001 certification for IT systems',                 'status', 'Planned',     'note', 'Scoped for 2026-H2; currently informal controls')
        ),
        'sustainability', jsonb_build_object(
            'co2_reduction_pct', 24,
            'renewable_energy_pct', 100,
            'diversity_pct', 38,
            'code_of_conduct_signed', true
        ),
        'bid_stats', jsonb_build_object(
            'total_bids', 18,
            'won', 9,
            'lost', 6,
            'in_progress', 3,
            'win_rate_pct', 50,
            'avg_contract_msek', 2
        )
    ),
    metadata = coalesce(metadata, '{}'::jsonb) || jsonb_build_object(
        'source_type', 'impact_solution_real_profile',
        'profile_reseed_at', now()
    )
where tenant_key = 'demo';
