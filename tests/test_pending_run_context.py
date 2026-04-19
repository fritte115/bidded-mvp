from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from bidded.orchestration import PendingRunContextError, create_pending_run_context

RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
COMPANY_ID = UUID("22222222-2222-4222-8222-222222222222")
TENDER_ID = UUID("33333333-3333-4333-8333-333333333333")
OTHER_TENDER_ID = UUID("33333333-3333-4333-8333-333333333334")
DOCUMENT_ID = UUID("44444444-4444-4444-8444-444444444444")
SECOND_DOCUMENT_ID = UUID("55555555-5555-4555-8555-555555555555")


class RecordingQuery:
    def __init__(self, client: RecordingSupabaseClient, table_name: str) -> None:
        self.client = client
        self.table_name = table_name
        self.filters: list[tuple[str, str]] = []
        self.insert_payload: dict[str, Any] | None = None

    def select(self, _columns: str) -> RecordingQuery:
        return self

    def eq(self, column: str, value: object) -> RecordingQuery:
        self.filters.append((column, str(value)))
        return self

    def insert(self, payload: dict[str, Any]) -> RecordingQuery:
        self.insert_payload = payload
        return self

    def execute(self) -> object:
        if self.insert_payload is not None:
            self.client.inserts.setdefault(self.table_name, []).append(
                self.insert_payload
            )
            row = {
                **self.insert_payload,
                "id": str(self.client.insert_ids[self.table_name]),
            }
            return type("Response", (), {"data": [row]})()

        rows = self.client.rows.get(self.table_name, [])
        filtered_rows = [
            row
            for row in rows
            if all(str(row.get(column)) == value for column, value in self.filters)
        ]
        return type("Response", (), {"data": filtered_rows})()


class RecordingSupabaseClient:
    def __init__(self) -> None:
        self.rows: dict[str, list[dict[str, Any]]] = {
            "companies": [{"id": str(COMPANY_ID), "tenant_key": "demo"}],
            "tenders": [{"id": str(TENDER_ID), "tenant_key": "demo"}],
            "documents": [
                {
                    "id": str(DOCUMENT_ID),
                    "tenant_key": "demo",
                    "tender_id": str(TENDER_ID),
                    "document_role": "tender_document",
                    "parse_status": "parsed",
                }
            ],
        }
        self.insert_ids = {"agent_runs": RUN_ID}
        self.inserts: dict[str, list[dict[str, Any]]] = {}
        self.table_names: list[str] = []

    def table(self, table_name: str) -> RecordingQuery:
        self.table_names.append(table_name)
        return RecordingQuery(self, table_name)


def test_create_pending_run_context_inserts_pending_agent_run() -> None:
    client = RecordingSupabaseClient()

    result = create_pending_run_context(
        client,
        tender_id=TENDER_ID,
        company_id=COMPANY_ID,
        document_id=DOCUMENT_ID,
    )

    assert result.run_id == RUN_ID
    assert result.tender_id == TENDER_ID
    assert result.company_id == COMPANY_ID
    assert result.document_ids == [DOCUMENT_ID]
    assert client.table_names == ["companies", "tenders", "documents", "agent_runs"]

    payload = client.inserts["agent_runs"][0]
    assert payload["tenant_key"] == "demo"
    assert payload["tender_id"] == str(TENDER_ID)
    assert payload["company_id"] == str(COMPANY_ID)
    assert payload["status"] == "pending"
    assert payload["run_config"] == result.run_config
    assert payload["metadata"] == {
        "created_via": "bidded_cli",
        "document_ids": [str(DOCUMENT_ID)],
    }

    config = payload["run_config"]
    assert config["language_policy"] == {
        "input_language": "en",
        "output_language": "en",
    }
    assert config["procurement_context"] == {
        "jurisdiction": "SE",
        "market": "Swedish public procurement",
        "procedure_family": "public_procurement",
    }
    assert config["active_agent_roles"] == [
        "evidence_scout",
        "compliance_officer",
        "win_strategist",
        "delivery_cfo",
        "red_team",
        "judge",
    ]
    assert config["evidence_lock"] == {
        "enabled": True,
        "allowed_source_types": ["tender_document", "company_profile"],
        "require_material_claim_evidence": True,
        "allow_new_external_sources": False,
    }
    assert config["document_ids"] == [str(DOCUMENT_ID)]


def test_create_pending_run_context_records_multiple_documents() -> None:
    client = RecordingSupabaseClient()
    client.rows["documents"].append(
        {
            "id": str(SECOND_DOCUMENT_ID),
            "tenant_key": "demo",
            "tender_id": str(TENDER_ID),
            "document_role": "tender_document",
            "parse_status": "parsed",
        }
    )

    result = create_pending_run_context(
        client,
        tender_id=TENDER_ID,
        company_id=COMPANY_ID,
        document_ids=[DOCUMENT_ID, SECOND_DOCUMENT_ID],
        created_via="bidded_prepare_run",
    )

    assert result.document_ids == [DOCUMENT_ID, SECOND_DOCUMENT_ID]
    payload = client.inserts["agent_runs"][0]
    assert payload["run_config"]["document_ids"] == [
        str(DOCUMENT_ID),
        str(SECOND_DOCUMENT_ID),
    ]
    assert payload["metadata"] == {
        "created_via": "bidded_prepare_run",
        "document_ids": [str(DOCUMENT_ID), str(SECOND_DOCUMENT_ID)],
    }


@pytest.mark.parametrize(
    ("table_name", "expected_error"),
    [
        ("companies", "Demo company does not exist"),
        ("tenders", "Demo tender does not exist"),
        ("documents", "Tender procurement document does not exist"),
    ],
)
def test_create_pending_run_context_validates_required_rows(
    table_name: str,
    expected_error: str,
) -> None:
    client = RecordingSupabaseClient()
    client.rows[table_name] = []

    with pytest.raises(PendingRunContextError, match=expected_error):
        create_pending_run_context(
            client,
            tender_id=TENDER_ID,
            company_id=COMPANY_ID,
            document_id=DOCUMENT_ID,
        )

    assert "agent_runs" not in client.inserts


def test_create_pending_run_context_requires_tender_document_linkage() -> None:
    client = RecordingSupabaseClient()
    client.rows["documents"][0]["document_role"] = "company_profile"

    with pytest.raises(
        PendingRunContextError,
        match="Tender procurement document does not exist",
    ):
        create_pending_run_context(
            client,
            tender_id=TENDER_ID,
            company_id=COMPANY_ID,
            document_id=DOCUMENT_ID,
        )

    assert "agent_runs" not in client.inserts


def test_create_pending_run_context_rejects_documents_from_other_tenders() -> None:
    client = RecordingSupabaseClient()
    client.rows["documents"][0]["tender_id"] = str(OTHER_TENDER_ID)

    with pytest.raises(
        PendingRunContextError,
        match="Tender procurement document does not exist",
    ):
        create_pending_run_context(
            client,
            tender_id=TENDER_ID,
            company_id=COMPANY_ID,
            document_id=DOCUMENT_ID,
        )

    assert "agent_runs" not in client.inserts


def test_create_pending_run_context_requires_parsed_tender_documents() -> None:
    client = RecordingSupabaseClient()
    client.rows["documents"][0]["parse_status"] = "pending"

    with pytest.raises(
        PendingRunContextError,
        match="parsed tender document",
    ):
        create_pending_run_context(
            client,
            tender_id=TENDER_ID,
            company_id=COMPANY_ID,
            document_id=DOCUMENT_ID,
        )

    assert "agent_runs" not in client.inserts
