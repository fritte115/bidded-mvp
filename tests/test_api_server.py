from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any
from zipfile import ZipFile

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
        self.single_requested = False
        self.upsert_payload: dict[str, Any] | None = None

    def select(self, _columns: str) -> FakeQuery:
        return self

    def upsert(
        self,
        payload: dict[str, Any],
        *,
        on_conflict: str | None = None,
    ) -> FakeQuery:
        self.upsert_payload = payload
        return self

    def eq(self, column: str, value: object) -> FakeQuery:
        self.filters.append((column, str(value)))
        return self

    def limit(self, _row_limit: int) -> FakeQuery:
        return self

    def single(self) -> FakeQuery:
        self.single_requested = True
        return self

    def execute(self) -> object:
        if self.upsert_payload is not None:
            next_id = f"{self.table_name}-{len(self.client.upserts) + 1}"
            row = {**self.upsert_payload, "id": next_id}
            self.client.upserts.append((self.table_name, row))
            self.client.rows.setdefault(self.table_name, []).append(row)
            return SimpleNamespace(data=[row])

        rows = self.client.rows[self.table_name]
        filtered_rows = [
            row
            for row in rows
            if all(str(row.get(column)) == value for column, value in self.filters)
        ]
        if self.single_requested:
            return SimpleNamespace(data=filtered_rows[0] if filtered_rows else None)
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
            "tenders": [{"id": TENDER_ID, "tenant_key": "demo", "title": "Example"}],
        }
        self.upserts: list[tuple[str, dict[str, Any]]] = []

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
    captured: dict[str, Any] = {
        "evidence_materialized": [],
        "ingested": [],
        "workers": [],
    }

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

    def record_evidence_materialization(
        supabase_client: object,
        *,
        document_id: str,
    ) -> None:
        captured["evidence_materialized"].append((supabase_client, document_id))

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
        graph_handlers: object,
    ) -> None:
        captured["workers"].append((supabase_client, run_id, log, graph_handlers))

    monkeypatch.setattr(api_server, "ingest_tender_document", record_ingestion)
    monkeypatch.setattr(
        api_server,
        "ensure_tender_evidence_items_for_document",
        record_evidence_materialization,
    )
    monkeypatch.setattr(
        api_server,
        "resolve_graph_handlers",
        lambda _settings: {"graph": "handlers"},
    )
    monkeypatch.setattr(api_server, "create_pending_run_context", record_pending_run)
    monkeypatch.setattr(api_server, "run_worker_once", record_worker)

    result = api_server.start_run(api_server.StartRunRequest(tender_id=TENDER_ID))

    assert result == {"run_id": RUN_ID}
    assert captured["ingested"] == [
        (client, DOCUMENT_ID_2, "public-procurements"),
    ]
    assert captured["evidence_materialized"] == [
        (client, DOCUMENT_ID_1),
        (client, DOCUMENT_ID_2),
    ]
    assert captured["pending_client"] is client
    assert captured["pending_kwargs"] == {
        "tender_id": TENDER_ID,
        "company_id": COMPANY_ID,
        "document_ids": [DOCUMENT_ID_1, DOCUMENT_ID_2],
    }
    assert captured["workers"] == [(client, RUN_ID, print, {"graph": "handlers"})]


class FakeStorageBucket:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files

    def list(self, folder: str) -> list[dict[str, str]]:
        prefix = f"{folder}/"
        return [
            {"name": path.removeprefix(prefix)}
            for path in sorted(self.files)
            if path.startswith(prefix) and "/" not in path.removeprefix(prefix)
        ]

    def download(self, path: str) -> bytes:
        return self.files[path]


class FakeStorage:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.bucket = FakeStorageBucket(files)

    def from_(self, _bucket_name: str) -> FakeStorageBucket:
        return self.bucket


def _docx_bytes() -> bytes:
    import io

    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", "<w:document />")
    return buffer.getvalue()


def test_auto_register_from_storage_finds_pdf_and_docx_documents() -> None:
    client = FakeSupabaseClient()
    client.rows["documents"] = []
    client.rows["tenders"] = [
        {
            "id": TENDER_ID,
            "tenant_key": "demo",
            "title": "DOCX Procurement",
        }
    ]
    client.storage = FakeStorage(
        {
            "demo/procurements/docx-procurement/01-main.pdf": b"%PDF-1.4\n%%EOF\n",
            "demo/procurements/docx-procurement/02-krav.docx": _docx_bytes(),
            "demo/procurements/docx-procurement/readme.txt": b"ignored",
        }
    )
    settings = SimpleNamespace(supabase_storage_bucket="public-procurements")

    registered = api_server._auto_register_from_storage(
        client,
        TENDER_ID,
        COMPANY_ID,
        settings,
    )

    assert registered == ["documents-1", "documents-2"]
    document_rows = [row for table, row in client.upserts if table == "documents"]
    assert [row["original_filename"] for row in document_rows] == [
        "01-main.pdf",
        "02-krav.docx",
    ]
    assert [row["content_type"] for row in document_rows] == [
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ]
