from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

import httpx


class TedFetchError(RuntimeError):
    """Raised when the TED API fetch fails."""


TED_SEARCH_URL = "https://api.ted.europa.eu/v3/notices/search"
TED_NOTICE_XML_URL = "https://ted.europa.eu/en/notice/{pub_number}/xml"
_DEFAULT_PAGE_SIZE = 25

# All fields we request from the TED v3 search API.
# These are the field names supported by the TED ODS search endpoint.
_TED_FIELDS = [
    "notice-identifier",
    "notice-title",
    "notice-type",
    "buyer-name",
    "buyer-country",
    "buyer-country-sub",
    "publication-date",
    "deadline",
    "procedure-type",
    "contract-nature-main-proc",
    "classification-cpv",
    "estimated-value-proc",
    "estimated-value-cur-proc",
    "submission-language",
    "place-of-performance",
]


def fetch_swedish_notices(
    *,
    page: int = 1,
    limit: int = _DEFAULT_PAGE_SIZE,
    timeout: float = 20.0,
) -> list[dict[str, Any]]:
    """Fetch active Swedish contract notices from EU TED open API (v3).

    Filters to CN-standard (Contract Notice) form types only so we don't
    return award notices or prior information notices that are not open for bids.
    """
    payload = {
        # buyer-country = SWE gives Swedish notices; form-type = CN limits to
        # Contract Notices that are still open for bidding (not award notices).
        "query": "buyer-country = SWE AND notice-type = cn-standard",
        "fields": _TED_FIELDS,
        "page": page,
        "limit": limit,
        "scope": "ACTIVE",
    }
    try:
        response = httpx.post(TED_SEARCH_URL, json=payload, timeout=timeout)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise TedFetchError(
            f"TED API HTTP error: {exc.response.status_code} "
            f"— {exc.response.text[:200]}"
        ) from exc
    except httpx.RequestError as exc:
        raise TedFetchError(f"TED API request failed: {exc}") from exc

    data = response.json()
    notices = data.get("notices", [])
    if not isinstance(notices, list):
        raise TedFetchError("Unexpected TED API response shape")
    return notices


def fetch_notice_xml(pub_number: str, *, timeout: float = 20.0) -> str | None:
    """Download the full eForms XML for a single TED notice.

    Returns the raw XML string, or None if the notice is not found or the
    request fails. Callers should degrade gracefully on None.
    """
    url = TED_NOTICE_XML_URL.format(pub_number=pub_number)
    try:
        response = httpx.get(url, timeout=timeout, follow_redirects=True)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.text
    except (httpx.HTTPStatusError, httpx.RequestError):
        return None


# ---------------------------------------------------------------------------
# XML parsing helpers
# ---------------------------------------------------------------------------

# Common UBL/eForms namespace prefixes used in TED XML
_NS: dict[str, str] = {
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "ext": "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2",
    "efext": "http://data.europa.eu/p27/eforms-ubl-extensions/1",
    "efac": "http://data.europa.eu/p27/eforms-ubl-extension-aggregate-components/1",
    "efbc": "http://data.europa.eu/p27/eforms-ubl-extension-basic-components/1",
}


def _text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return (element.text or "").strip()


def _find_text(root: ET.Element, xpath: str) -> str:
    return _text(root.find(xpath, _NS))


def _find_all_text(root: ET.Element, xpath: str) -> list[str]:
    return [t for el in root.findall(xpath, _NS) if (t := _text(el))]


def _find_first_lang(
    root: ET.Element, xpath: str, preferred: tuple[str, ...] = ("SWE", "ENG")
) -> str:
    """Find a multilingual element preferring Swedish then English then any."""
    elements = root.findall(xpath, _NS)
    by_lang: dict[str, str] = {}
    for el in elements:
        lang = el.get("languageID", "").upper()
        text = _text(el)
        if text:
            by_lang[lang] = text
    for lang in preferred:
        if lang in by_lang:
            return by_lang[lang]
    return next(iter(by_lang.values()), "")


