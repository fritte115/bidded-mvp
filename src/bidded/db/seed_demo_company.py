from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Protocol

DEMO_TENANT_KEY = "demo"
DEMO_COMPANY_NAME = "Nordic Digital Delivery AB"
DEMO_COMPANY_PROFILE_LABEL = "seeded_it_consultancy"


class SupabaseCompanyTable(Protocol):
    def upsert(
        self,
        payload: dict[str, Any],
        *,
        on_conflict: str | None = None,
    ) -> Any: ...


class SupabaseTableClient(Protocol):
    def table(self, table_name: str) -> SupabaseCompanyTable: ...


@dataclass(frozen=True)
class DemoCompanySeedResult:
    company_name: str
    tenant_key: str
    profile_label: str
    rows_returned: int


_DEMO_COMPANY_PAYLOAD: dict[str, Any] = {
    "tenant_key": DEMO_TENANT_KEY,
    "name": DEMO_COMPANY_NAME,
    "profile_label": DEMO_COMPANY_PROFILE_LABEL,
    "organization_number": "559900-0417",
    "headquarters_country": "SE",
    "employee_count": 1_850,
    "annual_revenue_sek": 2_650_000_000,
    "capabilities": {
        "service_lines": {
            "cloud_platforms": [
                "Azure landing zones",
                "AWS migration",
                "Kubernetes platform engineering",
                "FinOps",
            ],
            "data_and_ai": [
                "data platform modernization",
                "analytics engineering",
                "machine learning operations",
                "responsible AI governance",
            ],
            "cybersecurity": [
                "security architecture",
                "identity and access management",
                "secure software delivery",
                "incident readiness",
            ],
            "digital_services": [
                "product discovery",
                "service design",
                "full-stack development",
                "accessibility remediation",
            ],
        },
        "delivery_capacity": {
            "available_consultants_90_days": 260,
            "available_consultants_180_days": 420,
            "delivery_centers": [
                "Stockholm",
                "Goteborg",
                "Malmo",
                "Umea",
                "nearshore EU partner network",
            ],
            "security_cleared_consultants": 145,
            "active_public_sector_delivery_teams": 38,
            "project_management_office": {
                "pmp_certified_project_managers": 31,
                "safe_program_consultants": 18,
                "quality_assurance_leads": 22,
            },
        },
        "geographic_availability": {
            "countries": ["Sweden", "Denmark", "Norway", "Finland"],
            "swedish_regions": [
                "Stockholm",
                "Vastra Gotaland",
                "Skane",
                "Vasterbotten",
                "remote nationwide",
            ],
            "delivery_model": ["onsite", "hybrid", "remote"],
            "languages": ["English", "Swedish"],
        },
    },
    "certifications": [
        {
            "name": "ISO 9001",
            "scope": "quality management for consulting and software delivery",
            "status": "active",
            "source_label": "seeded company profile",
        },
        {
            "name": "ISO 14001",
            "scope": "environmental management for Nordic operations",
            "status": "active",
            "source_label": "seeded company profile",
        },
        {
            "name": "ISO 27001",
            "scope": "information security management for managed delivery",
            "status": "active",
            "source_label": "seeded company profile",
        },
        {
            "name": "Cyber Essentials Plus",
            "scope": "baseline cyber controls for consulting delivery",
            "status": "active",
            "source_label": "seeded company profile",
        },
    ],
    "reference_projects": [
        {
            "reference_id": "ref-public-cloud-01",
            "sector": "public_sector",
            "customer_type": "national agency",
            "delivery_years": "2023-2025",
            "contract_value_band_sek": "120m-180m",
            "case_study_summary": (
                "Modernized citizen-facing case management services using Azure, "
                "API integration, accessibility testing, and secure DevOps."
            ),
            "capabilities_used": [
                "cloud_platforms",
                "digital_services",
                "cybersecurity",
            ],
            "source_label": "seeded company profile",
        },
        {
            "reference_id": "ref-health-data-02",
            "sector": "public_sector",
            "customer_type": "regional healthcare authority",
            "delivery_years": "2022-2024",
            "contract_value_band_sek": "80m-120m",
            "case_study_summary": (
                "Built a governed analytics platform for healthcare operations "
                "with strict data access controls and audit reporting."
            ),
            "capabilities_used": ["data_and_ai", "cybersecurity"],
            "source_label": "seeded company profile",
        },
        {
            "reference_id": "ref-municipal-digital-03",
            "sector": "public_sector",
            "customer_type": "municipal consortium",
            "delivery_years": "2021-2024",
            "contract_value_band_sek": "55m-90m",
            "case_study_summary": (
                "Delivered shared digital permit services across municipalities "
                "with service design, integration, and agile delivery teams."
            ),
            "capabilities_used": ["digital_services", "cloud_platforms"],
            "source_label": "seeded company profile",
        },
    ],
    "financial_assumptions": {
        "revenue_band_sek": {"min": 2_000_000_000, "max": 3_000_000_000},
        "rate_card_sek_per_hour": {
            "principal_consultant": 1_650,
            "senior_consultant": 1_350,
            "consultant": 1_050,
            "delivery_manager": 1_450,
            "security_specialist": 1_550,
        },
        "target_gross_margin_percent": 32,
        "minimum_acceptable_margin_percent": 22,
        "travel_assumption": "travel billed at cost unless tender requires fixed price",
        "pricing_notes": [
            "can staff fixed-price discovery phases",
            "prefers index-adjusted multi-year rate cards",
            "requires explicit cap for security-cleared specialist allocation",
        ],
    },
    "profile_details": {
        "company_size": "larger_it_consultancy",
        "public_sector_track_record": {
            "framework_agreement_experience": [
                "Kammarkollegiet-style framework call-offs",
                "municipal joint procurement",
                "regional healthcare procurement",
            ],
            "procurement_response_capacity": {
                "bid_managers": 9,
                "legal_reviewers": 4,
                "solution_architect_pool": 42,
            },
        },
        "cv_summaries": [
            {
                "role": "Enterprise Architect",
                "seniority": "principal",
                "average_years_experience": 18,
                "available_profiles": 14,
                "typical_certifications": ["TOGAF", "Azure Solutions Architect"],
                "languages": ["English", "Swedish"],
                "source_label": "seeded company profile",
            },
            {
                "role": "Delivery Manager",
                "seniority": "senior",
                "average_years_experience": 15,
                "available_profiles": 24,
                "typical_certifications": ["PMP", "SAFe SPC"],
                "languages": ["English", "Swedish"],
                "source_label": "seeded company profile",
            },
            {
                "role": "Senior Full-Stack Developer",
                "seniority": "senior",
                "average_years_experience": 11,
                "available_profiles": 95,
                "typical_certifications": ["Azure Developer", "AWS Developer"],
                "languages": ["English", "Swedish"],
                "source_label": "seeded company profile",
            },
            {
                "role": "Cybersecurity Specialist",
                "seniority": "senior",
                "average_years_experience": 12,
                "available_profiles": 31,
                "typical_certifications": ["CISSP", "ISO 27001 Lead Implementer"],
                "languages": ["English", "Swedish"],
                "source_label": "seeded company profile",
            },
            {
                "role": "Data Platform Engineer",
                "seniority": "senior",
                "average_years_experience": 10,
                "available_profiles": 44,
                "typical_certifications": ["Databricks", "Azure Data Engineer"],
                "languages": ["English", "Swedish"],
                "source_label": "seeded company profile",
            },
        ],
    },
    "metadata": {
        "seed_version": "2026-04-18.v1",
        "source_type": "synthetic_demo_profile",
        "source_label": "seeded company profile",
        "idempotency_key": "demo:seeded_it_consultancy:nordic-digital-delivery",
    },
}


def build_demo_company_payload() -> dict[str, Any]:
    """Return a fresh copy of the deterministic demo company row."""
    return deepcopy(_DEMO_COMPANY_PAYLOAD)


def seed_demo_company(client: SupabaseTableClient) -> DemoCompanySeedResult:
    payload = build_demo_company_payload()
    response = (
        client.table("companies")
        .upsert(payload, on_conflict="tenant_key,name")
        .execute()
    )
    data = getattr(response, "data", [])
    rows_returned = len(data) if isinstance(data, list) else 0

    return DemoCompanySeedResult(
        company_name=payload["name"],
        tenant_key=payload["tenant_key"],
        profile_label=payload["profile_label"],
        rows_returned=rows_returned,
    )
