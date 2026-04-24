from __future__ import annotations

from collections.abc import Sequence

import pytest

from bidded.company.website_import import (
    FetchedWebsitePage,
    WebsiteImportError,
    WebsiteImportPage,
    WebsiteProfileExtraction,
    import_company_website,
)


class RecordingFetcher:
    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.requested_urls: list[str] = []

    def fetch(self, url: str) -> FetchedWebsitePage:
        self.requested_urls.append(url)
        try:
            html = self.pages[url]
        except KeyError as exc:
            raise AssertionError(f"unexpected fetch: {url}") from exc
        return FetchedWebsitePage(url=url, html=html)


class RecordingExtractor:
    def __init__(self) -> None:
        self.pages: tuple[WebsiteImportPage, ...] = ()

    def extract(
        self,
        *,
        source_url: str,
        pages: Sequence[WebsiteImportPage],
    ) -> WebsiteProfileExtraction:
        self.pages = tuple(pages)
        return WebsiteProfileExtraction(
            profile_patch={
                "website": source_url,
                "description": "Nordic Digital Delivery builds secure cloud platforms.",
                "capabilities": ["Cloud platforms", "Cybersecurity"],
            },
            field_sources={
                "description": {
                    "page_url": pages[0].url,
                    "excerpt": "Nordic Digital Delivery builds secure cloud platforms.",
                    "source_label": f"website:{source_url}",
                }
            },
            warnings=("deterministic preview",),
        )


class MissingBasicsExtractor:
    def extract(
        self,
        *,
        source_url: str,
        pages: Sequence[WebsiteImportPage],
    ) -> WebsiteProfileExtraction:
        return WebsiteProfileExtraction(
            profile_patch={
                "website": source_url,
                "description": "Varuautomat på jobbet - Impact Solution",
                "industries": ["Retail", "Facilities management", "Workplace"],
                "capabilities": ["Workplace vending"],
            },
            field_sources={
                "description": {
                    "page_url": pages[0].url,
                    "excerpt": "Varuautomat på jobbet - Impact Solution",
                    "source_label": f"website:{source_url}",
                },
                "capabilities": {
                    "page_url": pages[0].url,
                    "excerpt": "Varuautomat på jobbet",
                    "source_label": f"website:{source_url}",
                },
            },
            warnings=(
                "No contact email or phone number found on the page.",
                "No office address or location information found on the page.",
                "Article content appears to be placeholder text (Lorem ipsum) "
                "and was not extracted as factual content.",
            ),
        )


def test_import_fetches_homepage_and_same_origin_key_pages() -> None:
    fetcher = RecordingFetcher(
        {
            "https://example.com/": """
                <html>
                  <head><title>Nordic Digital Delivery</title></head>
                  <body>
                    <script>window.secret = true;</script>
                    <nav><a href="/blog">Blog</a></nav>
                    <a href="mailto:info@example.com?subject=Hello">Email</a>
                    <a href="/about">About us</a>
                    <a href="/services/cloud">Cloud services</a>
                    <a href="https://other.example/about">External</a>
                    <p>Nordic Digital Delivery builds secure cloud platforms.</p>
                  </body>
                </html>
            """,
            "https://example.com/about": (
                "<h1>About</h1><p>Public sector delivery teams.</p>"
            ),
            "https://example.com/services/cloud": (
                "<h1>Services</h1><p>Azure and AWS.</p>"
            ),
        }
    )
    extractor = RecordingExtractor()

    preview = import_company_website(
        url="https://example.com",
        max_pages=3,
        fetcher=fetcher,
        extractor=extractor,
        host_resolver=lambda _host: ("93.184.216.34",),
    )

    assert fetcher.requested_urls == [
        "https://example.com/",
        "https://example.com/about",
        "https://example.com/services/cloud",
    ]
    assert [page.url for page in extractor.pages] == fetcher.requested_urls
    assert "window.secret" not in extractor.pages[0].text
    assert (
        "Nordic Digital Delivery builds secure cloud platforms."
        in extractor.pages[0].text
    )
    assert preview["source_url"] == "https://example.com/"
    assert preview["profile_patch"]["capabilities"] == [
        "Cloud platforms",
        "Cybersecurity",
    ]
    assert preview["warnings"] == ["deterministic preview"]


def test_import_treats_bare_email_address_as_website_domain() -> None:
    fetcher = RecordingFetcher(
        {
            "https://impactsolution.se/": (
                "<html><body><p>Impact Solution provides workplace vending.</p>"
                "</body></html>"
            )
        }
    )

    preview = import_company_website(
        url="info@impactsolution.se",
        fetcher=fetcher,
        extractor=RecordingExtractor(),
        host_resolver=lambda _host: ("93.184.216.34",),
    )

    assert fetcher.requested_urls == ["https://impactsolution.se/"]
    assert preview["source_url"] == "https://impactsolution.se/"