def parse_notice_xml(xml_text: str) -> dict[str, Any]:
    """Parse a TED eForms XML notice into a flat dict of useful fields.

    Returns a dict with keys that align with ExternalTender fields. Fields
    not found in the XML are omitted (caller should merge with search data).
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return {}

    result: dict[str, Any] = {}

    # --- Description: prefer lot-level, fall back to project-level ---
    lot_descriptions: list[str] = []
    for proc_project in root.findall(".//cac:ProcurementProject", _NS):
        desc = _find_first_lang(proc_project, "cbc:Description")
        if desc:
            lot_descriptions.append(desc)
    if lot_descriptions:
        result["summary"] = "\n\n".join(lot_descriptions[:3])  # up to 3 lots

    # --- Requirements: selection criteria ---
    requirements: list[str] = []
    xpath_qual = ".//cac:TenderingTerms/cac:TendererQualificationRequest"
    for criterion in root.findall(xpath_qual, _NS):
        desc = _find_first_lang(criterion, ".//cbc:Description")
        if desc:
            requirements.append(desc)
    # Also grab any financial/technical standing descriptions
    xpath_guarantee = (
        ".//cac:TenderingTerms/cac:RequiredFinancialGuarantee/cac:Description"
    )
    for criterion in root.findall(xpath_guarantee, _NS):
        t = _text(criterion)
        if t:
            requirements.append(t)
    if requirements:
        result["requirements"] = requirements[:8]  # cap at 8

    # --- Award criteria ---
    award_criteria: list[dict[str, Any]] = []
    for criterion in root.findall(".//cac:AwardingTerms/cac:AwardingCriterion", _NS):
        name = _find_first_lang(criterion, "cbc:Description") or _find_text(
            criterion, "cbc:AwardingCriterionTypeCode"
        )
        weight_el = criterion.find("cbc:WeightNumeric", _NS)
        weight = 0
        if weight_el is not None and weight_el.text:
            try:
                v = float(weight_el.text)
                weight = int(v * 100) if v <= 1 else int(v)
            except (ValueError, TypeError):
                pass
        if name:
            award_criteria.append({"name": name, "weight": weight})
    if award_criteria:
        result["evaluationCriteria"] = award_criteria

    # --- Contract duration ---
    duration_el = root.find(
        ".//cac:ProcurementProject/cac:PlannedPeriod/cbc:DurationMeasure", _NS
    )
    if duration_el is not None and duration_el.text:
        try:
            unit = duration_el.get("unitCode", "MON").upper()
            val = float(duration_el.text)
            months = int(val) if unit in ("MON", "MONTH") else int(val * 12)
            result["contractDurationMonths"] = months
        except (ValueError, TypeError):
            pass

    # --- Contact info ---
    contact = root.find(".//cac:ContractingParty/cac:Party/cac:Contact", _NS)
    if contact is not None:
        name = _find_text(contact, "cbc:Name")
        email = _find_text(contact, "cbc:ElectronicMail")
        if name:
            result["contactName"] = name
        if email:
            result["contactEmail"] = email

    # --- Submission languages ---
    langs = _find_all_text(root, ".//cac:TenderingTerms/cac:Language/cbc:ID")
    if langs:
        _lang_map = {
            "SWE": "Swedish", "ENG": "English", "FIN": "Finnish",
            "NOR": "Norwegian", "DEU": "German", "FRA": "French",
        }
        result["submissionLanguage"] = _lang_map.get(langs[0].upper(), langs[0])
        result["languages"] = [_lang_map.get(lang.upper(), lang) for lang in langs]

    # --- Lots ---
    lot_count = len(root.findall(".//cac:ProcurementProjectLot", _NS))
    if lot_count > 0:
        result["lots"] = lot_count

    # --- Framework agreement ---
    framework_el = root.find(".//cac:TenderingProcess/cac:FrameworkAgreement", _NS)
    result["framework"] = framework_el is not None

    # --- Certifications / selection criteria text ---
    certs: list[str] = []
    xpath_cert = (
        ".//cac:TenderingTerms"
        "/cac:TendererQualificationRequest"
        "/cac:SpecificTendererRequirement"
    )
    for sc in root.findall(xpath_cert, _NS):
        desc = _find_first_lang(sc, "cbc:Description")
        if desc and len(desc) < 200:
            certs.append(desc)
    if certs:
        result["certifications"] = certs[:6]

    return result


def _first_str(value: Any) -> str | None:
    """Extract first string from a TED field (may be list, dict, or str)."""
    if isinstance(value, list) and value:
        return _first_str(value[0])
    if isinstance(value, dict):
        for lang_order in ("swe", "eng", "fin"):
            if lang_order in value:
                return _first_str(value[lang_order])
        if value:
            return _first_str(next(iter(value.values())))
    if isinstance(value, str):
        return value
    return None


def _all_strings(value: Any) -> list[str]:
    """Extract all string values from a TED field."""
    if isinstance(value, list):
        result = []
        for item in value:
            s = _first_str(item)
            if s:
                result.append(s)
        return result
    s = _first_str(value)
    return [s] if s else []


def _map_procedure(value: str | None) -> str:
    mapping = {
        "open": "Open",
        "restricted": "Restricted",
        "negotiated": "Negotiated",
        "competitive-dialogue": "Competitive Dialogue",
        "competitive_dialogue": "Competitive Dialogue",
    }
    return mapping.get((value or "").lower(), "Open")


def _map_contract(value: str | None) -> str:
    mapping = {
        "works": "Works",
        "supplies": "Supplies",
        "services": "Services",
    }
    return mapping.get((value or "").lower(), "Services")


def _parse_ted_date(s: str | None) -> str | None:
    """Normalise TED date strings to YYYY-MM-DD."""
    if not s:
        return None
    cleaned = s.strip()
    if "T" in cleaned:
        cleaned = cleaned.split("T")[0]
    cleaned = cleaned.rstrip("Z")
    if len(cleaned) > 10 and (cleaned[10:11] in ("+", "-")):
        cleaned = cleaned[:10]
    if len(cleaned) == 8 and cleaned.isdigit():
        return f"{cleaned[:4]}-{cleaned[4:6]}-{cleaned[6:8]}"
    return cleaned if cleaned else None


def _extract_search_field_text(value: Any) -> str:
    """Extract plain text from TED search result field values."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list) and value:
        return _extract_search_field_text(value[0])
    if isinstance(value, dict):
        # Could be {"value": "...", "languageID": "SWE"} or similar
        for key in ("value", "text", "description"):
            if key in value:
                return _extract_search_field_text(value[key])
        # Multilingual: pick Swedish then English then any
        for lang in ("SWE", "swe", "ENG", "eng"):
            if lang in value:
                return _extract_search_field_text(value[lang])
        if value:
            return _extract_search_field_text(next(iter(value.values())))
    return ""


