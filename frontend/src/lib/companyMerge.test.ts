import { describe, expect, it } from "vitest";
import type { Company } from "@/data/mock";
import {
  applyCompanyWebsiteImportPreview,
  mergeCompanyIntoDb,
  type CompanyWebsiteImportPreview,
  type DbCompany,
} from "./api";

function seededDbCompany(): DbCompany {
  return {
    name: "Nordic Digital Delivery AB",
    organization_number: "559900-0417",
    headquarters_country: "SE",
    employee_count: 1850,
    annual_revenue_sek: 2_650_000_000,
    capabilities: {
      service_lines: {
        cloud_platforms: ["AWS", "Azure"],
        data_and_ai: ["Snowflake", "Databricks"],
        cybersecurity: ["SOC", "IAM"],
        digital_services: ["UX", "Mobile"],
      },
      delivery_capacity: {
        available_consultants_90_days: 180,
        delivery_centers: ["Stockholm", "Malmö"],
      },
      geographic_availability: {
        countries: ["SE", "NO"],
        swedish_regions: ["Stockholm", "Skåne"],
      },
    },
    certifications: [
      {
        name: "ISO 27001",
        scope: "Information security management",
        status: "active",
        source_label: "seed",
      },
    ],
    reference_projects: [
      {
        reference_id: "ref-seed-1",
        sector: "public_sector",
        customer_type: "Swedish Municipality",
        delivery_years: "2022-2024",
        contract_value_band_sek: "12m-18m",
        case_study_summary: "Digital service platform rollout.",
        capabilities_used: ["UX", "Mobile"],
        source_label: "seed",
      },
    ],
    financial_assumptions: {
      revenue_band_sek: { min: 2_000_000_000, max: 3_000_000_000 },
      target_gross_margin_percent: 20,
      minimum_acceptable_margin_percent: 12,
      rate_card_sek_per_hour: { senior: 1650, junior: 1050 },
      travel_assumption: "Nordics on-site up to 20% of engagement",
    },
    profile_details: {
      company_size: "1 850 employees",
      cv_summaries: [
        { role: "Enterprise Architect", summary: "15+ years in regulated public sector." },
      ],
    },
    metadata: { seed_version: 7, source_type: "ralph_seed" },
  };
}

function uiCompany(): Company {
  return {
    name: "Nordic Digital Delivery AB",
    orgNumber: "559900-0417",
    size: "1 850 employees",
    hq: "Sweden",
    capabilities: ["AWS", "Azure", "Snowflake", "Databricks", "SOC", "IAM", "UX", "Mobile"],
    certifications: [
      { name: "ISO 27001", issuer: "Information security management", validUntil: "Active" },
    ],
    references: [
      {
        client: "Swedish Municipality",
        scope: "Digital service platform rollout.",
        value: "12m-18m SEK",
        year: 2022,
      },
    ],
    financialAssumptions: {
      revenueRange: "2,000 MSEK – 3,000 MSEK / year",
      targetMargin: "20%",
      maxContractSize: "Min. margin 12%",
    },
  };
}

