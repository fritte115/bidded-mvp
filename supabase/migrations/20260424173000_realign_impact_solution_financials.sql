-- Realign the demo Impact Solution profile with public company data available
-- from Allabolag/UC, Bolagsfakta and Vainu for organization number 556925-0516.
--
-- The earlier Impact reseed used plausible but partly illustrative values. This
-- follow-up keeps the vending/retail-technology business profile, but corrects
-- identity, leadership, headcount and financial history to match the latest
-- public 2024 annual-account snapshot.

update public.companies
set
    name = 'Impact Solution Scandinavia AB',
    profile_label = 'impact_solution_public_profile',
    organization_number = '556925-0516',
    headquarters_country = 'SE',
    employee_count = 7,
    annual_revenue_sek = 24901000,
    capabilities = jsonb_build_object(
        'service_lines', jsonb_build_object(
            'retail_technology', jsonb_build_array(
                'IT-based retail solutions',
                'cashless vending and payment flows',
                'connected unattended retail concepts'
            ),
            'vending_solutions', jsonb_build_array(
                'food vending machines',
                'beverage vending machines',
                'energy drink vending',
                'ice cream freezer vending',
                'workplace, gym, golf and event vending'
            ),
            'operations', jsonb_build_array(
                'machine rental',
                'installation',
                'scheduled restocking',
                'machine maintenance',
                'event pop-up vending'
            ),
            'commercial_models', jsonb_build_array(
                'rental',
                'managed vending service',
                'event pop-up hire'
            )
        ),
        'delivery_capacity', jsonb_build_object(
            'service_staff', 5,
            'administration_and_management_staff', 2,
            'registered_vehicles', 4,
            'service_regions', jsonb_build_array('Uppsala', 'Stockholm', 'Mälardalen'),
            'capacity_note', 'Capacity is seeded from public headcount and vehicle indicators; exact installed-base and SLA numbers are not publicly stated.'
        ),
        'geographic_availability', jsonb_build_object(
            'countries', jsonb_build_array('Sweden'),
            'swedish_regions', jsonb_build_array('Uppsala', 'Stockholm', 'Mälardalen'),
            'delivery_model', jsonb_build_array('onsite_install', 'scheduled_service', 'event_service'),
            'languages', jsonb_build_array('Swedish', 'English')
        )
    ),
    certifications = jsonb_build_array(),
    reference_projects = jsonb_build_array(
        jsonb_build_object(
            'reference_id', 'segment-workplaces',
            'sector', 'Workplaces',
            'customer_type', 'Companies and offices',
            'delivery_years', 'public website profile',
            'contract_value_band_sek', 'not publicly disclosed',
            'case_study_summary', 'Impact Solution offers companies rental vending-machine concepts for workplace food, drink and energy products.',
            'capabilities_used', jsonb_build_array('vending_solutions', 'operations', 'commercial_models'),
            'source_label', 'impactsolution.se public website profile'
        ),
        jsonb_build_object(
            'reference_id', 'segment-fitness-golf-events',
            'sector', 'Fitness, golf and events',
            'customer_type', 'Gyms, golf courses and event venues',
            'delivery_years', 'public website profile',
            'contract_value_band_sek', 'not publicly disclosed',
            'case_study_summary', 'Public profile material describes vending-machine rental for gyms, golf courses and event environments.',
            'capabilities_used', jsonb_build_array('vending_solutions', 'operations'),
            'source_label', 'impactsolution.se public website profile'
        )
    ),
    financial_assumptions = coalesce(financial_assumptions, '{}'::jsonb) || jsonb_build_object(
        'revenue_band_sek', jsonb_build_object('min', 12970000, 'max', 24901000),
        'target_gross_margin_percent', 10,
        'minimum_acceptable_margin_percent', 3,
        'latest_public_financial_year', 2024,
        'latest_public_net_revenue_sek', 24700000,
        'latest_public_other_revenue_sek', 201000,
        'latest_public_revenue_sek', 24901000,
        'latest_public_operating_expenses_sek', -24881000,
        'latest_public_operating_result_after_depreciation_sek', 21000,
        'latest_public_financial_income_sek', 2000,
        'latest_public_financial_expenses_sek', -127000,
        'latest_public_result_after_financial_items_sek', -104000,
        'latest_public_result_before_tax_sek', -104000,
        'latest_public_tax_sek', 0,
        'latest_public_net_income_sek', -104000,
        'latest_public_ebitda_sek', 580000,
        'latest_public_assets_sek', 11187000,
        'latest_public_equity_sek', 1511000,
        'latest_public_equity_ratio_percent', 14.9,
        'public_financial_source_label', 'Allabolag/UC, Bolagsfakta and Vainu public company data',
        'pricing_notes', jsonb_build_array(
            'Public annual-account figures show a small 2024 profit margin and negative result after financial items.',
            'Bid margins remain internal commercial assumptions and should not be treated as public booked margins.'
        )
    ),
    profile_details = coalesce(profile_details, '{}'::jsonb) || jsonb_build_object(
        'company_size', '7 employees',
        'legal_name', 'Impact Solution Scandinavia AB',
        'vat_number', 'SE556925051601',
        'founded', 2013,
        'headcount', 7,
        'offices', jsonb_build_array('Tiundagatan 59, 752 30 Uppsala'),
        'website', 'https://www.impactsolution.se',
        'description',
            'Impact Solution Scandinavia AB is an Uppsala-based company focused on IT-based retail solutions and rental vending concepts for workplaces, gyms, golf courses and events. Public annual-account data for 2024 shows 24.901 MSEK total revenue, 24.700 MSEK net revenue, 7 employees, 21 KSEK operating result after depreciation, -104 KSEK result after financial items, 11.187 MSEK total assets and 1.511 MSEK equity.',
        'leadership', jsonb_build_array(
            jsonb_build_object('name', 'Bernt Tore Jonsson', 'title', 'CEO'),
            jsonb_build_object('name', 'Johan Michael Green', 'title', 'Chair / board member'),
            jsonb_build_object('name', 'Lars Erik Magnus Nilsson', 'title', 'Board member')
        ),
        'industries', jsonb_build_array(
            'IT-based retail solutions',
            'Vending and unattended retail',
            'Workplace food and beverage service',
            'Events and leisure'
        ),
        'financials', jsonb_build_array(
            jsonb_build_object('year', 2020, 'revenue_msek', 12.970, 'ebit_margin_pct', 13.4, 'headcount', 1),
            jsonb_build_object('year', 2021, 'revenue_msek', 18.376, 'ebit_margin_pct', 13.2, 'headcount', 3),
            jsonb_build_object('year', 2022, 'revenue_msek', 20.093, 'ebit_margin_pct', -4.1, 'headcount', 5),
            jsonb_build_object('year', 2023, 'revenue_msek', 22.112, 'ebit_margin_pct', -2.1, 'headcount', 6),
            jsonb_build_object('year', 2024, 'revenue_msek', 24.901, 'ebit_margin_pct', 0.1,  'headcount', 7)
        ),
        'public_financial_statement_history', jsonb_build_array(
            jsonb_build_object(
                'year', 2020,
                'currency_code', 'SEK',
                'net_revenue_ksek', 12884,
                'other_revenue_ksek', 86,
                'total_revenue_ksek', 12970,
                'inventory_change_ksek', 0,
                'operating_expenses_ksek', -11234,
                'operating_result_after_depreciation_ksek', 1736,
                'financial_income_ksek', 0,
                'financial_expenses_ksek', -5,
                'result_after_financial_net_ksek', 1731,
                'result_before_tax_ksek', 1391,
                'tax_ksek', -225,
                'net_income_ksek', 1166,
                'source_label', 'Allabolag/UC public company data'
            ),
            jsonb_build_object(
                'year', 2021,
                'currency_code', 'SEK',
                'net_revenue_ksek', 17072,
                'other_revenue_ksek', 1304,
                'total_revenue_ksek', 18376,
                'inventory_change_ksek', 0,
                'operating_expenses_ksek', -15955,
                'operating_result_after_depreciation_ksek', 2420,
                'financial_income_ksek', 0,
                'financial_expenses_ksek', -7,
                'result_after_financial_net_ksek', 2414,
                'result_before_tax_ksek', 1814,
                'tax_ksek', -408,
                'net_income_ksek', 1406,
                'source_label', 'Allabolag/UC public company data'
            ),
            jsonb_build_object(
                'year', 2022,
                'currency_code', 'SEK',
                'net_revenue_ksek', 19442,
                'other_revenue_ksek', 651,
                'total_revenue_ksek', 20093,
                'inventory_change_ksek', 0,
                'operating_expenses_ksek', -20924,
                'operating_result_after_depreciation_ksek', -830,
                'financial_income_ksek', 0,
                'financial_expenses_ksek', -29,
                'result_after_financial_net_ksek', -859,
                'result_before_tax_ksek', -519,
                'tax_ksek', -34,
                'net_income_ksek', -553,
                'source_label', 'Allabolag/UC public company data'
            ),
            jsonb_build_object(
                'year', 2023,
                'currency_code', 'SEK',
                'net_revenue_ksek', 21802,
                'other_revenue_ksek', 310,
                'total_revenue_ksek', 22112,
                'inventory_change_ksek', 0,
                'operating_expenses_ksek', -22585,
                'operating_result_after_depreciation_ksek', -473,
                'financial_income_ksek', 3,
                'financial_expenses_ksek', -45,
                'result_after_financial_net_ksek', -515,
                'result_before_tax_ksek', -115,
                'tax_ksek', 0,
                'net_income_ksek', -115,
                'source_label', 'Allabolag/UC public company data'
            ),
            jsonb_build_object(
                'year', 2024,
                'currency_code', 'SEK',
                'net_revenue_ksek', 24700,
                'other_revenue_ksek', 201,
                'total_revenue_ksek', 24901,
                'inventory_change_ksek', 0,
                'operating_expenses_ksek', -24881,
                'operating_result_after_depreciation_ksek', 21,
                'financial_income_ksek', 2,
                'financial_expenses_ksek', -127,
                'result_after_financial_net_ksek', -104,
                'result_before_tax_ksek', -104,
                'tax_ksek', 0,
                'net_income_ksek', -104,
                'source_label', 'Allabolag/UC public company data'
            )
        ),
        'team_composition', jsonb_build_array(
            jsonb_build_object('role', 'Service and operations', 'count', 5, 'avg_years', 6),
            jsonb_build_object('role', 'Management and administration', 'count', 2, 'avg_years', 10)
        ),
        'insurance', jsonb_build_array(),
        'framework_agreements', jsonb_build_array(),
        'public_financial_snapshot', jsonb_build_object(
            'financial_year', 2024,
            'currency_code', 'SEK',
            'net_revenue_ksek', 24700,
            'other_revenue_ksek', 201,
            'revenue_ksek', 24901,
            'inventory_change_ksek', 0,
            'operating_expenses_ksek', -24881,
            'operating_result_after_depreciation_ksek', 21,
            'financial_income_ksek', 2,
            'financial_expenses_ksek', -127,
            'result_after_financial_items_ksek', -104,
            'result_before_tax_ksek', -104,
            'tax_ksek', 0,
            'net_income_ksek', -104,
            'ebitda_ksek', 580,
            'total_assets_ksek', 11187,
            'equity_ksek', 1511,
            'equity_ratio_percent', 14.9,
            'cash_liquidity_percent', 52.0,
            'source_label', 'Allabolag/UC, Bolagsfakta and Vainu public company data'
        )
    ),
    metadata = coalesce(metadata, '{}'::jsonb) || jsonb_build_object(
        'source_type', 'impact_solution_public_profile',
        'profile_reseed_at', now(),
        'source_label', 'Allabolag/UC, Bolagsfakta and Vainu public company data',
        'source_urls', jsonb_build_array(
            'https://www.allabolag.se/foretag/impact-solution-scandinavia-ab/uppsala/konsulter/2K3SD78I5YF3I',
            'https://www.bolagsfakta.se/5569250516-Impact_Solution_Scandinavia_AB',
            'https://search.vainu.com/company/impact-solution-scandinavia-ab-omsattning-och-nyckeltal/SE5569250516/foretagsinfo'
        )
    )
where tenant_key = 'demo'
  and name = 'Impact Solution Scandinavia AB';
