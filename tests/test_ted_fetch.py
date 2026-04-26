from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from bidded.ted_fetch import (
    TedFetchError,
    _first_str,
    _parse_ted_date,
    fetch_swedish_notices,
    map_notice_to_explore_shape,
    map_notice_to_tender_row,
    upsert_notices_to_supabase,
)

# v3 API notice shape (as returned by TED)
_SAMPLE_NOTICE = {
    "publication-number": "000001-2026",
    "notice-identifier": "abc-123",
    "notice-title": {
        "swe": "IT-konsulttjänster ramavtal",
        "eng": "IT Consulting Framework Agreement",
    },
    "buyer-name": {"swe": ["Skatteverket"]},
    "buyer-country": ["SWE"],
    "buyer-country-sub": ["SE110"],
    "publication-date": "20260101",
    "deadline": ["2026-03-01T00:00:00+01:00"],
    "procedure-type": "open",
    "contract-nature-main-proc": "services",
    "classification-cpv": ["72000000", "72200000"],
    "estimated-value-proc": "5000000",
    "estimated-value-cur-proc": "SEK",
}


def _mock_response(status: int, body: dict[str, Any]) -> MagicMock:
    mock = MagicMock()
    mock.status_code = status
    mock.json.return_value = body
    if status >= 400:
        mock.raise_for_status.side_effect = httpx.HTTPStatusError(
            message=f"HTTP {status}",
            request=MagicMock(),
            response=mock,
        )
    else:
        mock.raise_for_status.return_value = None
    return mock


def test_fetch_returns_notices_on_200():
    with patch(
        "httpx.post",
        return_value=_mock_response(200, {"notices": [_SAMPLE_NOTICE]}),
    ):
        result = fetch_swedish_notices()
    assert len(result) == 1
    assert result[0]["publication-number"] == "000001-2026"


def test_fetch_raises_on_http_error():
    with patch("httpx.post", return_value=_mock_response(500, {})):
        with pytest.raises(TedFetchError, match="500"):
            fetch_swedish_notices()


def test_fetch_raises_on_request_error():
    with patch("httpx.post", side_effect=httpx.ConnectError("connection refused")):
        with pytest.raises(TedFetchError, match="request failed"):
            fetch_swedish_notices()


def test_fetch_raises_on_unexpected_shape():
    with patch("httpx.post", return_value=_mock_response(200, {"notices": "bad"})):
        with pytest.raises(TedFetchError, match="Unexpected"):
            fetch_swedish_notices()


def test_first_str_with_list():
    assert _first_str(["val1", "val2"]) == "val1"


def test_first_str_with_string():
    assert _first_str("direct") == "direct"


def test_first_str_missing():
    assert _first_str(None) is None


def test_first_str_empty_list():
    assert _first_str([]) is None


def test_first_str_multilingual_dict():
    assert _first_str({"swe": ["Täby"], "eng": "Taby"}) == "Täby"


def test_parse_ted_date_yyyymmdd():
    assert _parse_ted_date("20260101") == "2026-01-01"


def test_parse_ted_date_iso_with_tz():
    assert _parse_ted_date("2026-03-01T00:00:00+01:00") == "2026-03-01"


def test_parse_ted_date_z_suffix():
    assert _parse_ted_date("2023-10-25Z") == "2023-10-25"


def test_parse_ted_date_date_with_tz_offset():
    assert _parse_ted_date("2017-02-15+01:00") == "2017-02-15"


def test_parse_ted_date_none():
    assert _parse_ted_date(None) is None


def test_map_notice_to_explore_shape():
    shaped = map_notice_to_explore_shape(_SAMPLE_NOTICE)
    assert shaped["id"] == "abc-123"
    assert shaped["source"] == "TED"
    assert shaped["title"] == "IT-konsulttjänster ramavtal"
    assert shaped["buyer"] == "Skatteverket"
    assert shaped["country"] == "SE"
    assert shaped["nutsCode"] == "SE110"
    assert shaped["cpvCodes"] == ["72000000", "72200000"]
    assert shaped["procedureType"] == "Open"
    assert shaped["contractType"] == "Services"
    assert shaped["estimatedValueMSEK"] == 5.0
    assert shaped["currency"] == "SEK"
    assert shaped["publishedAt"] == "2026-01-01"
    assert shaped["deadline"] == "2026-03-01"
    assert "000001-2026" in shaped["sourceUrl"]


