from __future__ import annotations

import pytest
from types import SimpleNamespace
from typing import Any
from collections.abc import Mapping

from bidded.bid_document import BidDocumentError, generate_bid_document

RUN_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
TENDER_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
COMPANY_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"


class FakeQuery:
    def __init__(self, client: FakeBidDocClient, table_name: str) -> None:
        self.client = client
        self.table_name = table_name
        self.filters: list[tuple[str, str]] = []

    def select(self, _: str) -> FakeQuery:
        return self

    def eq(self, column: str, value: object) -> FakeQuery:
        self.filters.append((column, str(value)))
        return self

    def limit(self, _: int) -> FakeQuery:
        return self

    def execute(self) -> object:
        rows = self.client.rows.get(self.table_name, [])
        filtered = [
            row
            for row in rows
            if all(str(row.get(col)) == val for col, val in self.filters)
        ]
        return SimpleNamespace(data=filtered)


class FakeBidDocClient:
    def __init__(self, rows: dict[str, list[dict[str, Any]]]) -> None:
        self.rows = rows

    def table(self, name: str) -> FakeQuery:
        return FakeQuery(self, name)


def _make_client(*, verdict: str = "bid", include_bid: bool = True) -> FakeBidDocClient:
    return FakeBidDocClient(
        rows={
            "bid_decisions": [
                {
                    "agent_run_id": RUN_ID,
                    "tenant_key": "demo",
                    "verdict": verdict,
                    "confidence": 0.85,
                    "final_decision": {
                        "verdict": verdict,
                        "confidence": 0.85,
                        "cited_memo": "Strong match on all criteria.",
                        "vote_summary": {"bid": 3, "no_bid": 0, "conditional_bid": 1},
                        "compliance_matrix": [
                            {
                                "requirement": "ISO 27001",
                                "status": "met",
                                "assessment": "Certified",
                            }
                        ],
                        "compliance_blockers": [],
                        "potential_blockers": [
                            {
                                "claim": "Subcontractor approval needed",
                                "evidence_refs": [],
                            }
                        ],
                        "risk_register": [
                            {
                                "risk": "Tight deadline",
                                "severity": "medium",
                                "mitigation": "Add buffer",
                                "evidence_refs": [],
                            }
                        ],
                        "recommended_actions": ["Confirm team availability"],
                    },
                }
            ],
            "agent_runs": [
                {
                    "id": RUN_ID,
                    "tender_id": TENDER_ID,
                    "company_id": COMPANY_ID,
                }
            ],
            "tenders": [
                {
                    "id": TENDER_ID,
                    "title": "IT Consulting Services 2026",
                    "issuing_authority": "Skatteverket",
                    "procurement_reference": "SKV-2026-001",
                }
            ],
            "bids": (
                [
                    {
                        "agent_run_id": RUN_ID,
                        "rate_sek": 1200,
                        "margin_pct": 15,
                        "hours_estimated": 2000,
                        "notes": "Includes on-site days",
                    }
                ]
                if include_bid
                else []
            ),
            "agent_outputs": [
                {
                    "agent_run_id": RUN_ID,
                    "tenant_key": "demo",
                    "agent_role": "compliance_officer",
                    "round_name": "round_1_motion",
                    "validated_payload": {
                        "agent_role": "compliance_officer",
                        "vote": "bid",
                        "confidence": 0.9,
                        "top_findings": [
                            {
                                "claim": "All exclusion grounds cleared",
                                "evidence_refs": [],
                            }
                        ],
                        "assumptions": ["Annual report available"],
                    },
                }
            ],
            "companies": [
                {
                    "id": COMPANY_ID,
                    "name": "Acme IT AB",
                    "organization_number": "556000-0001",
                    "capabilities": {"service_lines": ["Cloud", "Security"]},
                }
            ],
        }
    )


def test_returns_markdown_header():
    doc = generate_bid_document(_make_client(), run_id=RUN_ID)
    assert doc.startswith("# Bid Response: IT Consulting Services 2026")


def test_contains_company_name():
    doc = generate_bid_document(_make_client(), run_id=RUN_ID)
    assert "Acme IT AB" in doc


def test_contains_pricing_proposal():
    doc = generate_bid_document(_make_client(), run_id=RUN_ID)
    assert "Pricing Proposal" in doc
    assert "1 200 SEK/h" in doc
    assert "2 400 000 SEK" in doc


def test_pricing_dashes_when_no_bid_row():
    doc = generate_bid_document(_make_client(include_bid=False), run_id=RUN_ID)
    assert "Pricing Proposal" in doc
    assert "| Hourly Rate | — |" in doc


def test_contains_compliance_section():
    doc = generate_bid_document(_make_client(), run_id=RUN_ID)
    assert "Compliance Statement" in doc
    assert "ISO 27001" in doc


def test_contains_specialist_summary():
    doc = generate_bid_document(_make_client(), run_id=RUN_ID)
    assert "Compliance Officer" in doc
    assert "All exclusion grounds cleared" in doc


def test_raises_for_no_bid_verdict():
    client = _make_client(verdict="no_bid")
    with pytest.raises(BidDocumentError, match="no_bid"):
        generate_bid_document(client, run_id=RUN_ID)


def test_raises_for_missing_decision():
    client = FakeBidDocClient(rows={"bid_decisions": [], "agent_runs": [], "tenders": [], "bids": [], "agent_outputs": [], "companies": []})
    with pytest.raises(BidDocumentError, match="No persisted decision"):
        generate_bid_document(client, run_id=RUN_ID)


def test_conditional_bid_shows_conditions_section():
    doc = generate_bid_document(_make_client(verdict="conditional_bid"), run_id=RUN_ID)
    assert "Conditions" in doc
    assert "Subcontractor approval needed" in doc


def test_run_id_in_footer():
    doc = generate_bid_document(_make_client(), run_id=RUN_ID)
    assert RUN_ID in doc
