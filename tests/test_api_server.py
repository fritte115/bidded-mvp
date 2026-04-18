from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

from bidded import api_server

RUN_ID = "11111111-1111-4111-8111-111111111111"
COMPANY_ID = "22222222-2222-4222-8222-222222222222"
TENDER_ID = "33333333-3333-4333-8333-333333333333"
DOCUMENT_ID_1 = "44444444-4444-4444-8444-444444444441"
DOCUMENT_ID_2 = "44444444-4444-4444-8444-444444444442"


class FakeQuery:
    def __init__(self, client: FakeSupabaseClient, table_name: str) -> None:
        self.client = client
        self.table_name = table_name
        self.filters: list[tuple[str, str]] = []

    def select(self, _columns: str) -> FakeQuery:
        return self

    def eq(self, column: str, value: object) -> FakeQuery:
        self.filters.append((column, str(value)))
        return self

    def limit(self, _row_limit: int) -> FakeQuery:
        return self

    def execute(self) -> object:
        rows = self.client.rows[self.table_name]
        filtered_rows = [
            row
            for row in rows
            if all(str(row.get(column)) == value for column, value in self.filters)
        ]
        return SimpleNamespace(data=filtered_rows)


class FakeSupabaseClient:
    def __init__(self) -> None:
        self.rows: dict[str, list[dict[str, Any]]] = {
            "companies": [{"id": COMPANY_ID, "tenant_key": "demo"}],
            "documents": [
                {
                    "id": DOCUMENT_ID_1,
                    "tenant_key": "demo",
                    "tender_id": TENDER_ID,
                    "parse_status": "parsed",
                },
                {
                    "id": DOCUMENT_ID_2,
                    "tenant_key": "demo",
                    "tender_id": TENDER_ID,
                    "parse_status": "pending",
                },
            ],
        }

    def table(self, table_name: str) -> FakeQuery:
        return FakeQuery(self, table_name)


class ImmediateThread:
    def __init__(self, *, target: Any, daemon: bool) -> None:
        self.target = target
        self.daemon = daemon

    def start(self) -> None:
        self.target()


def test_start_run_parses_pending_documents_and_starts_worker(
    monkeypatch: Any,
) -> None:
    client = FakeSupabaseClient()
    settings = SimpleNamespace(
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="service-role",
        supabase_storage_bucket="public-procurements",
    )
    captured: dict[str, Any] = {"ingested": [], "workers": []}

    monkeypatch.setattr(api_server, "load_settings", lambda: settings)
    monkeypatch.setitem(
        sys.modules,
        "supabase",
        SimpleNamespace(create_client=lambda _url, _key: client),
    )
    monkeypatch.setattr(api_server.threading, "Thread", ImmediateThread)

    def record_ingestion(
        supabase_client: object,
        *,
        document_id: str,
        bucket_name: str,
    ) -> None:
        captured["ingested"].append((supabase_client, document_id, bucket_name))

    def record_pending_run(
        supabase_client: object,
        **kwargs: Any,
    ) -> SimpleNamespace:
        captured["pending_client"] = supabase_client
        captured["pending_kwargs"] = kwargs
        return SimpleNamespace(run_id=RUN_ID)

    def record_worker(
        supabase_client: object,
        *,
        run_id: str,
        log: object,
    ) -> None:
        captured["workers"].append((supabase_client, run_id, log))

    monkeypatch.setattr(api_server, "ingest_tender_pdf_document", record_ingestion)
    monkeypatch.setattr(api_server, "create_pending_run_context", record_pending_run)
    monkeypatch.setattr(api_server, "run_worker_once", record_worker)

    result = api_server.start_run(api_server.StartRunRequest(tender_id=TENDER_ID))

    assert result == {"run_id": RUN_ID}
    assert captured["ingested"] == [
        (client, DOCUMENT_ID_2, "public-procurements"),
    ]
    assert captured["pending_client"] is client
    assert captured["pending_kwargs"] == {
        "tender_id": TENDER_ID,
        "company_id": COMPANY_ID,
        "document_ids": [DOCUMENT_ID_1, DOCUMENT_ID_2],
    }
    assert captured["workers"] == [(client, RUN_ID, print)]