def test_map_notice_fields():
    row = map_notice_to_tender_row(_SAMPLE_NOTICE)
    assert row["procurement_reference"] == "000001-2026"
    assert row["title"] == "IT-konsulttjänster ramavtal"
    assert row["issuing_authority"] == "Skatteverket"
    assert row["tenant_key"] == "demo"
    assert row["procurement_context"]["source"] == "ted_api"
    assert row["procurement_context"]["country_code"] == "SE"
    assert row["language_policy"]["source_document_language"] == "sv"
    assert row["metadata"]["registered_via"] == "ted_api_fetch"


def test_map_notice_truncates_long_title():
    long_notice = dict(_SAMPLE_NOTICE)
    long_notice["notice-title"] = {"swe": "X" * 300}
    row = map_notice_to_tender_row(long_notice)
    assert len(row["title"]) == 255


def test_map_notice_skips_empty_pub_number():
    no_pub = {k: v for k, v in _SAMPLE_NOTICE.items() if k != "publication-number"}
    row = map_notice_to_tender_row(no_pub)
    assert row["procurement_reference"] == ""


class FakeTedQuery:
    def __init__(self, client: FakeTedClient, table: str) -> None:
        self.client = client
        self.table_name = table
        self.filters: list[tuple[str, str]] = []
        self._update_payload: dict[str, Any] | None = None

    def select(self, _: str) -> FakeTedQuery:
        return self

    def eq(self, col: str, val: object) -> FakeTedQuery:
        self.filters.append((col, str(val)))
        return self

    def limit(self, _: int) -> FakeTedQuery:
        return self

    def update(self, payload: dict[str, Any]) -> FakeTedQuery:
        self._update_payload = payload
        return self

    def insert(self, row: dict[str, Any]) -> FakeTedQuery:
        new_row = {"id": "new-id-001", **row}
        self.client.rows[self.table_name].append(new_row)
        self.client.last_inserted = new_row
        return self

    def execute(self) -> object:
        if self._update_payload is not None:
            return SimpleNamespace(data=[])
        rows = self.client.rows.get(self.table_name, [])
        filtered = [
            r for r in rows
            if all(str(r.get(c)) == v for c, v in self.filters)
        ]
        return SimpleNamespace(data=filtered)


class FakeTedClient:
    def __init__(self) -> None:
        self.rows: dict[str, list[dict[str, Any]]] = {"tenders": []}
        self.last_inserted: dict[str, Any] | None = None

    def table(self, name: str) -> FakeTedQuery:
        return FakeTedQuery(self, name)


def test_upsert_inserts_new_notice():
    client = FakeTedClient()
    ids = upsert_notices_to_supabase(client, [_SAMPLE_NOTICE])
    assert ids == ["new-id-001"]
    assert len(client.rows["tenders"]) == 1


def test_upsert_updates_existing_notice():
    existing_id = "existing-id-111"
    client = FakeTedClient()
    client.rows["tenders"] = [
        {
            "id": existing_id,
            "tenant_key": "demo",
            "procurement_reference": "000001-2026",
        }
    ]
    ids = upsert_notices_to_supabase(client, [_SAMPLE_NOTICE])
    assert ids == [existing_id]


def test_upsert_skips_notice_without_pub_number():
    client = FakeTedClient()
    no_pub_notice = {
        k: v for k, v in _SAMPLE_NOTICE.items() if k != "publication-number"
    }
    ids = upsert_notices_to_supabase(client, [no_pub_notice])
    assert ids == []
    assert len(client.rows["tenders"]) == 0