def test_import_strips_email_userinfo_without_password() -> None:
    fetcher = RecordingFetcher(
        {
            "https://impactsolution.se/": (
                "<html><body><p>Impact Solution provides workplace vending.</p>"
                "</body></html>"
            )
        }
    )

    preview = import_company_website(
        url="https://info@impactsolution.se/",
        fetcher=fetcher,
        extractor=RecordingExtractor(),
        host_resolver=lambda _host: ("93.184.216.34",),
    )

    assert fetcher.requested_urls == ["https://impactsolution.se/"]
    assert preview["source_url"] == "https://impactsolution.se/"


def test_import_rejects_explicit_url_credentials() -> None:
    with pytest.raises(WebsiteImportError, match="URL credentials"):
        import_company_website(
            url="https://user:pass@example.com",
            fetcher=RecordingFetcher({}),
            extractor=RecordingExtractor(),
            host_resolver=lambda _host: ("93.184.216.34",),
        )


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com",
        "http://127.0.0.1",
        "http://localhost:8000",
        "http://10.10.0.12",
    ],
)
def test_import_rejects_unsafe_urls(url: str) -> None:
    with pytest.raises(WebsiteImportError):
        import_company_website(
            url=url,
            fetcher=RecordingFetcher({}),
            extractor=RecordingExtractor(),
            host_resolver=lambda _host: ("93.184.216.34",),
        )


def test_rule_based_extractor_derives_common_profile_fields() -> None:
    fetcher = RecordingFetcher(
        {
            "https://example.com/": """
                <html><body>
                <h1>Nordic Digital Delivery</h1>
                <p>Nordic Digital Delivery is a Swedish consultancy helping
                public sector clients with cloud migration, cybersecurity,
                DevOps and data engineering.</p>
                <p>We are ISO 27001 and ISO 9001 certified.</p>
                <p>Offices in Stockholm and Malmö. Contact tenders@example.com
                or +46 8 123 456.</p>
                </body></html>
            """,
        }
    )

    preview = import_company_website(
        url="example.com",
        fetcher=fetcher,
        host_resolver=lambda _host: ("93.184.216.34",),
    )

    patch = preview["profile_patch"]
    assert preview["source_url"] == "https://example.com/"
    assert patch["website"] == "https://example.com/"
    assert patch["email"] == "tenders@example.com"
    assert patch["phone"] == "+46 8 123 456"
    assert "Cloud migration" in patch["capabilities"]
    assert "Cybersecurity" in patch["capabilities"]
    assert {"name": "ISO 27001", "issuer": "Website", "validUntil": "Active"} in patch[
        "certifications"
    ]
    assert "Stockholm" in patch["offices"]
    assert preview["field_sources"]["capabilities"]["source_label"] == (
        "website:https://example.com/"
    )


def test_import_fills_missing_contact_basics_from_rule_based_fallback() -> None:
    fetcher = RecordingFetcher(
        {
            "https://impactsolution.se/": """
                <html><body>
                <h1>Varuautomat på jobbet - Impact Solution</h1>
                <p>Vi hjälper arbetsplatser med moderna varuautomater.</p>
                <p>Kontakta oss på info@impactsolution.se eller
                +46 10 207 15 10.</p>
                <p>Besöksadress Tiundagatan 59, 753 20, Uppsala.</p>
                <article>Lorem ipsum dolor sit amet.</article>
                </body></html>
            """
        }
    )

    preview = import_company_website(
        url="impactsolution.se",
        fetcher=fetcher,
        extractor=MissingBasicsExtractor(),
        host_resolver=lambda _host: ("93.184.216.34",),
    )

    patch = preview["profile_patch"]
    assert patch["capabilities"] == ["Workplace vending"]
    assert patch["email"] == "info@impactsolution.se"
    assert patch["phone"] == "+46 10 207 15 10"
    assert patch["offices"] == ["Uppsala"]
    assert preview["field_sources"]["email"]["source_label"] == (
        "website:https://impactsolution.se/"
    )
    assert (
        "No contact email or phone number found on the page."
        not in preview["warnings"]
    )
    assert (
        "No office address or location information found on the page."
        not in preview["warnings"]
    )
    assert preview["warnings"] == [
        "Article content appears to be placeholder text (Lorem ipsum) "
        "and was not extracted as factual content.",
    ]
