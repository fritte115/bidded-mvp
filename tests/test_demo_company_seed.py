from __future__ import annotations

from typing import Any

from bidded.db.seed_demo_company import (
    DEMO_COMPANY_NAME,
    build_demo_company_payload,
    seed_demo_company,
)


class RecordingCompanyTable:
    def __init__(self) -> None:
        self.upserts: list[tuple[dict[str, Any], str | None]] = []

    def upsert(
        self,
        payload: dict[str, Any],
        *,
        on_conflict: str | None = None,
    ) -> RecordingCompanyTable:
        self.upserts.append((payload, on_conflict))
        return self

    def execute(self) -> object:
        payload = self.upserts[-1][0]
        return type("Response", (), {"data": [payload]})()


class RecordingSupabaseClient:
    def __init__(self) -> None:
        self.company_table = RecordingCompanyTable()
        self.table_names: list[str] = []

    def table(self, table_name: str) -> RecordingCompanyTable:
        self.table_names.append(table_name)
        assert table_name == "companies"
        return self.company_table


def test_demo_company_payload_represents_larger_it_consultancy() -> None:
    payload = build_demo_company_payload()

    assert payload["tenant_key"] == "demo"
    assert payload["name"] == DEMO_COMPANY_NAME
    assert payload["profile_label"] == "seeded_it_consultancy"
    assert payload["headquarters_country"] == "SE"
    assert payload["employee_count"] >= 1_000
    assert payload["annual_revenue_sek"] >= 1_000_000_000

    capabilities = payload["capabilities"]
    assert capabilities["delivery_capacity"]["available_consultants_90_days"] >= 100
    assert "Sweden" in capabilities["geographic_availability"]["countries"]
    assert "cloud_platforms" in capabilities["service_lines"]

    certifications = payload["certifications"]
    assert {item["name"] for item in certifications}.issuperset(
        {"ISO 9001", "ISO 14001", "ISO 27001"}
    )

    reference_projects = payload["reference_projects"]
    assert any(project["sector"] == "public_sector" for project in reference_projects)
    assert all(project["case_study_summary"] for project in reference_projects)

    profile_details = payload["profile_details"]
    assert len(profile_details["cv_summaries"]) >= 4
    assert any(
        cv_summary["role"] == "Enterprise Architect"
        for cv_summary in profile_details["cv_summaries"]
    )

    financial_assumptions = payload["financial_assumptions"]
    assert financial_assumptions["revenue_band_sek"]["min"] >= 1_000_000_000
    assert financial_assumptions["rate_card_sek_per_hour"]["senior_consultant"] > 0
    assert financial_assumptions["target_gross_margin_percent"] > 0


def test_seed_demo_company_upserts_one_payload_by_demo_name_for_idempotence() -> None:
    client = RecordingSupabaseClient()

    first_result = seed_demo_company(client)
    second_result = seed_demo_company(client)

    assert first_result.company_name == DEMO_COMPANY_NAME
    assert first_result.rows_returned == 1
    assert second_result.company_name == DEMO_COMPANY_NAME
    assert second_result.rows_returned == 1
    assert client.table_names == ["companies", "companies"]

    upserts = client.company_table.upserts
    assert len(upserts) == 2
    assert upserts[0][0] == upserts[1][0] == build_demo_company_payload()
    assert upserts[0][1] == upserts[1][1] == "tenant_key,name"