def _extract_all_from_field(value: Any) -> list[str]:
    """Extract all text values from a TED search result field."""
    if isinstance(value, list):
        results = []
        for item in value:
            t = _extract_search_field_text(item)
            if t:
                results.append(t)
        return results
    t = _extract_search_field_text(value)
    return [t] if t else []


def map_notice_to_explore_shape(notice: dict[str, Any]) -> dict[str, Any]:
    """Map a TED v3 notice dict to a frontend ExternalTender-shaped dict."""
    pub_number = notice.get("publication-number", "")
    notice_id = _first_str(notice.get("notice-identifier")) or pub_number

    # Title
    title_dict = notice.get("notice-title") or {}
    if isinstance(title_dict, dict):
        title_raw = (
            _first_str(title_dict.get("swe"))
            or _first_str(title_dict.get("eng"))
            or _first_str(next(iter(title_dict.values()), None))
            or f"Notice {pub_number}"
        )
    else:
        title_raw = _first_str(title_dict) or f"Notice {pub_number}"

    buyer = _first_str(notice.get("buyer-name")) or "Unknown Authority"
    country_list = _all_strings(notice.get("buyer-country"))
    raw_country = country_list[0] if country_list else "SWE"
    _ALPHA3_TO_2 = {
        "SWE": "SE", "NOR": "NO", "DNK": "DK", "FIN": "FI",
        "DEU": "DE", "FRA": "FR", "GBR": "GB",
    }
    country = _ALPHA3_TO_2.get(
        raw_country, raw_country[:2] if len(raw_country) >= 2 else "SE"
    )

    nuts_list = _all_strings(notice.get("buyer-country-sub"))
    nuts = nuts_list[0] if nuts_list else ""

    cpv_raw = notice.get("classification-cpv", [])
    cpv_codes = list(dict.fromkeys(_all_strings(cpv_raw)))

    procedure = _map_procedure(_first_str(notice.get("procedure-type")))
    contract = _map_contract(_first_str(notice.get("contract-nature-main-proc")))

    tv_raw = _first_str(notice.get("estimated-value-proc"))
    try:
        tv_msek = round(float(tv_raw) / 1_000_000, 2) if tv_raw else 0.0
    except (ValueError, TypeError):
        tv_msek = 0.0

    currency_raw = _first_str(notice.get("estimated-value-cur-proc")) or "SEK"
    currency = currency_raw if currency_raw in ("SEK", "EUR") else "EUR"

    pub_date = _parse_ted_date(_first_str(notice.get("publication-date"))) or ""
    deadline_raw = notice.get("deadline")
    deadline = _parse_ted_date(_first_str(deadline_raw)) or ""

    source_url = (
        f"https://ted.europa.eu/en/notice/{pub_number}/html" if pub_number else ""
    )

    # Submission language (valid TED v3 field)
    lang_raw = notice.get("submission-language")
    submission_language = None
    languages: list[str] = []
    if lang_raw:
        _lang_map = {
            "SWE": "Swedish", "ENG": "English",
            "FIN": "Finnish", "NOR": "Norwegian",
        }
        raw_langs = _extract_all_from_field(lang_raw)
        languages = [_lang_map.get(lang.upper(), lang) for lang in raw_langs]
        submission_language = languages[0] if languages else None

    result: dict[str, Any] = {
        "id": notice_id,
        "source": "TED",
        "title": title_raw,
        "buyer": buyer,
        "country": country,
        "nutsCode": nuts,
        "cpvCodes": cpv_codes,
        "procedureType": procedure,
        "contractType": contract,
        "estimatedValueMSEK": tv_msek,
        "currency": currency,
        "publishedAt": pub_date,
        "deadline": deadline,
        "summary": "",
        "requirements": [],
        "sourceUrl": source_url,
        "attachments": [],
        "publicationNumber": pub_number,
    }

    if submission_language:
        result["submissionLanguage"] = submission_language
    if languages:
        result["languages"] = languages

    return result


