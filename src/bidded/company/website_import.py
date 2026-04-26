from __future__ import annotations

import ipaddress
import json
import re
import socket
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from bidded.llm.anthropic_client import anthropic_complete_json

MAX_IMPORT_PAGES = 5
MAX_PAGE_BYTES = 750_000
FETCH_TIMEOUT_SECONDS = 5

HostResolver = Callable[[str], Sequence[str]]


class WebsiteImportError(ValueError):
    """Raised when a website import request is unsafe or cannot be fetched."""


@dataclass(frozen=True)
class FetchedWebsitePage:
    url: str
    html: str
    content_type: str = "text/html"


@dataclass(frozen=True)
class WebsiteImportPage:
    url: str
    title: str | None
    text: str


@dataclass(frozen=True)
class WebsiteProfileExtraction:
    profile_patch: Mapping[str, Any]
    field_sources: Mapping[str, Mapping[str, str]]
    warnings: tuple[str, ...] = ()


class WebsitePageFetcher(Protocol):
    def fetch(self, url: str) -> FetchedWebsitePage: ...


class WebsiteProfileExtractor(Protocol):
    def extract(
        self,
        *,
        source_url: str,
        pages: Sequence[WebsiteImportPage],
    ) -> WebsiteProfileExtraction: ...


def import_company_website(
    *,
    url: str,
    max_pages: int = MAX_IMPORT_PAGES,
    fetcher: WebsitePageFetcher | None = None,
    extractor: WebsiteProfileExtractor | None = None,
    host_resolver: HostResolver | None = None,
) -> dict[str, Any]:
    if max_pages < 1 or max_pages > MAX_IMPORT_PAGES:
        raise WebsiteImportError(f"max_pages must be between 1 and {MAX_IMPORT_PAGES}.")

    resolver = host_resolver or _resolve_host_ips
    normalized_url = normalize_website_url(url)
    _validate_public_http_url(normalized_url, host_resolver=resolver)

    page_fetcher = fetcher or UrlLibWebsitePageFetcher(host_resolver=resolver)
    profile_extractor = extractor or RuleBasedWebsiteProfileExtractor()
    warnings: list[str] = []

    home_fetched = page_fetcher.fetch(normalized_url)
    home = _import_page_from_fetched(home_fetched, resolver)
    pages: list[WebsiteImportPage] = [home]

    for candidate_url in _select_key_page_urls(
        base_url=home.url,
        html=home_fetched.html,
        limit=max_pages - 1,
    ):
        try:
            pages.append(_fetch_import_page(page_fetcher, candidate_url, resolver))
        except WebsiteImportError as exc:
            warnings.append(f"Skipped {candidate_url}: {exc}")

    import_pages = tuple(pages)
    extraction = profile_extractor.extract(source_url=home.url, pages=import_pages)
    profile_patch = dict(extraction.profile_patch)
    field_sources = {
        key: dict(value) for key, value in extraction.field_sources.items()
    }
    if extractor is not None:
        fallback_extraction = RuleBasedWebsiteProfileExtractor().extract(
            source_url=home.url,
            pages=import_pages,
        )
        _fill_missing_profile_fields(
            profile_patch,
            field_sources,
            fallback_extraction,
        )
    warnings.extend(extraction.warnings)
    warnings = _filter_resolved_website_import_warnings(warnings, profile_patch)

    return {
        "source_url": home.url,
        "pages": [
            {
                "url": page.url,
                "title": page.title,
                "text_excerpt": page.text[:500],
            }
            for page in pages
        ],
        "profile_patch": profile_patch,
        "field_sources": field_sources,
        "warnings": warnings,
    }


