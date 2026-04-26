from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID


class SupabaseEvidenceTable(Protocol):
    def upsert(
        self,
        payload: list[dict[str, Any]],
        *,
        on_conflict: str | None = None,
    ) -> Any: ...


class SupabaseTableClient(Protocol):
    def table(self, table_name: str) -> SupabaseEvidenceTable: ...


@dataclass(frozen=True)
class CompanyProfileEvidenceUpsertResult:
    evidence_count: int
    evidence_keys: tuple[str, ...]
    rows_returned: int


def build_company_profile_evidence_items(
    *,
    company_id: UUID,
    company_profile: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Convert seeded company profile facts into evidence_items payloads."""
    tenant_key = str(company_profile.get("tenant_key", "demo"))
    profile_label = str(company_profile.get("profile_label", "company_profile"))
    source_label = _source_label(company_profile)

    evidence_items: list[dict[str, Any]] = []

    for index, certification in enumerate(company_profile.get("certifications", [])):
        if not isinstance(certification, Mapping):
            continue

        name = str(certification.get("name", "")).strip()
        scope = str(certification.get("scope", "")).strip()
        status = str(certification.get("status", "")).strip()
        if not name or not scope:
            continue

        field_path = f"certifications[{index}]"
        item_source_label = str(certification.get("source_label") or source_label)
        evidence_items.append(
            _company_evidence_payload(
                tenant_key=tenant_key,
                company_id=company_id,
                profile_label=profile_label,
                fact_key=f"cert-{name}",
                field_path=field_path,
                category="certification",
                excerpt=f"{name}: {scope}; status {status}.",
                normalized_meaning=(
                    f"The company has {status} {name} certification for {scope}."
                ),
                source_label=item_source_label,
                confidence=0.95,
                metadata={"certification_name": name, "status": status},
            )
        )

    evidence_items.extend(
        _build_reference_evidence(
            tenant_key=tenant_key,
            company_id=company_id,
            profile_label=profile_label,
            source_label=source_label,
            company_profile=company_profile,
        )
    )
    evidence_items.extend(
        _build_capacity_evidence(
            tenant_key=tenant_key,
            company_id=company_id,
            profile_label=profile_label,
            source_label=source_label,
            company_profile=company_profile,
        )
    )
    evidence_items.extend(
        _build_geography_evidence(
            tenant_key=tenant_key,
            company_id=company_id,
            profile_label=profile_label,
            source_label=source_label,
            company_profile=company_profile,
        )
    )
    evidence_items.extend(
        _build_cv_summary_evidence(
            tenant_key=tenant_key,
            company_id=company_id,
            profile_label=profile_label,
            source_label=source_label,
            company_profile=company_profile,
        )
    )
    evidence_items.extend(
        _build_revenue_evidence(
            tenant_key=tenant_key,
            company_id=company_id,
            profile_label=profile_label,
            source_label=source_label,
            company_profile=company_profile,
        )
    )
    evidence_items.extend(
        _build_economics_evidence(
            tenant_key=tenant_key,
            company_id=company_id,
            profile_label=profile_label,
            source_label=source_label,
            company_profile=company_profile,
        )
    )
    evidence_items.extend(
        _build_public_financial_snapshot_evidence(
            tenant_key=tenant_key,
            company_id=company_id,
            profile_label=profile_label,
            source_label=source_label,
            company_profile=company_profile,
        )
    )
    evidence_items.extend(
        _build_public_financial_statement_history_evidence(
            tenant_key=tenant_key,
            company_id=company_id,
            profile_label=profile_label,
            source_label=source_label,
            company_profile=company_profile,
        )
    )
    evidence_items.extend(
        _build_website_import_evidence(
            tenant_key=tenant_key,
            company_id=company_id,
            profile_label=profile_label,
            company_profile=company_profile,
        )
    )

    return evidence_items


def upsert_company_profile_evidence(
    client: SupabaseTableClient,
    *,
    company_id: UUID,
    company_profile: Mapping[str, Any],
) -> CompanyProfileEvidenceUpsertResult:
    evidence_items = build_company_profile_evidence_items(
        company_id=company_id,
        company_profile=company_profile,
    )
    if not evidence_items:
        return CompanyProfileEvidenceUpsertResult(
            evidence_count=0,
            evidence_keys=(),
            rows_returned=0,
        )

    response = (
        client.table("evidence_items")
        .upsert(evidence_items, on_conflict="tenant_key,evidence_key")
        .execute()
    )
    data = getattr(response, "data", [])
    rows_returned = len(data) if isinstance(data, list) else 0

    return CompanyProfileEvidenceUpsertResult(
        evidence_count=len(evidence_items),
        evidence_keys=tuple(item["evidence_key"] for item in evidence_items),
        rows_returned=rows_returned,
    )


def _build_reference_evidence(
    *,
    tenant_key: str,
    company_id: UUID,
    profile_label: str,
    source_label: str,
    company_profile: Mapping[str, Any],
) -> list[dict[str, Any]]:
    evidence_items: list[dict[str, Any]] = []
    for index, reference in enumerate(
        _mapping_sequence(company_profile.get("reference_projects", []))
    ):
        reference_id = str(reference.get("reference_id") or f"reference-{index + 1}")
        sector = str(reference.get("sector", "")).strip()
        customer_type = str(reference.get("customer_type", "")).strip()
        years = str(reference.get("delivery_years", "")).strip()
        value_band = str(reference.get("contract_value_band_sek", "")).strip()
        summary = str(reference.get("case_study_summary", "")).strip()
        capabilities = _string_sequence(reference.get("capabilities_used", []))
        if not summary:
            continue

        field_path = f"reference_projects[{index}]"
        evidence_items.append(
            _company_evidence_payload(
                tenant_key=tenant_key,
                company_id=company_id,
                profile_label=profile_label,
                fact_key=f"reference-{reference_id}",
                field_path=field_path,
                category="reference",
                excerpt=(
                    f"{customer_type} reference ({sector}, {years}, {value_band}): "
                    f"{summary} Capabilities used: {', '.join(capabilities)}."
                ),
                normalized_meaning=(
                    f"The company has a {sector} case-study reference for "
                    f"{customer_type} delivery during {years}."
                ),
                source_label=str(reference.get("source_label") or source_label),
                confidence=0.9,
                metadata={
                    "reference_id": reference_id,
                    "sector": sector,
                    "customer_type": customer_type,
                    "delivery_years": years,
                    "contract_value_band_sek": value_band,
                    "capabilities_used": capabilities,
                },
            )
        )

    return evidence_items


def _build_capacity_evidence(
    *,
    tenant_key: str,
    company_id: UUID,
    profile_label: str,
    source_label: str,
    company_profile: Mapping[str, Any],
) -> list[dict[str, Any]]:
    capacity = _nested_mapping(company_profile, "capabilities", "delivery_capacity")
    evidence_items: list[dict[str, Any]] = []

    numeric_capacity_specs = [
        (
            "available_consultants_90_days",
            "consultants",
            "consultants available within 90 days",
        ),
        (
            "available_consultants_180_days",
            "consultants",
            "consultants available within 180 days",
        ),
        (
            "security_cleared_consultants",
            "consultants",
            "security-cleared consultants",
        ),
        (
            "active_public_sector_delivery_teams",
            "teams",
            "active public-sector delivery teams",
        ),
    ]
    for key, unit, label in numeric_capacity_specs:
        value = capacity.get(key)
        if not isinstance(value, int | float):
            continue

        field_path = f"capabilities.delivery_capacity.{key}"
        evidence_items.append(
            _company_evidence_payload(
                tenant_key=tenant_key,
                company_id=company_id,
                profile_label=profile_label,
                fact_key=f"capacity-{key}",
                field_path=field_path,
                category="capacity",
                excerpt=f"{_format_number(value)} {label}.",
                normalized_meaning=(
                    f"The company has {_format_number(value)} {label}."
                ),
                source_label=source_label,
                confidence=0.9,
                metadata={"value": value, "unit": unit},
            )
        )

    delivery_centers = _string_sequence(capacity.get("delivery_centers", []))
    if delivery_centers:
        evidence_items.append(
            _company_evidence_payload(
                tenant_key=tenant_key,
                company_id=company_id,
                profile_label=profile_label,
                fact_key="capacity-delivery-centers",
                field_path="capabilities.delivery_capacity.delivery_centers",
                category="capacity",
                excerpt=f"Delivery centers: {', '.join(delivery_centers)}.",
                normalized_meaning=(
                    "The company can deliver from "
                    f"{len(delivery_centers)} listed delivery centers."
                ),
                source_label=source_label,
                confidence=0.85,
                metadata={"delivery_centers": delivery_centers},
            )
        )

    pmo = _nested_mapping(
        company_profile,
        "capabilities",
        "delivery_capacity",
        "project_management_office",
    )
    for key, value in pmo.items():
        if not isinstance(value, int | float):
            continue
        label = key.replace("_", " ")
        field_path = f"capabilities.delivery_capacity.project_management_office.{key}"
        evidence_items.append(
            _company_evidence_payload(
                tenant_key=tenant_key,
                company_id=company_id,
                profile_label=profile_label,
                fact_key=f"capacity-pmo-{key}",
                field_path=field_path,
                category="capacity",
                excerpt=(
                    f"Project management office has {_format_number(value)} {label}."
                ),
                normalized_meaning=(
                    f"The company has {_format_number(value)} {label} in its PMO."
                ),
                source_label=source_label,
                confidence=0.85,
                metadata={"value": value, "unit": label},
            )
        )

    return evidence_items


def _build_geography_evidence(
    *,
    tenant_key: str,
    company_id: UUID,
    profile_label: str,
    source_label: str,
    company_profile: Mapping[str, Any],
) -> list[dict[str, Any]]:
    geography = _nested_mapping(
        company_profile,
        "capabilities",
        "geographic_availability",
    )
    evidence_items: list[dict[str, Any]] = []

    for key, label in [
        ("countries", "Countries"),
        ("swedish_regions", "Swedish regions"),
        ("delivery_model", "Delivery model"),
        ("languages", "Languages"),
    ]:
        values = _string_sequence(geography.get(key, []))
        if not values:
            continue

        field_path = f"capabilities.geographic_availability.{key}"
        evidence_items.append(
            _company_evidence_payload(
                tenant_key=tenant_key,
                company_id=company_id,
                profile_label=profile_label,
                fact_key=f"geography-{key}",
                field_path=field_path,
                category="geography",
                excerpt=f"{label}: {', '.join(values)}.",
                normalized_meaning=(
                    f"The company profile lists {label.lower()} as {', '.join(values)}."
                ),
                source_label=source_label,
                confidence=0.85,
                metadata={key: values},
            )
        )

    return evidence_items


def _build_cv_summary_evidence(
    *,
    tenant_key: str,
    company_id: UUID,
    profile_label: str,
    source_label: str,
    company_profile: Mapping[str, Any],
) -> list[dict[str, Any]]:
    cv_summaries = _mapping_sequence(
        _nested_mapping(company_profile, "profile_details").get("cv_summaries", [])
    )
    evidence_items: list[dict[str, Any]] = []

    for index, cv_summary in enumerate(cv_summaries):
        role = str(cv_summary.get("role", "")).strip()
        seniority = str(cv_summary.get("seniority", "")).strip()
        years = cv_summary.get("average_years_experience")
        available_profiles = cv_summary.get("available_profiles")
        certifications = _string_sequence(cv_summary.get("typical_certifications", []))
        languages = _string_sequence(cv_summary.get("languages", []))
        if not role or not isinstance(available_profiles, int | float):
            continue

        field_path = f"profile_details.cv_summaries[{index}]"
        years_text = (
            f"{_format_number(years)} average years experience"
            if isinstance(years, int | float)
            else "average experience not specified"
        )
        evidence_items.append(
            _company_evidence_payload(
                tenant_key=tenant_key,
                company_id=company_id,
                profile_label=profile_label,
                fact_key=f"cv-{role}",
                field_path=field_path,
                category="cv_summary",
                excerpt=(
                    f"{role} ({seniority}): {_format_number(available_profiles)} "
                    f"available profiles, {years_text}, certifications "
                    f"{', '.join(certifications)}, languages {', '.join(languages)}."
                ),
                normalized_meaning=(
                    f"The company has {_format_number(available_profiles)} "
                    f"{seniority} {role} profiles with {years_text}."
                ),
                source_label=str(cv_summary.get("source_label") or source_label),
                confidence=0.88,
                metadata={
                    "role": role,
                    "seniority": seniority,
                    "average_years_experience": years,
                    "available_profiles": available_profiles,
                    "typical_certifications": certifications,
                    "languages": languages,
                },
            )
        )

    return evidence_items


def _build_revenue_evidence(
    *,
    tenant_key: str,
    company_id: UUID,
    profile_label: str,
    source_label: str,
    company_profile: Mapping[str, Any],
) -> list[dict[str, Any]]:
    evidence_items: list[dict[str, Any]] = []
    annual_revenue = company_profile.get("annual_revenue_sek")
    if isinstance(annual_revenue, int | float):
        revenue_text = _format_money(annual_revenue)
        evidence_items.append(
            _company_evidence_payload(
                tenant_key=tenant_key,
                company_id=company_id,
                profile_label=profile_label,
                fact_key="revenue-annual-revenue-sek",
                field_path="annual_revenue_sek",
                category="revenue",
                excerpt=f"Annual revenue: {revenue_text}.",
                normalized_meaning=(
                    f"The company reports annual revenue of {revenue_text}."
                ),
                source_label=source_label,
                confidence=0.9,
                metadata={"amount_sek": annual_revenue},
            )
        )

    revenue_band = _nested_mapping(
        company_profile,
        "financial_assumptions",
        "revenue_band_sek",
    )
    minimum = revenue_band.get("min")
    maximum = revenue_band.get("max")
    if isinstance(minimum, int | float) and isinstance(maximum, int | float):
        band_text = f"{_format_money(minimum)} to {_format_money(maximum)}"
        evidence_items.append(
            _company_evidence_payload(
                tenant_key=tenant_key,
                company_id=company_id,
                profile_label=profile_label,
                fact_key="revenue-band-sek",
                field_path="financial_assumptions.revenue_band_sek",
                category="revenue",
                excerpt=f"Revenue band: {band_text}.",
                normalized_meaning=(
                    f"The company assumes a revenue band from {band_text}."
                ),
                source_label=source_label,
                confidence=0.85,
                metadata={"min_sek": minimum, "max_sek": maximum},
            )
        )

    return evidence_items


def _build_economics_evidence(
    *,
    tenant_key: str,
    company_id: UUID,
    profile_label: str,
    source_label: str,
    company_profile: Mapping[str, Any],
) -> list[dict[str, Any]]:
    economics = _nested_mapping(company_profile, "financial_assumptions")
    evidence_items: list[dict[str, Any]] = []

    rate_card = _nested_mapping(
        company_profile,
        "financial_assumptions",
        "rate_card_sek_per_hour",
    )
    if rate_card:
        rate_parts = [
            f"{role}: {_format_plain_number(rate)} SEK/hour"
            for role, rate in rate_card.items()
            if isinstance(rate, int | float)
        ]
        evidence_items.append(
            _company_evidence_payload(
                tenant_key=tenant_key,
                company_id=company_id,
                profile_label=profile_label,
                fact_key="economics-rate-card-sek-per-hour",
                field_path="financial_assumptions.rate_card_sek_per_hour",
                category="economics",
                excerpt=f"Rate card: {'; '.join(rate_parts)}.",
                normalized_meaning=(
                    "The company has seeded hourly SEK rates for "
                    f"{len(rate_parts)} consultant categories."
                ),
                source_label=source_label,
                confidence=0.85,
                metadata=dict(rate_card),
            )
        )

    for key, phrase in [
        ("target_gross_margin_percent", "target gross margin"),
        ("minimum_acceptable_margin_percent", "minimum acceptable margin"),
    ]:
        value = economics.get(key)
        if not isinstance(value, int | float):
            continue
        evidence_items.append(
            _company_evidence_payload(
                tenant_key=tenant_key,
                company_id=company_id,
                profile_label=profile_label,
                fact_key=f"economics-{key}",
                field_path=f"financial_assumptions.{key}",
                category="economics",
                excerpt=f"{phrase.title()}: {_format_number(value)}%.",
                normalized_meaning=f"The company {phrase} is {_format_number(value)}%.",
                source_label=source_label,
                confidence=0.85,
                metadata={"percent": value},
            )
        )

    travel_assumption = str(economics.get("travel_assumption", "")).strip()
    if travel_assumption:
        evidence_items.append(
            _company_evidence_payload(
                tenant_key=tenant_key,
                company_id=company_id,
                profile_label=profile_label,
                fact_key="economics-travel-assumption",
                field_path="financial_assumptions.travel_assumption",
                category="economics",
                excerpt=f"Travel assumption: {travel_assumption}.",
                normalized_meaning=(
                    f"The company's travel pricing assumption is: {travel_assumption}."
                ),
                source_label=source_label,
                confidence=0.8,
                metadata={"travel_assumption": travel_assumption},
            )
        )

    pricing_notes = _string_sequence(economics.get("pricing_notes", []))
    if pricing_notes:
        evidence_items.append(
            _company_evidence_payload(
                tenant_key=tenant_key,
                company_id=company_id,
                profile_label=profile_label,
                fact_key="economics-pricing-notes",
                field_path="financial_assumptions.pricing_notes",
                category="economics",
                excerpt=f"Pricing notes: {'; '.join(pricing_notes)}.",
                normalized_meaning=(
                    "The company profile lists commercial assumptions for "
                    "fixed-price discovery, multi-year rate cards, and specialist "
                    "allocation caps."
                ),
                source_label=source_label,
                confidence=0.8,
                metadata={"pricing_notes": pricing_notes},
            )
        )

    return evidence_items


def _build_public_financial_snapshot_evidence(
    *,
    tenant_key: str,
    company_id: UUID,
    profile_label: str,
    source_label: str,
    company_profile: Mapping[str, Any],
) -> list[dict[str, Any]]:
    snapshot = _nested_mapping(
        company_profile,
        "profile_details",
        "public_financial_snapshot",
    )
    if not snapshot:
        return []

    financial_year = snapshot.get("financial_year")
    revenue_ksek = snapshot.get("revenue_ksek")
    result_ksek = snapshot.get("result_after_financial_items_ksek")
    ebitda_ksek = snapshot.get("ebitda_ksek")
    assets_ksek = snapshot.get("total_assets_ksek")
    equity_ksek = snapshot.get("equity_ksek")
    equity_ratio = snapshot.get("equity_ratio_percent")
    cash_liquidity = snapshot.get("cash_liquidity_percent")
    if not isinstance(financial_year, int | float) or not isinstance(
        revenue_ksek,
        int | float,
    ):
        return []

    source = str(snapshot.get("source_label") or source_label)
    excerpt_parts = [
        f"{_format_number(revenue_ksek)} KSEK revenue",
    ]
    if isinstance(result_ksek, int | float):
        excerpt_parts.append(
            f"{_format_number(result_ksek)} KSEK result after financial items"
        )
    if isinstance(ebitda_ksek, int | float):
        excerpt_parts.append(f"{_format_number(ebitda_ksek)} KSEK EBITDA")
    if isinstance(assets_ksek, int | float):
        excerpt_parts.append(f"{_format_number(assets_ksek)} KSEK total assets")
    if isinstance(equity_ksek, int | float):
        excerpt_parts.append(f"{_format_number(equity_ksek)} KSEK equity")
    if isinstance(equity_ratio, int | float):
        excerpt_parts.append(f"{_format_percent(equity_ratio)} equity ratio")
    if isinstance(cash_liquidity, int | float):
        excerpt_parts.append(f"{_format_percent(cash_liquidity)} cash liquidity")

    return [
        _company_evidence_payload(
            tenant_key=tenant_key,
            company_id=company_id,
            profile_label=profile_label,
            fact_key=f"financial-snapshot-{int(financial_year)}",
            field_path="profile_details.public_financial_snapshot",
            category="financial_standing",
            excerpt=(
                f"{int(financial_year)} public financial snapshot: "
                f"{'; '.join(excerpt_parts)}."
            ),
            normalized_meaning=(
                f"The company profile includes a public annual-account snapshot "
                f"for {int(financial_year)} with {_format_number(revenue_ksek)} "
                "KSEK revenue."
            ),
            source_label=source,
            confidence=0.9,
            metadata=dict(snapshot),
        )
    ]


def _build_public_financial_statement_history_evidence(
    *,
    tenant_key: str,
    company_id: UUID,
    profile_label: str,
    source_label: str,
    company_profile: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows = sorted(
        _mapping_sequence(
            _nested_mapping(company_profile, "profile_details").get(
                "public_financial_statement_history",
                [],
            )
        ),
        key=lambda row: int(row.get("year", 0)),
    )
    if not rows:
        return []

    usable_rows = [
        row
        for row in rows
        if isinstance(row.get("year"), int | float)
        and isinstance(row.get("total_revenue_ksek"), int | float)
    ]
    if not usable_rows:
        return []

    first = usable_rows[0]
    latest = usable_rows[-1]
    first_year = int(first["year"])
    latest_year = int(latest["year"])
    first_revenue = first["total_revenue_ksek"]
    latest_revenue = latest["total_revenue_ksek"]
    latest_result = latest.get("result_after_financial_net_ksek")
    source = str(latest.get("source_label") or source_label)

    row_summaries: list[str] = []
    for row in usable_rows:
        year = int(row["year"])
        revenue = row["total_revenue_ksek"]
        result = row.get("result_after_financial_net_ksek")
        operating_result = row.get("operating_result_after_depreciation_ksek")
        summary_parts = [f"{year}: revenue {_format_number(revenue)} KSEK"]
        if isinstance(operating_result, int | float):
            summary_parts.append(
                f"operating result {_format_number(operating_result)} KSEK"
            )
        if isinstance(result, int | float):
            summary_parts.append(
                f"result after financial net {_format_number(result)} KSEK"
            )
        row_summaries.append(", ".join(summary_parts))

    normalized_tail = (
        f" and result after financial net {_format_number(latest_result)} KSEK"
        if isinstance(latest_result, int | float)
        else ""
    )

    return [
        _company_evidence_payload(
            tenant_key=tenant_key,
            company_id=company_id,
            profile_label=profile_label,
            fact_key=f"financial-history-{first_year}-{latest_year}",
            field_path="profile_details.public_financial_statement_history",
            category="financial_standing",
            excerpt=(
                f"{first_year}-{latest_year} public financial statement history: "
                f"{'; '.join(row_summaries)}."
            ),
            normalized_meaning=(
                "The company profile public financial history shows revenue grew "
                f"from {_format_number(first_revenue)} KSEK in {first_year} to "
                f"{_format_number(latest_revenue)} KSEK in {latest_year}"
                f"{normalized_tail}."
            ),
            source_label=source,
            confidence=0.9,
            metadata={
                "first_year": first_year,
                "latest_year": latest_year,
                "first_total_revenue_ksek": first_revenue,
                "latest_total_revenue_ksek": latest_revenue,
                "latest_result_after_financial_net_ksek": latest_result,
                "rows": [dict(row) for row in usable_rows],
            },
        )
    ]


def _build_website_import_evidence(
    *,
    tenant_key: str,
    company_id: UUID,
    profile_label: str,
    company_profile: Mapping[str, Any],
) -> list[dict[str, Any]]:
    imports = _mapping_sequence(
        _nested_mapping(company_profile, "profile_details").get("website_imports", [])
    )
    evidence_items: list[dict[str, Any]] = []

    for index, website_import in enumerate(imports):
        source_url = str(website_import.get("source_url", "")).strip()
        if not source_url:
            continue
        source_label = f"website:{source_url}"
        imported_at = str(website_import.get("imported_at", "")).strip()
        profile_patch = _nested_mapping(website_import, "profile_patch")

        description = str(profile_patch.get("description", "")).strip()
        if description:
            evidence_items.append(
                _website_import_payload(
                    tenant_key=tenant_key,
                    company_id=company_id,
                    profile_label=profile_label,
                    import_index=index,
                    source_url=source_url,
                    imported_at=imported_at,
                    field_name="description",
                    category="profile_summary",
                    field_path=(
                        f"profile_details.website_imports[{index}]."
                        "profile_patch.description"
                    ),
                    excerpt=description,
                    normalized_meaning=(
                        "The imported website profile describes the company as: "
                        f"{description}"
                    ),
                    source_label=source_label,
                    website_import=website_import,
                    confidence=0.78,
                )
            )

        capabilities = _string_sequence(profile_patch.get("capabilities", []))
        if capabilities:
            values_text = ", ".join(capabilities)
            evidence_items.append(
                _website_import_payload(
                    tenant_key=tenant_key,
                    company_id=company_id,
                    profile_label=profile_label,
                    import_index=index,
                    source_url=source_url,
                    imported_at=imported_at,
                    field_name="capabilities",
                    category="capability",
                    field_path=(
                        f"profile_details.website_imports[{index}]."
                        "profile_patch.capabilities"
                    ),
                    excerpt=f"Website-imported capabilities: {values_text}.",
                    normalized_meaning=(
                        "The imported website profile lists company capabilities: "
                        f"{values_text}."
                    ),
                    source_label=source_label,
                    website_import=website_import,
                    confidence=0.78,
                    metadata={"values": capabilities},
                )
            )

        for cert_index, certification in enumerate(
            _mapping_sequence(profile_patch.get("certifications", []))
        ):
            name = str(certification.get("name", "")).strip()
            if not name:
                continue
            issuer = str(certification.get("issuer", "")).strip()
            status = str(certification.get("validUntil", "")).strip()
            evidence_items.append(
                _website_import_payload(
                    tenant_key=tenant_key,
                    company_id=company_id,
                    profile_label=profile_label,
                    import_index=index,
                    source_url=source_url,
                    imported_at=imported_at,
                    field_name="certifications",
                    category="certification",
                    field_path=(
                        f"profile_details.website_imports[{index}]."
                        f"profile_patch.certifications[{cert_index}]"
                    ),
                    excerpt=(
                        f"Website-imported certification: {name}; "
                        f"issuer {issuer}; status {status}."
                    ),
                    normalized_meaning=(
                        f"The imported website profile lists {name} certification."
                    ),
                    source_label=source_label,
                    website_import=website_import,
                    confidence=0.76,
                    metadata={
                        "certification_name": name,
                        "issuer": issuer,
                        "status": status,
                    },
                )
            )

        for reference_index, reference in enumerate(
            _mapping_sequence(profile_patch.get("references", []))
        ):
            client = str(reference.get("client", "")).strip()
            scope = str(reference.get("scope", "")).strip()
            if not client and not scope:
                continue
            evidence_items.append(
                _website_import_payload(
                    tenant_key=tenant_key,
                    company_id=company_id,
                    profile_label=profile_label,
                    import_index=index,
                    source_url=source_url,
                    imported_at=imported_at,
                    field_name="references",
                    category="reference",
                    field_path=(
                        f"profile_details.website_imports[{index}]."
                        f"profile_patch.references[{reference_index}]"
                    ),
                    excerpt=f"Website-imported reference: {client}: {scope}.",
                    normalized_meaning=(
                        f"The imported website profile lists {client} as a reference."
                    ),
                    source_label=source_label,
                    website_import=website_import,
                    confidence=0.74,
                    metadata={"client": client, "scope": scope},
                )
            )

        for security_index, security_item in enumerate(
            _mapping_sequence(profile_patch.get("securityPosture", []))
        ):
            item = str(security_item.get("item", "")).strip()
            status = str(security_item.get("status", "")).strip()
            note = str(security_item.get("note", "")).strip()
            if not item:
                continue
            evidence_items.append(
                _website_import_payload(
                    tenant_key=tenant_key,
                    company_id=company_id,
                    profile_label=profile_label,
                    import_index=index,
                    source_url=source_url,
                    imported_at=imported_at,
                    field_name="securityPosture",
                    category="security",
                    field_path=(
                        f"profile_details.website_imports[{index}]."
                        f"profile_patch.securityPosture[{security_index}]"
                    ),
                    excerpt=(
                        f"Website-imported security posture: {item}; "
                        f"{status}; {note}."
                    ),
                    normalized_meaning=(
                        f"The imported website profile lists {item} as {status}."
                    ),
                    source_label=source_label,
                    website_import=website_import,
                    confidence=0.74,
                    metadata={"item": item, "status": status, "note": note},
                )
            )

    return evidence_items


def _website_import_payload(
    *,
    tenant_key: str,
    company_id: UUID,
    profile_label: str,
    import_index: int,
    source_url: str,
    imported_at: str,
    field_name: str,
    category: str,
    field_path: str,
    excerpt: str,
    normalized_meaning: str,
    source_label: str,
    website_import: Mapping[str, Any],
    confidence: float,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    field_source = _nested_mapping(website_import, "field_sources", field_name)
    source_excerpt = str(field_source.get("excerpt", "")).strip()
    page_url = str(field_source.get("page_url", "")).strip()
    item_source_label = str(field_source.get("source_label") or source_label)
    payload = _company_evidence_payload(
        tenant_key=tenant_key,
        company_id=company_id,
        profile_label=profile_label,
        fact_key=f"website-import-{import_index}-{field_name}-{source_url}",
        field_path=field_path,
        category=category,
        excerpt=(
            f"{excerpt} Source excerpt: {source_excerpt}"
            if source_excerpt
            else excerpt
        ),
        normalized_meaning=normalized_meaning,
        source_label=item_source_label,
        confidence=confidence,
        metadata={
            "source_url": source_url,
            "page_url": page_url,
            "imported_at": imported_at,
            **dict(metadata or {}),
        },
    )
    return payload


def _company_evidence_payload(
    *,
    tenant_key: str,
    company_id: UUID,
    profile_label: str,
    fact_key: str,
    field_path: str,
    category: str,
    excerpt: str,
    normalized_meaning: str,
    source_label: str,
    confidence: float,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "tenant_key": tenant_key,
        "evidence_key": f"COMPANY-{_slug(profile_label)}-{_slug(fact_key)}",
        "source_type": "company_profile",
        "excerpt": excerpt,
        "normalized_meaning": normalized_meaning,
        "category": category,
        "confidence": confidence,
        "source_metadata": {"source_label": source_label},
        "company_id": str(company_id),
        "field_path": field_path,
        "metadata": dict(metadata or {}),
    }


def _source_label(company_profile: Mapping[str, Any]) -> str:
    metadata = company_profile.get("metadata", {})
    if isinstance(metadata, Mapping) and metadata.get("source_label"):
        return str(metadata["source_label"])
    return "seeded company profile"


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").upper()
    return slug or "UNKNOWN"


def _nested_mapping(mapping: Mapping[str, Any], *path: str) -> Mapping[str, Any]:
    current: Any = mapping
    for key in path:
        if not isinstance(current, Mapping):
            return {}
        current = current.get(key, {})
    return current if isinstance(current, Mapping) else {}


def _mapping_sequence(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _string_sequence(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _format_money(value: int | float) -> str:
    return f"{value:,.0f} SEK"


def _format_number(value: int | float) -> str:
    return f"{value:,.0f}"


def _format_percent(value: int | float) -> str:
    formatted = f"{value:,.1f}" if not float(value).is_integer() else f"{value:,.0f}"
    return f"{formatted}%"


def _format_plain_number(value: int | float) -> str:
    return f"{value:.0f}"
