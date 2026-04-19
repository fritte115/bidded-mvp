from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from bidded.db.seed_demo_company import build_demo_company_payload
from bidded.documents import PdfIngestionError
from bidded.orchestration import PrepareRunError, prepare_procurement_run

RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
COMPANY_ID = UUID("22222222-2222-4222-8222-222222222222")
TENDER_ID = UUID("33333333-3333-4333-8333-333333333333")
DOCUMENT_ID = UUID("44444444-4444-4444-8444-444444444444")
CHUNK_ID = UUID("55555555-5555-4555-8555-555555555555")
SECOND_RUN_ID = UUID("66666666-6666-4666-8666-666666666666")
OTHER_TENDER_ID = UUID("77777777-7777-4777-8777-777777777777")


class RecordingPrepareQuery:
    def __init__(self, client: RecordingPrepareClient, table_name: str) -> None:
        self.client = client
        self.table_name = table_name
        self.filters: list[tuple[str, str]] = []
        self.insert_payload: dict[str, Any] | None = None
        self.upsert_payload: list[dict[str, Any]] | None = None
        self.upsert_conflict: str | None = None

    def select(self, _columns: str) -> RecordingPrepareQuery:
        return self

    def eq(self, column: str, value: object) -> RecordingPrepareQuery:
        self.filters.append((column, str(value)))
        return self

    def insert(self, payload: dict[str, Any]) -> RecordingPrepareQuery:
        self.insert_payload = payload
        return self

    def upsert(
        self,
        payload: list[dict[str, Any]],
        *,
        on_conflict: str | None = None,
    ) -> RecordingPrepareQuery:
        self.upsert_payload = payload
        self.upsert_conflict = on_conflict
        return self

    def execute(self) -> object:
        if self.insert_payload is not None:
            row_id = self.client.next_insert_id(self.table_name)
            row = {**self.insert_payload, "id": str(row_id)}
            self.client.rows.setdefault(self.table_name, []).append(row)
            self.client.inserts.setdefault(self.table_name, []).append(
                self.insert_payload
            )
            return SimpleNamespace(data=[row])

        if self.upsert_payload is not None:
            self.client.upserts.setdefault(self.table_name, []).append(
                (self.upsert_payload, self.upsert_conflict)
            )
            returned_rows = []
            for payload in self.upsert_payload:
                row = self.client.upsert_row(self.table_name, payload)
                returned_rows.append(row)
            return SimpleNamespace(data=returned_rows)

        return SimpleNamespace(data=self._filtered_rows())

    def _filtered_rows(self) -> list[dict[str, Any]]:
        rows = self.client.rows.get(self.table_name, [])
        return [
            row
            for row in rows
            if all(str(row.get(column)) == value for column, value in self.filters)
        ]


