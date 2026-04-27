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


def test_public_financial_snapshot_converts_to_financial_standing_evidence() -> None:
    company_profile = build_demo_company_payload()
    company_profile["profile_details"] = {
        **company_profile["profile_details"],
        "public_financial_snapshot": {
            "financial_year": 2024,
            "revenue_ksek": 24901,
            "result_after_financial_items_ksek": -104,
            "ebitda_ksek": 580,
            "total_assets_ksek": 11187,
            "equity_ksek": 1511,
            "equity_ratio_percent": 14.9,
            "cash_liquidity_percent": 52.0,
            "source_label": "Allabolag/UC public company data",
        },
    }

    evidence_items = build_company_profile_evidence_items(
        company_id=COMPANY_ID,
        company_profile=company_profile,
    )

    financial_snapshot = _item_by_path(
        evidence_items,
        "profile_details.public_financial_snapshot",
    )

    assert financial_snapshot["category"] == "financial_standing"
    assert "2024 public financial snapshot" in financial_snapshot["excerpt"]
    assert "24,901 KSEK" in financial_snapshot["excerpt"]
    assert "-104 KSEK" in financial_snapshot["excerpt"]
    assert "14.9%" in financial_snapshot["excerpt"]
    assert "public annual-account snapshot" in financial_snapshot["normalized_meaning"]
    assert financial_snapshot["metadata"]["financial_year"] == 2024
    assert financial_snapshot["metadata"]["revenue_ksek"] == 24901
    assert (
        financial_snapshot["source_metadata"]["source_label"]
        == "Allabolag/UC public company data"
    )


def test_public_financial_statement_history_converts_to_evidence() -> None:
    company_profile = build_demo_company_payload()
    company_profile["profile_details"] = {
        **company_profile["profile_details"],
        "public_financial_statement_history": [
            {
                "year": 2020,
                "net_revenue_ksek": 12884,
                "other_revenue_ksek": 86,
                "total_revenue_ksek": 12970,
                "operating_expenses_ksek": -11234,
                "operating_result_after_depreciation_ksek": 1736,
                "financial_income_ksek": 0,
                "financial_expenses_ksek": -5,
                "result_after_financial_net_ksek": 1731,
                "result_before_tax_ksek": 1391,
                "tax_ksek": -225,
                "net_income_ksek": 1166,
            },
            {
                "year": 2024,
                "net_revenue_ksek": 24700,
                "other_revenue_ksek": 201,
                "total_revenue_ksek": 24901,
                "operating_expenses_ksek": -24881,
                "operating_result_after_depreciation_ksek": 21,
                "financial_income_ksek": 2,
                "financial_expenses_ksek": -127,
                "result_after_financial_net_ksek": -104,
                "result_before_tax_ksek": -104,
                "tax_ksek": 0,
                "net_income_ksek": -104,
            },
        ],
    }

    evidence_items = build_company_profile_evidence_items(
        company_id=COMPANY_ID,
        company_profile=company_profile,
    )

    history = _item_by_path(
        evidence_items,
        "profile_details.public_financial_statement_history",
    )

    assert history["category"] == "financial_standing"
    assert "2020-2024 public financial statement history" in history["excerpt"]
    assert "2020: revenue 12,970 KSEK" in history["excerpt"]
    assert "2024: revenue 24,901 KSEK" in history["excerpt"]
    assert "revenue grew from 12,970 KSEK in 2020 to 24,901 KSEK in 2024" in (
        history["normalized_meaning"]
    )
    assert history["metadata"]["first_year"] == 2020
    assert history["metadata"]["latest_year"] == 2024


def test_profile_financials_convert_to_revenue_margin_trend_evidence() -> None:
    company_profile = build_demo_company_payload()
    company_profile["profile_details"] = {
        **company_profile["profile_details"],
        "public_financial_statement_history": [],
        "financials": [
            {
                "year": 2020,
                "revenue_msek": 12.970,
                "ebit_margin_pct": 13.4,
                "headcount": 1,
            },
            {
                "year": 2024,
                "revenue_msek": 24.901,
                "ebit_margin_pct": 0.1,
                "headcount": 7,
            },
        ],
    }

    evidence_items = build_company_profile_evidence_items(
        company_id=COMPANY_ID,
        company_profile=company_profile,
    )

    trend = _item_by_path(evidence_items, "profile_details.financials")

    assert trend["category"] == "financial_standing"
    assert "2020-2024 public financial trend" in trend["excerpt"]
    assert "2020: revenue 12.970 MSEK, EBIT margin 13.4%" in trend["excerpt"]
    assert "2024: revenue 24.901 MSEK, EBIT margin 0.1%" in trend["excerpt"]
    assert (
        "revenue grew from 12.970 MSEK in 2020 to 24.901 MSEK in 2024"
        in trend["normalized_meaning"]
    )
    assert "latest EBIT margin 0.1%" in trend["normalized_meaning"]
    assert trend["metadata"]["first_year"] == 2020
    assert trend["metadata"]["latest_year"] == 2024
    assert trend["metadata"]["latest_ebit_margin_pct"] == 0.1


