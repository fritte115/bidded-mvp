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
                    f"The company profile lists {label.lower()} as "
                    f"{', '.join(values)}."
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


def _format_plain_number(value: int | float) -> str:
    return f"{value:.0f}"