def normalize_website_url(raw_url: str) -> str:
    stripped = raw_url.strip()
    if not stripped:
        raise WebsiteImportError("URL is required.")
    if "://" not in stripped:
        parsed_without_slashes = urlparse(stripped)
        has_unsupported_scheme = (
            parsed_without_slashes.scheme
            and parsed_without_slashes.scheme.lower() not in {"http", "https"}
        )
        if has_unsupported_scheme:
            raise WebsiteImportError("Only http and https URLs can be imported.")
        email_domain = _domain_from_bare_email_address(stripped)
        if email_domain:
            stripped = email_domain
        stripped = f"https://{stripped}"

    url_without_fragment, _fragment = urldefrag(stripped)
    parsed = urlparse(url_without_fragment)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise WebsiteImportError("Only http and https URLs can be imported.")
    if not parsed.hostname:
        raise WebsiteImportError("URL must include a host.")
    if parsed.username and not parsed.password:
        parsed = parsed._replace(netloc=parsed.hostname)
    if parsed.username or parsed.password:
        raise WebsiteImportError("URL credentials are not allowed.")

    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    return urlunparse(
        parsed._replace(scheme=parsed.scheme.lower(), netloc=netloc, path=path)
    )


def _domain_from_bare_email_address(value: str) -> str | None:
    if any(separator in value for separator in ("/", "?", "#")):
        return None
    if value.count("@") != 1:
        return None
    local_part, domain = value.rsplit("@", 1)
    if not local_part or not domain or "." not in domain:
        return None
    return domain


class UrlLibWebsitePageFetcher:
    def __init__(
        self,
        *,
        host_resolver: HostResolver | None = None,
        max_bytes: int = MAX_PAGE_BYTES,
        timeout_seconds: int = FETCH_TIMEOUT_SECONDS,
    ) -> None:
        self._host_resolver = host_resolver or _resolve_host_ips
        self._max_bytes = max_bytes
        self._timeout_seconds = timeout_seconds
        self._opener = build_opener(_NoRedirectHandler)

    def fetch(self, url: str) -> FetchedWebsitePage:
        current_url = normalize_website_url(url)
        for _attempt in range(4):
            _validate_public_http_url(
                current_url,
                host_resolver=self._host_resolver,
            )
            request = Request(
                current_url,
                headers={
                    "Accept": "text/html,application/xhtml+xml",
                    "User-Agent": "BiddedWebsiteImporter/0.1",
                },
            )
            try:
                with self._opener.open(
                    request,
                    timeout=self._timeout_seconds,
                ) as response:
                    content_type = response.headers.get("content-type", "text/html")
                    if "html" not in content_type.lower():
                        raise WebsiteImportError(
                            f"Expected HTML content, got {content_type}."
                        )
                    payload = response.read(self._max_bytes + 1)
                    if len(payload) > self._max_bytes:
                        raise WebsiteImportError("HTML page exceeds import size limit.")
                    return FetchedWebsitePage(
                        url=normalize_website_url(response.geturl()),
                        html=_decode_html(payload, content_type),
                        content_type=content_type,
                    )
            except HTTPError as exc:
                if exc.code in {301, 302, 303, 307, 308}:
                    location = exc.headers.get("location")
                    if not location:
                        raise WebsiteImportError(
                            f"Redirect response {exc.code} had no Location header."
                        ) from exc
                    current_url = normalize_website_url(urljoin(current_url, location))
                    continue
                raise WebsiteImportError(f"Website returned HTTP {exc.code}.") from exc
            except URLError as exc:
                raise WebsiteImportError(
                    f"Could not fetch website: {exc.reason}"
                ) from exc
            except TimeoutError as exc:
                raise WebsiteImportError("Website fetch timed out.") from exc

        raise WebsiteImportError("Website redirected too many times.")