def test_imported_website_profile_facts_convert_to_evidence() -> None:
    company_profile = build_demo_company_payload()
    company_profile["profile_details"] = {
        **company_profile["profile_details"],
        "website_imports": [
            {
                "source_url": "https://example.com/",
                "imported_at": "2026-04-23T12:00:00Z",
                "pages": [{"url": "https://example.com/", "title": "Example"}],
                "profile_patch": {
                    "description": (
                        "Nordic Digital Delivery builds secure cloud platforms "
                        "for Swedish public sector buyers."
                    ),
                    "capabilities": ["Cloud migration", "Cybersecurity"],
                    "certifications": [
                        {
                            "name": "ISO 27001",
                            "issuer": "Website",
                            "validUntil": "Active",
                        }
                    ],
                    "references": [
                        {
                            "client": "Region Skåne",
                            "scope": "Cloud migration programme.",
                            "value": "—",
                            "year": 2024,
                        }
                    ],
                    "securityPosture": [
                        {
                            "item": "ISO 27001",
                            "status": "Implemented",
                            "note": "Listed on the website.",
                        }
                    ],
                },
                "field_sources": {
                    "description": {
                        "page_url": "https://example.com/",
                        "excerpt": (
                            "Nordic Digital Delivery builds secure cloud platforms "
                            "for Swedish public sector buyers."
                        ),
                        "source_label": "website:https://example.com/",
                    },
                    "capabilities": {
                        "page_url": "https://example.com/",
                        "excerpt": (
                            "Services include cloud migration and cybersecurity."
                        ),
                        "source_label": "website:https://example.com/",
                    },
                    "certifications": {
                        "page_url": "https://example.com/",
                        "excerpt": "We are ISO 27001 certified.",
                        "source_label": "website:https://example.com/",
                    },
                    "references": {
                        "page_url": "https://example.com/",
                        "excerpt": (
                            "Case study: Region Skåne cloud migration programme."
                        ),
                        "source_label": "website:https://example.com/",
                    },
                    "securityPosture": {
                        "page_url": "https://example.com/",
                        "excerpt": "We are ISO 27001 certified.",
                        "source_label": "website:https://example.com/",
                    },
                },
                "warnings": [],
            }
        ],
    }

    evidence_items = build_company_profile_evidence_items(
        company_id=COMPANY_ID,
        company_profile=company_profile,
    )

    imported = [
        item
        for item in evidence_items
        if item["field_path"].startswith("profile_details.website_imports[0]")
    ]

    assert {item["category"] for item in imported} >= {
        "profile_summary",
        "capability",
        "certification",
        "reference",
        "security",
    }
    assert all(
        item["source_metadata"]["source_label"] == "website:https://example.com/"
        for item in imported
    )
    capability = _item_by_path(
        evidence_items,
        "profile_details.website_imports[0].profile_patch.capabilities",
    )
    assert "Cloud migration, Cybersecurity" in capability["excerpt"]
    assert capability["metadata"]["source_url"] == "https://example.com/"


class RecordingEvidenceTable:
    def __init__(self) -> None:
        self.upserts: list[tuple[list[dict[str, Any]], str | None]] = []
        self.deletes: list[tuple[tuple[str, object], ...]] = []
        self._operation = "upsert"
        self._filters: list[tuple[str, object]] = []

    def upsert(
        self,
        payload: list[dict[str, Any]],
        *,
        on_conflict: str | None = None,
    ) -> RecordingEvidenceTable:
        self._operation = "upsert"
        self.upserts.append((payload, on_conflict))
        return self

    def delete(self) -> RecordingEvidenceTable:
        self._operation = "delete"
        self._filters = []
        return self

    def eq(self, column: str, value: object) -> RecordingEvidenceTable:
        self._filters.append((f"eq:{column}", value))
        return self

    def is_(self, column: str, value: object) -> RecordingEvidenceTable:
        self._filters.append((f"is:{column}", value))
        return self

    @property
    def not_(self) -> RecordingEvidenceTable:
        self._filters.append(("not", True))
        return self

    def in_(self, column: str, values: object) -> RecordingEvidenceTable:
        self._filters.append((f"in:{column}", values))
        return self

    def execute(self) -> object:
        if self._operation == "delete":
            self.deletes.append(tuple(self._filters))
            return type("Response", (), {"data": []})()
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


def test_company_profile_evidence_upsert_deletes_stale_generated_rows() -> None:
    client = RecordingSupabaseClient()
    company_profile = build_demo_company_payload()

    upsert_company_profile_evidence(
        client,
        company_id=COMPANY_ID,
        company_profile=company_profile,
    )

    payload, _ = client.evidence_table.upserts[0]
    expected_keys = sorted(item["evidence_key"] for item in payload)
    assert client.evidence_table.deletes == [
        (
            ("eq:tenant_key", "demo"),
            ("eq:source_type", "company_profile"),
            ("eq:company_id", str(COMPANY_ID)),
            ("is:document_id", "null"),
            ("not", True),
            ("in:evidence_key", expected_keys),
        )
    ]
