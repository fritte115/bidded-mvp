from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from bidded.bolagsverket import BolagsverketError, fetch_company_data


def _mock_response(status: int, body: dict | None = None) -> MagicMock:
    mock = MagicMock()
    mock.status_code = status
    mock.is_success = status < 400
    mock.json.return_value = body or {}
    return mock


def test_invalid_format_raises():
    with pytest.raises(BolagsverketError, match="Invalid organisation number"):
        fetch_company_data("abc123")


def test_too_short_raises():
    with pytest.raises(BolagsverketError, match="Invalid organisation number"):
        fetch_company_data("12345")


def test_401_raises_requires_credentials():
    with patch("httpx.get", return_value=_mock_response(401)):
        with pytest.raises(BolagsverketError, match="requires_credentials"):
            fetch_company_data("5560000000")


def test_403_raises_requires_credentials():
    with patch("httpx.get", return_value=_mock_response(403)):
        with pytest.raises(BolagsverketError, match="requires_credentials"):
            fetch_company_data("5560000000")


def test_404_raises_not_found():
    with patch("httpx.get", return_value=_mock_response(404)):
        with pytest.raises(BolagsverketError, match="not found"):
            fetch_company_data("5560000000")


def test_500_raises_api_error():
    with patch("httpx.get", return_value=_mock_response(500)):
        with pytest.raises(BolagsverketError, match="500"):
            fetch_company_data("5560000000")


def test_request_error_raises():
    with patch("httpx.get", side_effect=httpx.ConnectError("refused")):
        with pytest.raises(BolagsverketError, match="Request failed"):
            fetch_company_data("5560000000")


def test_200_returns_parsed_dict():
    payload = {
        "foretagsnamn": "Acme AB",
        "registreringsdatum": "2000-01-01",
        "foretagsform": "AB",
        "besoksadress": "Storgatan 1, Stockholm",
    }
    with patch("httpx.get", return_value=_mock_response(200, payload)):
        result = fetch_company_data("5560000000")
    assert result["organization_number"] == "5560000000"
    assert result["name"] == "Acme AB"
    assert result["registration_date"] == "2000-01-01"
    assert result["company_form"] == "AB"
    assert result["address"] == "Storgatan 1, Stockholm"
    assert result["raw"] == payload


def test_normalization_strips_hyphen():
    with patch("httpx.get", return_value=_mock_response(401)):
        with pytest.raises(BolagsverketError, match="requires_credentials"):
            fetch_company_data("556000-0000")


def test_normalization_strips_spaces():
    with patch("httpx.get", return_value=_mock_response(401)):
        with pytest.raises(BolagsverketError, match="requires_credentials"):
            fetch_company_data("556000 0000")


def test_normalization_12_digits_accepted():
    with patch("httpx.get", return_value=_mock_response(401)):
        with pytest.raises(BolagsverketError, match="requires_credentials"):
            fetch_company_data("165560000000")