class RuleBasedWebsiteProfileExtractor:
    def extract(
        self,
        *,
        source_url: str,
        pages: Sequence[WebsiteImportPage],
    ) -> WebsiteProfileExtraction:
        source_label = f"website:{source_url}"
        combined_text = "\n".join(page.text for page in pages)
        lower_text = combined_text.lower()
        patch: dict[str, Any] = {"website": source_url}
        field_sources: dict[str, dict[str, str]] = {
            "website": {
                "page_url": source_url,
                "excerpt": source_url,
                "source_label": source_label,
            }
        }
        warnings: list[str] = []

        description = _best_description(pages)
        if description:
            patch["description"] = description
            field_sources["description"] = _field_source(
                pages,
                source_label=source_label,
                terms=(description[:80],),
                fallback=description,
            )

        email = _first_match(
            r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
            combined_text,
        )
        if email:
            patch["email"] = email
            field_sources["email"] = _field_source(
                pages,
                source_label=source_label,
                terms=(email,),
            )

        phone = _first_match(r"\+\d{1,3}(?:[\s-]?\d){6,14}", combined_text)
        if phone:
            patch["phone"] = phone.strip(" .,:;")
            field_sources["phone"] = _field_source(
                pages,
                source_label=source_label,
                terms=(phone,),
            )

        capabilities = _extract_capabilities(lower_text)
        if capabilities:
            patch["capabilities"] = capabilities
            field_sources["capabilities"] = _field_source(
                pages,
                source_label=source_label,
                terms=tuple(capabilities),
                fallback=", ".join(capabilities),
            )
        else:
            warnings.append("No clear service capabilities found on imported pages.")

        certifications = _extract_certifications(combined_text)
        if certifications:
            patch["certifications"] = certifications
            field_sources["certifications"] = _field_source(
                pages,
                source_label=source_label,
                terms=tuple(cert["name"] for cert in certifications),
            )

        offices = _extract_known_values(combined_text, _CITY_NAMES)
        if offices:
            patch["offices"] = offices
            field_sources["offices"] = _field_source(
                pages,
                source_label=source_label,
                terms=tuple(offices),
            )

        industries = _extract_industries(lower_text)
        if industries:
            patch["industries"] = industries
            field_sources["industries"] = _field_source(
                pages,
                source_label=source_label,
                terms=tuple(industries),
            )

        references = _extract_references(combined_text)
        if references:
            patch["references"] = references
            field_sources["references"] = _field_source(
                pages,
                source_label=source_label,
                terms=tuple(ref["client"] for ref in references),
            )

        security_posture = _extract_security_posture(lower_text, certifications)
        if security_posture:
            patch["securityPosture"] = security_posture
            field_sources["securityPosture"] = _field_source(
                pages,
                source_label=source_label,
                terms=tuple(item["item"] for item in security_posture),
            )

        return WebsiteProfileExtraction(
            profile_patch=patch,
            field_sources=field_sources,
            warnings=tuple(warnings),
        )


