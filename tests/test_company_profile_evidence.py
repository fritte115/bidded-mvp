from __future__ import annotations

from typing import Any
from uuid import UUID

from bidded.db.seed_demo_company import build_demo_company_payload
from bidded.evidence.company_profile import (
    build_company_profile_evidence_items,
    upsert_company_profile_evidence,
)

COMPANY_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


def _item_by_path(
    evidence_items: list[dict[str, Any]],
    field_path: str,
) -> dict[str, Any]:
    return next(item for item in evidence_items if item["field_path"] == field_path)


def test_seeded_certification_converts_to_company_profile_evidence() -> None:
    evidence_items = build_company_profile_evidence_items(
        company_id=COMPANY_ID,
        company_profile=build_demo_company_payload(),
    )

    iso_27001 = _item_by_path(evidence_items, "certifications[2]")

    assert iso_27001["tenant_key"] == "demo"
    assert iso_27001["source_type"] == "company_profile"
    assert iso_27001["company_id"] == str(COMPANY_ID)
    assert iso_27001["field_path"] == "certifications[2]"
    assert iso_27001["category"] == "certification"
    assert iso_27001["source_metadata"]["source_label"] == "seeded company profile"
    assert "ISO 27001" in iso_27001["excerpt"]
    assert "information security management" in iso_27001["normalized_meaning"]
    assert 0 <= iso_27001["confidence"] <= 1


def test_seeded_reference_case_study_converts_to_evidence() -> None:
    evidence_items = build_company_profile_evidence_items(
        company_id=COMPANY_ID,
        company_profile=build_demo_company_payload(),
    )

    reference = _item_by_path(evidence_items, "reference_projects[0]")

    assert reference["category"] == "reference"
    assert "national agency" in reference["excerpt"]
    assert "Modernized citizen-facing case management" in reference["excerpt"]
    assert "120m-180m" in reference["excerpt"]
    assert "public_sector" in reference["normalized_meaning"]
    assert reference["metadata"]["reference_id"] == "ref-public-cloud-01"
    assert reference["source_metadata"]["source_label"] == "seeded company profile"


def test_seeded_cv_and_capacity_facts_convert_to_evidence() -> None:
    evidence_items = build_company_profile_evidence_items(
        company_id=COMPANY_ID,
        company_profile=build_demo_company_payload(),
    )

    capacity = _item_by_path(
        evidence_items,
        "capabilities.delivery_capacity.available_consultants_90_days",
    )
    cv_summary = _item_by_path(evidence_items, "profile_details.cv_summaries[0]")

    assert capacity["category"] == "capacity"
    assert "260 consultants" in capacity["excerpt"]
    assert "90 days" in capacity["normalized_meaning"]
    assert capacity["metadata"]["value"] == 260

    assert cv_summary["category"] == "cv_summary"
    assert "Enterprise Architect" in cv_summary["excerpt"]
    assert "14 available profiles" in cv_summary["excerpt"]
    assert "18 average years" in cv_summary["normalized_meaning"]


def test_seeded_revenue_geography_and_economics_convert_to_evidence() -> None:
    evidence_items = build_company_profile_evidence_items(
        company_id=COMPANY_ID,
        company_profile=build_demo_company_payload(),
    )

    annual_revenue = _item_by_path(evidence_items, "annual_revenue_sek")
    countries = _item_by_path(
        evidence_items,
        "capabilities.geographic_availability.countries",
    )
    rate_card = _item_by_path(
        evidence_items,
        "financial_assumptions.rate_card_sek_per_hour",
    )
    margin = _item_by_path(
        evidence_items,
        "financial_assumptions.minimum_acceptable_margin_percent",
    )

    assert annual_revenue["category"] == "revenue"
    assert "2,650,000,000 SEK" in annual_revenue["excerpt"]
    assert annual_revenue["metadata"]["amount_sek"] == 2_650_000_000

    assert countries["category"] == "geography"
    assert "Sweden, Denmark, Norway, Finland" in countries["excerpt"]

    assert rate_card["category"] == "economics"
    assert "senior_consultant: 1350 SEK/hour" in rate_card["excerpt"]
    assert rate_card["metadata"]["senior_consultant"] == 1_350

    assert margin["category"] == "economics"
    assert "minimum acceptable margin is 22%" in margin["normalized_meaning"]


class RecordingEvidenceTable:
    def __init__(self) -> None:
        self.upserts: list[tuple[list[dict[str, Any]], str | None]] = []

    def upsert(
        self,
        payload: list[dict[str, Any]],
        *,
        on_conflict: str | None = None,
    ) -> RecordingEvidenceTable:
        self.upserts.append((payload, on_conflict))
        return self

    def execute(self) -> object:
        payload = self.upserts[-1][0]
        return type("Response", (), {"data": payload})()


class RecordingSupabaseClient:
    def __init__(self) -> None:
        self.evidence_table = RecordingEvidenceTable()
        self.table_names: list[str] = []

    def table(self, table_name: str) -> RecordingEvidenceTable:
        self.table_names.append(table_name)
        assert table_name == "evidence_items"
        return self.evidence_table


def test_company_profile_evidence_upsert_is_idempotent() -> None:
    client = RecordingSupabaseClient()
    company_profile = build_demo_company_payload()

    first_result = upsert_company_profile_evidence(
        client,
        company_id=COMPANY_ID,
        company_profile=company_profile,
    )
    second_result = upsert_company_profile_evidence(
        client,
        company_id=COMPANY_ID,
        company_profile=company_profile,
    )

    assert client.table_names == ["evidence_items", "evidence_items"]
    first_payload, first_conflict = client.evidence_table.upserts[0]
    second_payload, second_conflict = client.evidence_table.upserts[1]
    assert first_payload == second_payload
    assert first_conflict == second_conflict == "tenant_key,evidence_key"
    assert (
        first_result.rows_returned == second_result.rows_returned == len(first_payload)
    )
    assert len({item["evidence_key"] for item in first_payload}) == len(first_payload)