class RecordingPrepareClient:
    def __init__(self) -> None:
        company = build_demo_company_payload()
        self.rows: dict[str, list[dict[str, Any]]] = {
            "companies": [{**company, "id": str(COMPANY_ID)}],
            "tenders": [
                {
                    "id": str(TENDER_ID),
                    "tenant_key": "demo",
                    "title": "Uploaded tender",
                }
            ],
            "documents": [_document_row(DOCUMENT_ID)],
            "document_chunks": [],
            "evidence_items": [],
            "agent_runs": [],
            "agent_outputs": [],
            "bid_decisions": [],
        }
        self.inserts: dict[str, list[dict[str, Any]]] = {}
        self.upserts: dict[str, list[tuple[list[dict[str, Any]], str | None]]] = {}
        self.table_names: list[str] = []
        self.insert_ids = {"agent_runs": [RUN_ID]}

    def table(self, table_name: str) -> RecordingPrepareQuery:
        self.table_names.append(table_name)
        return RecordingPrepareQuery(self, table_name)

    def next_insert_id(self, table_name: str) -> UUID:
        ids = self.insert_ids.get(table_name)
        if ids:
            return ids.pop(0)
        return UUID(int=len(self.rows.get(table_name, [])) + 1)

    def upsert_row(
        self,
        table_name: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        rows = self.rows.setdefault(table_name, [])
        tenant_key = str(payload.get("tenant_key"))
        evidence_key = str(payload.get("evidence_key"))
        for row in rows:
            if (
                str(row.get("tenant_key")) == tenant_key
                and str(row.get("evidence_key")) == evidence_key
            ):
                row.update(payload)
                return row

        row = {**payload, "id": str(UUID(int=len(rows) + 100))}
        rows.append(row)
        return row


def _ingest_document(
    client: RecordingPrepareClient,
    **kwargs: Any,
) -> SimpleNamespace:
    assert kwargs["document_id"] == DOCUMENT_ID
    assert kwargs["bucket_name"] == "procurement-fixtures"
    document = client.rows["documents"][0]
    document["parse_status"] = "parsed"
    client.rows["document_chunks"] = [
        _chunk_row(
            document_id=DOCUMENT_ID,
            chunk_id=CHUNK_ID,
            text="Supplier must provide ISO 27001 certification.",
            source_label="document 1",
        )
    ]
    return SimpleNamespace(document_id=DOCUMENT_ID, page_count=1, chunk_count=1)


def _document_row(
    document_id: UUID,
    *,
    tender_id: UUID = TENDER_ID,
    parse_status: str = "pending",
    source_label: str = "document 1",
) -> dict[str, Any]:
    return {
        "id": str(document_id),
        "tenant_key": "demo",
        "tender_id": str(tender_id),
        "company_id": None,
        "document_role": "tender_document",
        "parse_status": parse_status,
        "content_type": "application/pdf",
        "storage_path": f"demo/tenders/uploaded/{document_id}.pdf",
        "original_filename": f"{document_id}.pdf",
        "metadata": {"source_label": source_label},
    }


def _chunk_row(
    *,
    document_id: UUID,
    chunk_id: UUID,
    text: str,
    source_label: str,
    chunk_index: int = 0,
) -> dict[str, Any]:
    return {
        "id": str(chunk_id),
        "tenant_key": "demo",
        "document_id": str(document_id),
        "page_start": 1,
        "page_end": 1,
        "chunk_index": chunk_index,
        "text": text,
        "metadata": {"source_label": source_label},
    }


def _uuid(prefix: str, index: int) -> UUID:
    return UUID(f"{prefix}-{index:012d}")


def test_prepare_procurement_run_ingests_evidence_and_creates_pending_run() -> None:
    client = RecordingPrepareClient()
    ingestion_calls: list[UUID] = []

    def record_ingestion(
        received_client: RecordingPrepareClient,
        **kwargs: Any,
    ) -> SimpleNamespace:
        ingestion_calls.append(UUID(str(kwargs["document_id"])))
        return _ingest_document(received_client, **kwargs)

    result = prepare_procurement_run(
        client,
        tender_id=TENDER_ID,
        company_id=COMPANY_ID,
        document_ids=[DOCUMENT_ID],
        bucket_name="procurement-fixtures",
        ingest_document=record_ingestion,
    )

    assert ingestion_calls == [DOCUMENT_ID]
    assert result.tender_id == TENDER_ID
    assert result.company_id == COMPANY_ID
    assert result.document_ids == (DOCUMENT_ID,)
    assert result.agent_run_id == RUN_ID
    assert result.tender_evidence_count == 1
    assert result.company_evidence_count > 0
    assert result.evidence_count == result.tender_evidence_count + (
        result.company_evidence_count
    )
    assert result.warnings == ()

    document_result = result.document_results[0]
    assert document_result.document_id == DOCUMENT_ID
    assert document_result.parse_status == "parsed"
    assert document_result.chunk_count == 1
    assert document_result.evidence_count == 1

    payload = client.inserts["agent_runs"][0]
    assert payload["status"] == "pending"
    assert payload["run_config"]["document_ids"] == [str(DOCUMENT_ID)]
    assert payload["metadata"]["document_ids"] == [str(DOCUMENT_ID)]
    assert payload["metadata"]["created_via"] == "bidded_prepare_run"
    assert "running" not in {row.get("status") for row in client.rows["agent_runs"]}
    assert client.rows["agent_outputs"] == []
    assert client.rows["bid_decisions"] == []


def test_prepare_procurement_run_handles_seven_uploaded_documents() -> None:
    client = RecordingPrepareClient()
    document_ids = tuple(
        _uuid("44444444-4444-4444-8444", index) for index in range(1, 8)
    )
    chunk_ids = tuple(
        _uuid("55555555-5555-4555-8555", index) for index in range(1, 8)
    )
    client.rows["documents"] = [
        _document_row(
            document_id,
            source_label=f"document {index}",
        )
        for index, document_id in enumerate(document_ids, start=1)
    ]
    ingestion_calls: list[UUID] = []

    def ingest_one(
        received_client: RecordingPrepareClient,
        **kwargs: Any,
    ) -> SimpleNamespace:
        document_id = UUID(str(kwargs["document_id"]))
        ingestion_calls.append(document_id)
        index = document_ids.index(document_id)
        received_client.rows["documents"][index]["parse_status"] = "parsed"
        received_client.rows["document_chunks"].append(
            _chunk_row(
                document_id=document_id,
                chunk_id=chunk_ids[index],
                text=(
                    "Supplier must provide ISO 27001 certification for "
                    f"document {index + 1}."
                ),
                source_label=f"document {index + 1}",
            )
        )
        return SimpleNamespace(document_id=document_id, page_count=1, chunk_count=1)

    result = prepare_procurement_run(
        client,
        tender_id=TENDER_ID,
        company_id=COMPANY_ID,
        document_ids=document_ids,
        bucket_name="procurement-fixtures",
        ingest_document=ingest_one,
    )

    assert tuple(ingestion_calls) == document_ids
    assert result.document_ids == document_ids
    assert len(result.document_results) == 7
    assert [summary.chunk_count for summary in result.document_results] == [1] * 7
    assert [summary.evidence_count for summary in result.document_results] == [1] * 7
    assert result.tender_evidence_count == 7

    payload = client.inserts["agent_runs"][0]
    assert payload["run_config"]["document_ids"] == [
        str(document_id) for document_id in document_ids
    ]
    assert payload["metadata"]["document_ids"] == [
        str(document_id) for document_id in document_ids
    ]


def test_prepare_procurement_run_rejects_mixed_tender_documents() -> None:
    client = RecordingPrepareClient()
    other_document_id = UUID("88888888-8888-4888-8888-888888888888")
    client.rows["documents"].append(
        _document_row(other_document_id, tender_id=OTHER_TENDER_ID)
    )

    def fail_ingestion(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("mixed tender validation should run before ingestion")

    with pytest.raises(PrepareRunError, match="belongs to tender"):
        prepare_procurement_run(
            client,
            tender_id=TENDER_ID,
            company_id=COMPANY_ID,
            document_ids=[DOCUMENT_ID, other_document_id],
            bucket_name="procurement-fixtures",
            ingest_document=fail_ingestion,
        )

    assert client.rows["agent_runs"] == []
    assert client.rows["evidence_items"] == []


def test_prepare_procurement_run_blocks_parser_failed_documents() -> None:
    client = RecordingPrepareClient()
    client.rows["documents"][0]["parse_status"] = "parser_failed"
    ingestion_calls: list[UUID] = []

    def fail_ingestion(_client: RecordingPrepareClient, **kwargs: Any) -> None:
        ingestion_calls.append(UUID(str(kwargs["document_id"])))
        raise PdfIngestionError("Only text-based PDF ingestion is supported.")

    with pytest.raises(PrepareRunError, match="could not be parsed"):
        prepare_procurement_run(
            client,
            tender_id=TENDER_ID,
            company_id=COMPANY_ID,
            document_ids=[DOCUMENT_ID],
            bucket_name="procurement-fixtures",
            ingest_document=fail_ingestion,
        )

    assert ingestion_calls == [DOCUMENT_ID]
    assert client.rows["agent_runs"] == []
    assert client.rows["evidence_items"] == []


def test_prepare_procurement_run_reuses_parsed_chunks_on_idempotent_rerun() -> None:
    client = RecordingPrepareClient()
    client.insert_ids["agent_runs"] = [RUN_ID, SECOND_RUN_ID]
    client.rows["documents"][0]["parse_status"] = "parsed"
    client.rows["document_chunks"] = [
        _chunk_row(
            document_id=DOCUMENT_ID,
            chunk_id=CHUNK_ID,
            text="Supplier must provide ISO 27001 certification.",
            source_label="document 1",
        )
    ]

    def fail_ingestion(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("parsed document chunks should be reused")

    first = prepare_procurement_run(
        client,
        tender_id=TENDER_ID,
        company_id=COMPANY_ID,
        document_ids=[DOCUMENT_ID],
        bucket_name="procurement-fixtures",
        ingest_document=fail_ingestion,
    )
    second = prepare_procurement_run(
        client,
        tender_id=TENDER_ID,
        company_id=COMPANY_ID,
        document_ids=[DOCUMENT_ID],
        bucket_name="procurement-fixtures",
        ingest_document=fail_ingestion,
    )

    assert first.agent_run_id == RUN_ID
    assert second.agent_run_id == SECOND_RUN_ID
    assert first.tender_evidence_count == second.tender_evidence_count == 1
    assert first.company_evidence_count == second.company_evidence_count
    assert len(client.rows["agent_runs"]) == 2
    assert len(client.rows["document_chunks"]) == 1
    assert len(client.rows["evidence_items"]) == first.evidence_count