class AnthropicWebsiteProfileExtractor:
    def __init__(self, *, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    def extract(
        self,
        *,
        source_url: str,
        pages: Sequence[WebsiteImportPage],
    ) -> WebsiteProfileExtraction:
        source_label = f"website:{source_url}"
        page_payload = [
            {
                "url": page.url,
                "title": page.title,
                "text": page.text[:2_500],
            }
            for page in pages
        ]
        system = (
            "Extract a review-only company profile import from public website text. "
            "Return a single JSON object with profile_patch, field_sources, and "
            "warnings. profile_patch may include only: website, description, email, "
            "phone, offices, industries, capabilities, certifications, references, "
            "securityPosture, sustainability. Use the frontend camelCase field names. "
            "Each field_sources value must include page_url, excerpt, and "
            "source_label. "
            f"Use source_label {source_label!r}. Do not invent facts."
        )
        data = anthropic_complete_json(
            api_key=self._api_key,
            model=self._model,
            system=system,
            user=json.dumps(
                {"source_url": source_url, "pages": page_payload},
                ensure_ascii=False,
            ),
            max_tokens=3_000,
        )
        return WebsiteProfileExtraction(
            profile_patch=_mapping(data.get("profile_patch")),
            field_sources={
                str(key): _string_mapping(value)
                for key, value in _mapping(data.get("field_sources")).items()
            },
            warnings=tuple(str(item) for item in _sequence(data.get("warnings"))),
        )


def resolve_website_profile_extractor(settings: Any) -> WebsiteProfileExtractor:
    api_key = getattr(settings, "anthropic_api_key", None)
    model = getattr(settings, "bidded_anthropic_model", None)
    if api_key and model:
        return AnthropicWebsiteProfileExtractor(api_key=api_key, model=model)
    return RuleBasedWebsiteProfileExtractor()


def _fetch_import_page(
    fetcher: WebsitePageFetcher,
    url: str,
    host_resolver: HostResolver,
) -> WebsiteImportPage:
    return _import_page_from_fetched(fetcher.fetch(url), host_resolver)


def _import_page_from_fetched(
    fetched: FetchedWebsitePage,
    host_resolver: HostResolver,
) -> WebsiteImportPage:
    fetched_url = normalize_website_url(fetched.url)
    _validate_public_http_url(fetched_url, host_resolver=host_resolver)
    parsed = _ParsedHTML.from_html(fetched.html)
    return WebsiteImportPage(
        url=fetched_url,
        title=parsed.title,
        text=parsed.text,
    )


def _select_key_page_urls(*, base_url: str, html: str, limit: int) -> list[str]:
    if limit <= 0:
        return []
    base = urlparse(base_url)
    parsed_html = _ParsedHTML.from_html(html)
    scored: dict[str, int] = {}
    for href, label in parsed_html.links:
        absolute, _fragment = urldefrag(urljoin(base_url, href))
        try:
            candidate = normalize_website_url(absolute)
        except WebsiteImportError:
            continue
        parsed = urlparse(candidate)
        if (parsed.scheme, parsed.netloc.lower()) != (base.scheme, base.netloc.lower()):
            continue
        if parsed.path == "/" or _looks_like_download(parsed.path):
            continue
        score = _key_page_score(parsed.path, label)
        if score <= 0:
            continue
        scored[candidate] = max(score, scored.get(candidate, 0))

    return [
        url
        for url, _score in sorted(
            scored.items(),
            key=lambda item: (-item[1], urlparse(item[0]).path),
        )[:limit]
    ]


def _key_page_score(path: str, label: str) -> int:
    haystack = f"{path} {label}".lower()
    scores = {
        "about": 100,
        "service": 90,
        "solution": 88,
        "case": 82,
        "customer": 80,
        "reference": 80,
        "contact": 72,
        "security": 70,
        "sustainability": 68,
        "esg": 64,
    }
    return max(
        (score for keyword, score in scores.items() if keyword in haystack),
        default=0,
    )


def _validate_public_http_url(url: str, *, host_resolver: HostResolver) -> None:
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise WebsiteImportError("Only http and https URLs can be imported.")
    host = parsed.hostname
    if not host:
        raise WebsiteImportError("URL must include a host.")
    host = host.lower().rstrip(".")
    if host in {"localhost"} or host.endswith((".localhost", ".local")):
        raise WebsiteImportError("Local/private hosts cannot be imported.")

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        try:
            addresses = host_resolver(host)
        except OSError as exc:
            raise WebsiteImportError(f"Could not resolve host {host}.") from exc
    else:
        addresses = (str(ip),)

    if not addresses:
        raise WebsiteImportError(f"Could not resolve host {host}.")
    for address in addresses:
        if _is_unsafe_ip(address):
            raise WebsiteImportError("Local/private hosts cannot be imported.")


def _resolve_host_ips(host: str) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                info[4][0]
                for info in socket.getaddrinfo(
                    host,
                    None,
                    type=socket.SOCK_STREAM,
                )
            }
        )
    )