def map_notice_to_tender_row(notice: dict[str, Any]) -> dict[str, Any]:
    """Map a TED notice dict to a tenders table upsert payload (for Supabase)."""
    pub_number = notice.get("publication-number", "")
    title_dict = notice.get("notice-title") or {}
    if isinstance(title_dict, dict):
        title = (
            _first_str(title_dict.get("swe"))
            or _first_str(title_dict.get("eng"))
            or _first_str(next(iter(title_dict.values()), None))
            or f"Untitled notice {pub_number}"
        )
    else:
        title = _first_str(title_dict) or f"Untitled notice {pub_number}"
    authority = _first_str(notice.get("buyer-name")) or "Unknown Authority"

    pub_date = _parse_ted_date(_first_str(notice.get("publication-date")))
    deadline = _parse_ted_date(_first_str(notice.get("deadline")))

    return {
        "tenant_key": "demo",
        "title": title[:255],
        "issuing_authority": authority,
        "procurement_reference": pub_number,
        "procurement_context": {
            "source": "ted_api",
            "country_code": "SE",
            "publication_date": pub_date,
            "submission_deadline": deadline,
        },
        "language_policy": {
            "source_document_language": "sv",
            "agent_output_language": "en",
        },
        "metadata": {
            "registered_via": "ted_api_fetch",
        },
    }


def upsert_notices_to_supabase(
    client: Any,
    notices: list[dict[str, Any]],
) -> list[str]:
    """Upsert TED notices into the tenders table. Returns list of tender IDs."""
    ids: list[str] = []
    for notice in notices:
        row = map_notice_to_tender_row(notice)
        ref = row.get("procurement_reference")
        if not ref:
            continue

        existing_resp = (
            client.table("tenders")
            .select("id")
            .eq("tenant_key", "demo")
            .eq("procurement_reference", ref)
            .limit(1)
            .execute()
        )
        existing_data = list(getattr(existing_resp, "data", None) or [])

        if existing_data:
            row_id = str(existing_data[0]["id"])
            update_payload = {k: v for k, v in row.items() if k != "tenant_key"}
            client.table("tenders").update(update_payload).eq("id", row_id).execute()
            ids.append(row_id)
        else:
            insert_resp = client.table("tenders").insert(row).execute()
            insert_data = list(getattr(insert_resp, "data", None) or [])
            if insert_data and insert_data[0].get("id"):
                ids.append(str(insert_data[0]["id"]))

    return ids


__all__ = [
    "TedFetchError",
    "fetch_notice_xml",
    "fetch_swedish_notices",
    "map_notice_to_explore_shape",
    "map_notice_to_tender_row",
    "parse_notice_xml",
    "upsert_notices_to_supabase",
]