describe("mergeCompanyIntoDb", () => {
  it("preserves nested capabilities buckets under service_lines", () => {
    const prev = seededDbCompany();
    const ui = uiCompany();

    const payload = mergeCompanyIntoDb(ui, prev);
    const caps = payload.capabilities as { service_lines: Record<string, string[]> };

    // Original four seeded categories must still be present
    expect(caps.service_lines.cloud_platforms).toEqual(["AWS", "Azure"]);
    expect(caps.service_lines.data_and_ai).toEqual(["Snowflake", "Databricks"]);
    expect(caps.service_lines.cybersecurity).toEqual(["SOC", "IAM"]);
    expect(caps.service_lines.digital_services).toEqual(["UX", "Mobile"]);

    // The flat UI list is isolated under `user_edits` so it never clobbers buckets
    expect(caps.service_lines.user_edits).toEqual(ui.capabilities);
  });

  it("preserves delivery_capacity and geographic_availability outside service_lines", () => {
    const prev = seededDbCompany();
    const payload = mergeCompanyIntoDb(uiCompany(), prev);
    const caps = payload.capabilities as {
      delivery_capacity?: Record<string, unknown>;
      geographic_availability?: Record<string, unknown>;
    };

    expect(caps.delivery_capacity).toEqual(prev.capabilities.delivery_capacity);
    expect(caps.geographic_availability).toEqual(prev.capabilities.geographic_availability);
  });

  it("keeps financial_assumptions fields the UI does not edit", () => {
    const prev = seededDbCompany();
    const payload = mergeCompanyIntoDb(uiCompany(), prev);
    const fa = payload.financial_assumptions as Record<string, unknown>;

    expect(fa.revenue_band_sek).toEqual(prev.financial_assumptions.revenue_band_sek);
    expect(fa.minimum_acceptable_margin_percent).toBe(12);
    expect(fa.rate_card_sek_per_hour).toEqual(
      prev.financial_assumptions.rate_card_sek_per_hour,
    );
    expect(fa.travel_assumption).toBe(prev.financial_assumptions.travel_assumption);
  });

  it("updates target_gross_margin_percent when UI value changes", () => {
    const prev = seededDbCompany();
    const ui = uiCompany();
    ui.financialAssumptions.targetMargin = "25%";

    const payload = mergeCompanyIntoDb(ui, prev);
    const fa = payload.financial_assumptions as Record<string, unknown>;
    expect(fa.target_gross_margin_percent).toBe(25);
  });

  it("merges certifications by name instead of replacing the array", () => {
    const prev = seededDbCompany();
    const ui = uiCompany();
    // Add a brand-new cert and keep the seeded one
    ui.certifications.push({
      name: "Cyber Essentials Plus",
      issuer: "UK cybersecurity baseline",
      validUntil: "Active",
    });

    const payload = mergeCompanyIntoDb(ui, prev);
    const certs = payload.certifications as Array<Record<string, unknown>>;

    const iso = certs.find((c) => c.name === "ISO 27001");
    expect(iso).toBeDefined();
    // Seeded source_label must survive because we merged into the existing row
    expect(iso?.source_label).toBe("seed");

    const cyber = certs.find((c) => c.name === "Cyber Essentials Plus");
    expect(cyber).toBeDefined();
    expect(cyber?.source_label).toBe("user_edit");
  });

  it("merges reference_projects by customer_type and keeps capabilities_used", () => {
    const prev = seededDbCompany();
    const ui = uiCompany();
    ui.references[0].scope = "Updated case study summary.";

    const payload = mergeCompanyIntoDb(ui, prev);
    const refs = payload.reference_projects as Array<Record<string, unknown>>;

    expect(refs).toHaveLength(1);
    expect(refs[0].customer_type).toBe("Swedish Municipality");
    expect(refs[0].case_study_summary).toBe("Updated case study summary.");
    // Seeded fields outside the UI form must survive
    expect(refs[0].capabilities_used).toEqual(["UX", "Mobile"]);
    expect(refs[0].reference_id).toBe("ref-seed-1");
  });

  it("preserves profile_details keys the UI does not edit (e.g. cv_summaries)", () => {
    const prev = seededDbCompany();
    const payload = mergeCompanyIntoDb(uiCompany(), prev);
    // profile_details is now emitted (the editor writes extended fields to it),
    // but keys the UI does not touch must pass through untouched.
    const pd = payload.profile_details as Record<string, unknown>;
    expect(pd).toBeDefined();
    expect(pd.company_size).toBe("1 850 employees");
    expect(pd.cv_summaries).toEqual(prev.profile_details.cv_summaries);
    // metadata and annual_revenue_sek are still never written.
    expect(Object.keys(payload)).not.toContain("metadata");
    expect(Object.keys(payload)).not.toContain("annual_revenue_sek");
  });

  it("updates only scalar top-level fields the UI exposes", () => {
    const prev = seededDbCompany();
    const ui = uiCompany();
    ui.name = "Nordic Digital Delivery Sverige AB";
    ui.orgNumber = "559900-9999";

    const payload = mergeCompanyIntoDb(ui, prev);
    expect(payload.name).toBe("Nordic Digital Delivery Sverige AB");
    expect(payload.organization_number).toBe("559900-9999");
    expect(payload.headquarters_country).toBe("SE");
    expect(payload.employee_count).toBe(1850);
  });

  it("round-trips extended profile_details fields with snake_case conversion", () => {
    const prev = seededDbCompany();
    const ui = uiCompany();
    ui.legalName = "Nordic Digital Delivery Sverige AB";
    ui.vatNumber = "SE559900041701";
    ui.founded = 2014;
    ui.headcount = 1850;
    ui.website = "https://example.se";
    ui.email = "tenders@example.se";
    ui.phone = "+46 8 000 00";
    ui.description = "A test description that is comfortably longer than forty characters.";
    ui.offices = ["Stockholm", "Malmö"];
    ui.industries = ["Public sector", "Healthcare"];
    ui.leadership = [
      { name: "Anna Lindberg", title: "CEO", email: "anna@example.se" },
      { name: "Johan Eriksson", title: "CTO" },
    ];
    ui.financials = [
      { year: 2023, revenueMSEK: 124, ebitMarginPct: 11.2, headcount: 78 },
      { year: 2024, revenueMSEK: 138, ebitMarginPct: 12.6, headcount: 85 },
    ];
    ui.teamComposition = [{ role: "Cloud engineers", count: 24, avgYears: 9 }];
    ui.insurance = [{ type: "Cyber", insurer: "AIG", coverage: "15 MSEK" }];
    ui.frameworkAgreements = [
      { name: "SKL", authority: "Kammarkollegiet", validUntil: "2027-03-31", status: "Active" },
    ];
    ui.securityPosture = [
      { item: "SOC monitoring", status: "Implemented", note: "Outsourced" },
      { item: "NIS2", status: "Partial" },
    ];
    ui.sustainability = {
      co2ReductionPct: 38,
      renewableEnergyPct: 100,
      diversityPct: 41,
      codeOfConductSigned: true,
    };
    ui.bidStats = {
      totalBids: 42,
      won: 18,
      lost: 17,
      inProgress: 7,
      winRatePct: 43,
      avgContractMSEK: 14,
    };

    const payload = mergeCompanyIntoDb(ui, prev);
    const pd = payload.profile_details as Record<string, unknown>;

    // Scalars
    expect(pd.legal_name).toBe(ui.legalName);
    expect(pd.vat_number).toBe(ui.vatNumber);
    expect(pd.founded).toBe(2014);
    expect(pd.headcount).toBe(1850);
    expect(pd.website).toBe(ui.website);
    expect(pd.email).toBe(ui.email);
    expect(pd.phone).toBe(ui.phone);
    expect(pd.description).toBe(ui.description);

    // Arrays of scalars preserved as-is
    expect(pd.offices).toEqual(ui.offices);
    expect(pd.industries).toEqual(ui.industries);
    expect(pd.leadership).toEqual(ui.leadership);
    expect(pd.insurance).toEqual(ui.insurance);

    // camelCase → snake_case conversion at the boundary
    expect(pd.financials).toEqual([
      { year: 2023, revenue_msek: 124, ebit_margin_pct: 11.2, headcount: 78 },
      { year: 2024, revenue_msek: 138, ebit_margin_pct: 12.6, headcount: 85 },
    ]);
    expect(pd.team_composition).toEqual([
      { role: "Cloud engineers", count: 24, avg_years: 9 },
    ]);
    expect(pd.framework_agreements).toEqual([
      { name: "SKL", authority: "Kammarkollegiet", valid_until: "2027-03-31", status: "Active" },
    ]);
    expect(pd.security_posture).toEqual([
      { item: "SOC monitoring", status: "Implemented", note: "Outsourced" },
      { item: "NIS2", status: "Partial" },
    ]);
    expect(pd.sustainability).toEqual({
      co2_reduction_pct: 38,
      renewable_energy_pct: 100,
      diversity_pct: 41,
      code_of_conduct_signed: true,
    });
    expect(pd.bid_stats).toEqual({
      total_bids: 42,
      won: 18,
      lost: 17,
      in_progress: 7,
      win_rate_pct: 43,
      avg_contract_msek: 14,
    });

    // And seeded cv_summaries still survives
    expect(pd.cv_summaries).toEqual(prev.profile_details.cv_summaries);
  });

  it("references carry sector/duration/outcome through the merge", () => {
    const prev = seededDbCompany();
    const ui = uiCompany();
    ui.references[0].sector = "Public services";
    ui.references[0].duration = "24 mo";
    ui.references[0].outcome = "Zero unplanned downtime";

    const payload = mergeCompanyIntoDb(ui, prev);
    const refs = payload.reference_projects as Array<Record<string, unknown>>;
    expect(refs[0].sector).toBe("Public services");
    expect(refs[0].duration).toBe("24 mo");
    expect(refs[0].outcome).toBe("Zero unplanned downtime");
    // Seeded fields outside UI surface still intact
    expect(refs[0].capabilities_used).toEqual(["UX", "Mobile"]);
  });

  it("applies website import previews to the editable draft without saving", () => {
    const draft = uiCompany();
    draft.capabilities = ["AWS"];
    draft.certifications = [];
    draft.references = [];
    const preview: CompanyWebsiteImportPreview = {
      source_url: "https://example.com/",
      pages: [{ url: "https://example.com/", title: "Example" }],
      profile_patch: {
        website: "https://example.com/",
        description: "Imported company description.",
        capabilities: ["AWS", "Cybersecurity"],
        certifications: [
          { name: "ISO 27001", issuer: "Website", validUntil: "Active" },
        ],
        references: [
          {
            client: "Region Skåne",
            scope: "Cloud migration programme.",
            value: "—",
            year: 2024,
          },
        ],
        securityPosture: [
          { item: "ISO 27001", status: "Implemented", note: "Website listed." },
        ],
      },
      field_sources: {
        capabilities: {
          page_url: "https://example.com/",
          excerpt: "Cloud and cybersecurity services.",
          source_label: "website:https://example.com/",
        },
      },
      warnings: ["Review imported facts before save."],
    };

    const next = applyCompanyWebsiteImportPreview(
      draft,
      preview,
      "2026-04-23T12:00:00.000Z",
    );

    expect(next.website).toBe("https://example.com/");
    expect(next.description).toBe("Imported company description.");
    expect(next.capabilities).toEqual(["AWS", "Cybersecurity"]);
    expect(next.certifications).toEqual(preview.profile_patch.certifications);
    expect(next.references).toEqual(preview.profile_patch.references);
    expect(next.securityPosture).toEqual(preview.profile_patch.securityPosture);
    expect(next.websiteImports?.[0]).toEqual({
      ...preview,
      imported_at: "2026-04-23T12:00:00.000Z",
    });
  });

  it("persists website import provenance under profile_details only", () => {
    const prev = seededDbCompany();
    const ui = uiCompany();
    ui.websiteImports = [
      {
        source_url: "https://example.com/",
        imported_at: "2026-04-23T12:00:00.000Z",
        pages: [{ url: "https://example.com/", title: "Example" }],
        profile_patch: { capabilities: ["Cybersecurity"] },
        field_sources: {},
        warnings: [],
      },
    ];

    const payload = mergeCompanyIntoDb(ui, prev);
    const pd = payload.profile_details as Record<string, unknown>;

    expect(pd.website_imports).toEqual(ui.websiteImports);
    expect(pd.cv_summaries).toEqual(prev.profile_details.cv_summaries);
  });

  it("does not overwrite existing reviewed array items when applying imports", () => {
    const draft = uiCompany();
    const preview: CompanyWebsiteImportPreview = {
      source_url: "https://example.com/",
      pages: [],
      profile_patch: {
        certifications: [
          { name: "ISO 27001", issuer: "Website", validUntil: "Active" },
        ],
        references: [
          {
            client: "Swedish Municipality",
            scope: "Imported scope.",
            value: "—",
            year: 2022,
          },
        ],
      },
      field_sources: {},
      warnings: [],
    };

    const next = applyCompanyWebsiteImportPreview(
      draft,
      preview,
      "2026-04-23T12:00:00.000Z",
    );

    expect(next.certifications[0]).toEqual(draft.certifications[0]);
    expect(next.references[0]).toEqual(draft.references[0]);
    expect(next.websiteImports?.[0].profile_patch).toEqual(preview.profile_patch);
  });
});