def _is_unsafe_ip(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return True
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


@dataclass(frozen=True)
class _ParsedHTML:
    title: str | None
    text: str
    links: tuple[tuple[str, str], ...]

    @classmethod
    def from_html(cls, html: str) -> _ParsedHTML:
        parser = _HTMLContentParser()
        parser.feed(html)
        parser.close()
        return cls(
            title=_collapse_text(parser.title) or None,
            text=_collapse_text(" ".join(parser.text_parts)),
            links=tuple(parser.links),
        )


class _HTMLContentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.text_parts: list[str] = []
        self.links: list[tuple[str, str]] = []
        self._skip_depth = 0
        self._in_title = False
        self._active_link: tuple[str, list[str]] | None = None

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self._active_link = (href, [])

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if tag == "title":
            self._in_title = False
        if tag == "a" and self._active_link is not None:
            href, parts = self._active_link
            self.links.append((href, _collapse_text(" ".join(parts))))
            self._active_link = None

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        value = unescape(data)
        if self._in_title:
            self.title += f" {value}"
        if self._active_link is not None:
            self._active_link[1].append(value)
        self.text_parts.append(value)


def _decode_html(payload: bytes, content_type: str) -> str:
    match = re.search(r"charset=([\w.-]+)", content_type, flags=re.IGNORECASE)
    encoding = match.group(1) if match else "utf-8"
    return payload.decode(encoding, errors="replace")


def _collapse_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _looks_like_download(path: str) -> bool:
    return bool(
        re.search(
            r"\.(pdf|docx?|xlsx?|pptx?|zip|png|jpe?g|gif|svg)$",
            path,
            re.I,
        )
    )


def _best_description(pages: Sequence[WebsiteImportPage]) -> str | None:
    for page in pages:
        sentences = re.split(r"(?<=[.!?])\s+", page.text)
        for sentence in sentences:
            cleaned = _collapse_text(sentence)
            if 60 <= len(cleaned) <= 420 and "cookie" not in cleaned.lower():
                return cleaned
    for page in pages:
        cleaned = _collapse_text(page.text)
        if len(cleaned) > 40:
            return cleaned[:420].rstrip(" ,;")
    return None


def _first_match(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return match.group(0) if match else None


def _extract_capabilities(lower_text: str) -> list[str]:
    specs = [
        ("Cloud migration", ("cloud migration", "cloud transformation")),
        ("Cloud platforms", ("cloud platform", "aws", "azure", "google cloud")),
        ("Cybersecurity", ("cybersecurity", "cyber security", "security operations")),
        (
            "Identity & Access Management",
            ("iam", "identity and access", "identity & access"),
        ),
        ("DevOps", ("devops", "platform engineering", "ci/cd")),
        ("Data engineering", ("data engineering", "data platform", "analytics")),
        ("AI", ("artificial intelligence", " ai ", "machine learning")),
        ("Agile delivery", ("agile", "scrum", "product teams")),
        ("Systems integration", ("integration", "api", "systems integration")),
        ("Managed services", ("managed service", "operations", "support desk")),
    ]
    return [
        label
        for label, needles in specs
        if any(needle in lower_text for needle in needles)
    ]


def _extract_certifications(text: str) -> list[dict[str, str]]:
    cert_names = []
    for pattern, label in [
        (r"\bISO\s*27001\b", "ISO 27001"),
        (r"\bISO\s*9001\b", "ISO 9001"),
        (r"\bISO\s*14001\b", "ISO 14001"),
        (r"\bSOC\s*2\b", "SOC 2"),
        (r"\bCyber Essentials(?: Plus)?\b", "Cyber Essentials Plus"),
    ]:
        if re.search(pattern, text, flags=re.IGNORECASE):
            cert_names.append(label)
    return [
        {"name": name, "issuer": "Website", "validUntil": "Active"}
        for name in dict.fromkeys(cert_names)
    ]


_CITY_NAMES = (
    "Stockholm",
    "Malmö",
    "Gothenburg",
    "Göteborg",
    "Uppsala",
    "Linköping",
    "Lund",
    "Umeå",
    "Örebro",
    "Helsingborg",
    "Copenhagen",
    "Oslo",
    "Helsinki",
)


def _extract_known_values(text: str, values: Sequence[str]) -> list[str]:
    return [
        value
        for value in values
        if re.search(rf"\b{re.escape(value)}\b", text, flags=re.IGNORECASE)
    ]


def _extract_industries(lower_text: str) -> list[str]:
    specs = [
        ("Public sector", ("public sector", "government", "municipality", "region")),
        ("Healthcare", ("healthcare", "hospital", "patient", "region skåne")),
        ("Financial services", ("bank", "financial services", "insurance")),
        ("Transport", ("transport", "rail", "logistics")),
        ("Energy", ("energy", "utility", "grid")),
    ]
    return [
        label
        for label, needles in specs
        if any(needle in lower_text for needle in needles)
    ]


def _extract_references(text: str) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    for match in re.finditer(
        r"(?:case study|customer|client|reference)\s*[:\-]\s*"
        r"(?P<client>[A-ZÅÄÖ][A-Za-zÅÄÖåäö0-9 &.-]{2,80})"
        r"(?:\s*[-–]\s*(?P<scope>[^.]{10,180}))?",
        text,
        flags=re.IGNORECASE,
    ):
        client = _collapse_text(match.group("client"))
        scope = _collapse_text(match.group("scope") or "Website-listed reference.")
        if len(client) > 2:
            references.append(
                {
                    "client": client,
                    "scope": scope,
                    "value": "—",
                    "year": 2026,
                }
            )
    return references[:5]


def _extract_security_posture(
    lower_text: str,
    certifications: Sequence[Mapping[str, str]],
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    if any(cert.get("name") == "ISO 27001" for cert in certifications):
        items.append(
            {
                "item": "ISO 27001",
                "status": "Implemented",
                "note": "Listed on imported website pages.",
            }
        )
    if "soc" in lower_text or "security operations" in lower_text:
        items.append(
            {
                "item": "Security operations",
                "status": "Implemented",
                "note": "Security operations are described on the website.",
            }
        )
    if "gdpr" in lower_text:
        items.append(
            {
                "item": "GDPR",
                "status": "Implemented",
                "note": "GDPR is mentioned on the website.",
            }
        )
    return items


def _field_source(
    pages: Sequence[WebsiteImportPage],
    *,
    source_label: str,
    terms: Sequence[str],
    fallback: str | None = None,
) -> dict[str, str]:
    lower_terms = [term.lower() for term in terms if term]
    for page in pages:
        lower_text = page.text.lower()
        if any(term in lower_text for term in lower_terms):
            return {
                "page_url": page.url,
                "excerpt": _excerpt_for_terms(page.text, lower_terms),
                "source_label": source_label,
            }
    first_page = pages[0] if pages else WebsiteImportPage(url="", title=None, text="")
    return {
        "page_url": first_page.url,
        "excerpt": (fallback or first_page.text)[:300],
        "source_label": source_label,
    }


def _excerpt_for_terms(text: str, lower_terms: Sequence[str]) -> str:
    lower_text = text.lower()
    starts = [
        lower_text.find(term)
        for term in lower_terms
        if term and lower_text.find(term) >= 0
    ]
    if not starts:
        return text[:300]
    start = max(min(starts) - 120, 0)
    end = min(start + 300, len(text))
    return text[start:end].strip()


def _fill_missing_profile_fields(
    profile_patch: dict[str, Any],
    field_sources: dict[str, dict[str, str]],
    fallback_extraction: WebsiteProfileExtraction,
) -> None:
    for key, value in fallback_extraction.profile_patch.items():
        if _profile_value_present(value) and not _profile_value_present(
            profile_patch.get(key)
        ):
            profile_patch[key] = value
        if key in profile_patch and key not in field_sources:
            source = fallback_extraction.field_sources.get(key)
            if source:
                field_sources[key] = dict(source)


def _filter_resolved_website_import_warnings(
    warnings: Sequence[str],
    profile_patch: Mapping[str, Any],
) -> list[str]:
    filtered: list[str] = []
    seen: set[str] = set()
    for warning in warnings:
        normalized = warning.strip()
        if not normalized or normalized in seen:
            continue
        if _warning_is_resolved_by_profile_patch(normalized, profile_patch):
            continue
        filtered.append(normalized)
        seen.add(normalized)
    return filtered


def _warning_is_resolved_by_profile_patch(
    warning: str,
    profile_patch: Mapping[str, Any],
) -> bool:
    lower_warning = warning.lower()
    has_contact = _profile_value_present(profile_patch.get("email")) or (
        _profile_value_present(profile_patch.get("phone"))
    )
    if "contact email or phone" in lower_warning and has_contact:
        return True
    if (
        ("office address" in lower_warning or "location information" in lower_warning)
        and _profile_value_present(profile_patch.get("offices"))
    ):
        return True
    if "service capabilities" in lower_warning and _profile_value_present(
        profile_patch.get("capabilities")
    ):
        return True
    if "industries" in lower_warning and _profile_value_present(
        profile_patch.get("industries")
    ):
        return True
    has_governance_details = any(
        _profile_value_present(profile_patch.get(key))
        for key in (
            "certifications",
            "references",
            "securityPosture",
            "sustainability",
        )
    )
    if (
        "certifications" in lower_warning
        and "references" in lower_warning
        and "security posture" in lower_warning
        and "sustainability" in lower_warning
        and has_governance_details
    ):
        return True
    return False


def _profile_value_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        return bool(value)
    if isinstance(value, Sequence):
        return bool(value)
    return True


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _string_mapping(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, list | tuple) else ()
