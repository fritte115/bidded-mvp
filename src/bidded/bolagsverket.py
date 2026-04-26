from __future__ import annotations

import re
from typing import Any

import httpx


class BolagsverketError(RuntimeError):
    """Raised when Bolagsverket lookup fails or credentials are required."""


BOLAGSVERKET_API_BASE = "https://api.bolagsverket.se"

_ORG_NUMBER_RE = re.compile(r"^\d{10}$|^\d{12}$")


def _normalize_org_number(org_number: str) -> str:
    """Strip hyphens and spaces, return digits only."""
    return re.sub(r"[\s\-]", "", org_number.strip())


def fetch_company_data(
    org_number: str,
    *,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """
    Attempt to fetch basic company data from Bolagsverket public API.

    Returns a dict with available fields on success. Raises BolagsverketError
    when the API requires credentials or the organisation is not found.

    NOTE: The Bolagsverket API requires authentication (BankID or API key via
    the Bolagsverket portal). This call will raise BolagsverketError with
    "requires_credentials" when unauthenticated, allowing the caller to
    gracefully surface what fields *could* be filled with proper credentials.
    """
    normalized = _normalize_org_number(org_number)
    if not _ORG_NUMBER_RE.match(normalized):
        raise BolagsverketError(
            f"Invalid organisation number format: {org_number!r}. "
            "Expected 10 or 12 digits (hyphens/spaces stripped)."
        )

    url = f"{BOLAGSVERKET_API_BASE}/foretagsinformation/v1/organisationer/{normalized}"
    try:
        response = httpx.get(url, timeout=timeout)
    except httpx.RequestError as exc:
        raise BolagsverketError(f"Request failed: {exc}") from exc

    if response.status_code in (401, 403):
        raise BolagsverketError("requires_credentials")

    if response.status_code == 404:
        raise BolagsverketError(
            f"Organisation {normalized} not found in Bolagsverket."
        )

    if not response.is_success:
        raise BolagsverketError(
            f"Bolagsverket API error: {response.status_code}"
        )

    data = response.json()
    return {
        "organization_number": normalized,
        "name": data.get("foretagsnamn") or data.get("namn"),
        "registration_date": data.get("registreringsdatum"),
        "company_form": data.get("foretagsform"),
        "address": data.get("besoksadress") or data.get("adress"),
        "raw": data,
    }


__all__ = ["BolagsverketError", "fetch_company_data"]
