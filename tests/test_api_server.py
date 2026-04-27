from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any
from uuid import UUID
from zipfile import ZipFile

from fastapi.testclient import TestClient

from bidded import api_server
from bidded.auth import AuthenticatedUser
from bidded.documents.company_kb import (
    CompanyKbDocumentSummary,
    CompanyKbDocumentType,
    CompanyKbRegistrationResult,
)

RUN_ID = "11111111-1111-4111-8111-111111111111"
COMPANY_ID = "22222222-2222-4222-8222-222222222222"
TENDER_ID = "33333333-3333-4333-8333-333333333333"
DOCUMENT_ID_1 = "44444444-4444-4444-8444-444444444441"
DOCUMENT_ID_2 = "44444444-4444-4444-8444-444444444442"
USER_ID = "55555555-5555-4555-8555-555555555555"
SUPERADMIN_ID = "66666666-6666-4666-8666-666666666666"
ORG_ID = "00000000-0000-4000-8000-000000000001"


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
            "companies": [
                {"id": COMPANY_ID, "tenant_key": "demo", "organization_id": ORG_ID}
            ],
            "tenders": [
                {
                    "id": TENDER_ID,
                    "tenant_key": "demo",
                    "organization_id": ORG_ID,
                    "title": "Example",
                }
            ],
            "agent_runs": [
                {"id": RUN_ID, "tenant_key": "demo", "organization_id": ORG_ID}
            ],
            "profiles": [
                {"user_id": USER_ID, "global_role": None},
                {"user_id": SUPERADMIN_ID, "global_role": "superadmin"},
            ],
            "organization_memberships": [
                {
                    "organization_id": ORG_ID,
                    "user_id": USER_ID,
                    "role": "user",
                    "status": "active",
                }
            ],
            "documents": [
                {
                    "id": DOCUMENT_ID_1,
                    "tenant_key": "demo",
                    "tender_id": TENDER_ID,
                    "document_role": "tender_document",
                    "parse_status": "parsed",
                },
                {
                    "id": DOCUMENT_ID_2,
                    "tenant_key": "demo",
                    "tender_id": TENDER_ID,
                    "document_role": "tender_document",
                    "parse_status": "pending",
                },
            ],
            "document_chunks": [
                {
                    "id": "chunk-1",
                    "tenant_key": "demo",
                    "document_id": DOCUMENT_ID_1,
                },
                {
                    "id": "chunk-2",
                    "tenant_key": "demo",
                    "document_id": DOCUMENT_ID_2,
                },
            ],
            "requirement_fit_gaps": [],
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
    monkeypatch.setattr(
        api_server,
        "require_tender_member",
        lambda *_args, **_kwargs: "00000000-0000-4000-8000-000000000001",
    )
    monkeypatch.setattr(api_server, "create_pending_run_context", record_pending_run)
    monkeypatch.setattr(api_server, "run_worker_once", record_worker)

    result = api_server.start_run(
        api_server.StartRunRequest(tender_id=TENDER_ID),
        user=AuthenticatedUser(user_id=USER_ID, email="user@example.com"),
    )

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


def test_get_run_fit_gaps_returns_stable_rows(monkeypatch: Any) -> None:
    client = FakeSupabaseClient()
    client.rows["requirement_fit_gaps"] = [
        {
            "tenant_key": "demo",
            "agent_run_id": RUN_ID,
            "tender_id": TENDER_ID,
            "company_id": COMPANY_ID,
            "requirement_key": "TENDER-REQ-001",
            "requirement": "Supplier must hold ISO 27001.",
            "requirement_type": "qualification_requirement",
            "match_status": "matched",
            "risk_level": "low",
            "confidence": 0.91,
            "assessment": "Company evidence matches the tender requirement.",
            "tender_evidence_refs": [
                {
                    "evidence_key": "TENDER-REQ-001",
                    "source_type": "tender_document",
                    "evidence_id": "66666666-6666-4666-8666-666666666666",
                }
            ],
            "company_evidence_refs": [
                {
                    "evidence_key": "COMPANY-CERT-001",
                    "source_type": "company_profile",
                    "evidence_id": "77777777-7777-4777-8777-777777777777",
                }
            ],
            "tender_evidence_ids": ["66666666-6666-4666-8666-666666666666"],
            "company_evidence_ids": ["77777777-7777-4777-8777-777777777777"],
            "missing_info": [],
            "recommended_actions": [],
            "metadata": {},
        }
    ]
    settings = SimpleNamespace(
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="service-role",
    )
    monkeypatch.setattr(api_server, "load_settings", lambda: settings)
    monkeypatch.setattr(api_server, "_service_role_client", lambda _settings: client)

    result = api_server.get_run_fit_gaps(
        RUN_ID,
        user=AuthenticatedUser(user_id=USER_ID, email="user@example.com"),
    )

    assert result["run_id"] == RUN_ID
    assert result["fit_gaps"][0]["requirement_key"] == "TENDER-REQ-001"
    assert result["fit_gaps"][0]["match_status"] == "matched"
    assert result["fit_gaps"][0]["company_evidence_refs"][0]["evidence_key"] == (
        "COMPANY-CERT-001"
    )


def test_get_run_fit_gaps_rejects_non_member(monkeypatch: Any) -> None:
    client = FakeSupabaseClient()
    settings = SimpleNamespace(
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="service-role",
    )
    monkeypatch.setattr(api_server, "load_settings", lambda: settings)
    monkeypatch.setattr(api_server, "_service_role_client", lambda _settings: client)

    response = TestClient(api_server.app).get(
        f"/api/runs/{RUN_ID}/fit-gaps",
        headers={"Authorization": "Bearer invalid"},
    )

    assert response.status_code in {401, 403}


def test_start_run_skips_visual_reference_documents_without_chunks(
    monkeypatch: Any,
) -> None:
    client = FakeSupabaseClient()
    client.rows["document_chunks"] = [
        {
            "id": "chunk-1",
            "tenant_key": "demo",
            "document_id": DOCUMENT_ID_1,
        }
    ]
    settings = SimpleNamespace(
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="service-role",
        supabase_storage_bucket="public-procurements",
    )
    captured: dict[str, Any] = {
        "evidence_materialized": [],
        "ingested": [],
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
        for row in client.rows["documents"]:
            if row["id"] == document_id:
                row["parse_status"] = "parsed"
                row["metadata"] = {
                    "parser": {
                        "status": "parsed_skipped",
                        "reason": "no_text_layer",
                        "visual_document": True,
                    }
                }

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
        captured["pending_kwargs"] = kwargs
        return SimpleNamespace(run_id=RUN_ID)

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
    monkeypatch.setattr(
        api_server,
        "require_tender_member",
        lambda *_args, **_kwargs: "00000000-0000-4000-8000-000000000001",
    )
    monkeypatch.setattr(api_server, "create_pending_run_context", record_pending_run)
    monkeypatch.setattr(api_server, "run_worker_once", lambda *_args, **_kwargs: None)

    result = api_server.start_run(
        api_server.StartRunRequest(tender_id=TENDER_ID),
        user=AuthenticatedUser(user_id=USER_ID, email="user@example.com"),
    )

    assert result == {"run_id": RUN_ID}
    assert captured["ingested"] == [
        (client, DOCUMENT_ID_2, "public-procurements"),
    ]
    assert captured["evidence_materialized"] == [
        (client, DOCUMENT_ID_1),
    ]
    assert captured["pending_kwargs"] == {
        "tender_id": TENDER_ID,
        "company_id": COMPANY_ID,
        "document_ids": [DOCUMENT_ID_1],
    }


def test_import_company_website_returns_preview_without_supabase_write(
    monkeypatch: Any,
) -> None:
    captured: dict[str, Any] = {}

    def record_import(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "source_url": "https://example.com/",
            "pages": [{"url": "https://example.com/", "title": "Example"}],
            "profile_patch": {"website": "https://example.com/"},
            "field_sources": {},
            "warnings": [],
        }

    monkeypatch.setattr(api_server, "import_company_website", record_import)

    result = api_server.import_company_website_route(
        api_server.CompanyWebsiteImportRequest(url="https://example.com"),
        user=AuthenticatedUser(user_id=USER_ID, email="user@example.com"),
    )

    assert result == {
        "source_url": "https://example.com/",
        "pages": [{"url": "https://example.com/", "title": "Example"}],
        "profile_patch": {"website": "https://example.com/"},
        "field_sources": {},
        "warnings": [],
    }
    assert captured["url"] == "https://example.com"
    assert captured["max_pages"] == 5


def test_import_company_website_maps_import_errors_to_http_422(
    monkeypatch: Any,
) -> None:
    def fail_import(**_kwargs: Any) -> dict[str, Any]:
        raise api_server.WebsiteImportError("URL host is private.")

    monkeypatch.setattr(api_server, "import_company_website", fail_import)

    try:
        api_server.import_company_website_route(
            api_server.CompanyWebsiteImportRequest(url="http://127.0.0.1"),
            user=AuthenticatedUser(user_id=USER_ID, email="user@example.com"),
        )
    except api_server.HTTPException as exc:
        assert exc.status_code == 422
        assert exc.detail == "URL host is private."
    else:
        raise AssertionError("Expected HTTPException")


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


def test_archive_run_endpoint_uses_service_role_archive_control(
    monkeypatch: Any,
) -> None:
    client = FakeSupabaseClient()
    settings = SimpleNamespace(
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="service-role",
    )
    captured: dict[str, Any] = {}

    monkeypatch.setattr(api_server, "load_settings", lambda: settings)
    monkeypatch.setitem(
        sys.modules,
        "supabase",
        SimpleNamespace(create_client=lambda _url, _key: client),
    )

    def record_archive(
        supabase_client: object,
        *,
        run_id: str,
        reason: str,
    ) -> SimpleNamespace:
        captured["client"] = supabase_client
        captured["run_id"] = run_id
        captured["reason"] = reason
        return SimpleNamespace(
            run_id=RUN_ID,
            archived_at="2026-04-19T10:30:00+00:00",
            already_archived=False,
        )

    monkeypatch.setattr(api_server, "archive_agent_run", record_archive)
    monkeypatch.setattr(
        api_server,
        "require_agent_run_admin",
        lambda *_args, **_kwargs: "00000000-0000-4000-8000-000000000001",
    )

    result = api_server.archive_run(
        RUN_ID,
        api_server.ArchiveRunRequest(reason="clear stale run"),
        user=AuthenticatedUser(user_id=USER_ID, email="user@example.com"),
    )

    assert result == {
        "run_id": RUN_ID,
        "archived_at": "2026-04-19T10:30:00+00:00",
        "already_archived": False,
    }
    assert captured == {
        "client": client,
        "run_id": RUN_ID,
        "reason": "clear stale run",
    }


def test_upload_company_kb_documents_registers_files_and_starts_ingestion(
    monkeypatch: Any,
) -> None:
    client = FakeSupabaseClient()
    settings = SimpleNamespace(
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="service-role",
        company_kb_storage_bucket="company-knowledge",
    )
    captured: dict[str, Any] = {"ingested": []}

    monkeypatch.setattr(api_server, "load_settings", lambda: settings)
    monkeypatch.setitem(
        sys.modules,
        "supabase",
        SimpleNamespace(create_client=lambda _url, _key: client),
    )
    monkeypatch.setattr(api_server.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(
        api_server,
        "require_company_admin",
        lambda *_args, **_kwargs: ORG_ID,
    )

    def record_register(
        supabase_client: object,
        **kwargs: Any,
    ) -> list[CompanyKbRegistrationResult]:
        captured["register_client"] = supabase_client
        captured["register_kwargs"] = kwargs
        return [
            CompanyKbRegistrationResult(
                company_id=UUID(COMPANY_ID),
                document_id=UUID(DOCUMENT_ID_1),
                storage_path="demo/company-knowledge/doc.txt",
                checksum_sha256="a" * 64,
                content_type="text/plain",
                original_filename="iso.txt",
                kb_document_type=CompanyKbDocumentType.CERTIFICATION,
            )
        ]

    def record_ingest(
        supabase_client: object,
        **kwargs: Any,
    ) -> None:
        captured["ingested"].append((supabase_client, kwargs))

    monkeypatch.setattr(api_server, "register_company_kb_documents", record_register)
    monkeypatch.setattr(api_server, "ingest_company_kb_document", record_ingest)
    api_server.app.dependency_overrides[api_server.require_authenticated_user] = (
        lambda: AuthenticatedUser(user_id=SUPERADMIN_ID, email="ops@bidded.se")
    )
    try:
        response = TestClient(api_server.app).post(
            "/api/company/kb/documents",
            data={"kb_document_types": "certification"},
            files={"files": ("iso.txt", b"ISO 27001", "text/plain")},
        )
    finally:
        api_server.app.dependency_overrides.clear()

    assert response.status_code == 200
    document = response.json()["documents"][0]
    assert document["document_id"] == DOCUMENT_ID_1
    assert document["parse_status"] == "pending"
    assert document["extraction_status"] == "pending"
    assert document["evidence_count"] == 0
    assert captured["register_client"] is client
    assert captured["register_kwargs"]["company_id"] == COMPANY_ID
    assert captured["register_kwargs"]["bucket_name"] == "company-knowledge"
    [upload_file] = captured["register_kwargs"]["files"]
    assert upload_file.filename == "iso.txt"
    assert upload_file.content == b"ISO 27001"
    assert upload_file.kb_document_type is CompanyKbDocumentType.CERTIFICATION
    assert captured["ingested"] == [
        (
            client,
            {
                "document_id": UUID(DOCUMENT_ID_1),
                "bucket_name": "company-knowledge",
            },
        )
    ]


def test_company_kb_list_evidence_and_delete_endpoints_call_backend(
    monkeypatch: Any,
) -> None:
    client = FakeSupabaseClient()
    settings = SimpleNamespace(
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="service-role",
        company_kb_storage_bucket="company-knowledge",
    )
    captured: dict[str, Any] = {}

    monkeypatch.setattr(api_server, "load_settings", lambda: settings)
    monkeypatch.setitem(
        sys.modules,
        "supabase",
        SimpleNamespace(create_client=lambda _url, _key: client),
    )
    monkeypatch.setattr(
        api_server,
        "require_company_member",
        lambda *_args, **_kwargs: ORG_ID,
    )
    monkeypatch.setattr(
        api_server,
        "require_company_admin",
        lambda *_args, **_kwargs: ORG_ID,
    )
    monkeypatch.setattr(
        api_server,
        "list_company_kb_documents",
        lambda supabase_client, *, company_id: [
            CompanyKbDocumentSummary(
                document_id=UUID(DOCUMENT_ID_1),
                company_id=UUID(company_id),
                original_filename="case.csv",
                storage_path="demo/company-knowledge/case.csv",
                content_type="text/csv",
                parse_status="parsed",
                kb_document_type=CompanyKbDocumentType.CASE_STUDY,
                extraction_status="extracted",
                evidence_count=2,
                warnings=(),
            )
        ],
    )
    monkeypatch.setattr(
        api_server,
        "list_company_kb_evidence",
        lambda supabase_client, *, company_id, document_id: [
            {
                "evidence_key": "COMPANY-KB-CASE",
                "excerpt": "Agency delivery case study.",
                "category": "reference",
                "confidence": 0.8,
            }
        ],
    )

    def record_delete(supabase_client: object, **kwargs: Any) -> None:
        captured["delete"] = (supabase_client, kwargs)

    monkeypatch.setattr(api_server, "delete_company_kb_document", record_delete)
    api_server.app.dependency_overrides[api_server.require_authenticated_user] = (
        lambda: AuthenticatedUser(user_id=SUPERADMIN_ID, email="ops@bidded.se")
    )
    try:
        test_client = TestClient(api_server.app)
        list_response = test_client.get("/api/company/kb/documents")
        evidence_response = test_client.get(
            f"/api/company/kb/documents/{DOCUMENT_ID_1}/evidence"
        )
        delete_response = test_client.delete(
            f"/api/company/kb/documents/{DOCUMENT_ID_1}"
        )
    finally:
        api_server.app.dependency_overrides.clear()

    assert list_response.status_code == 200
    assert list_response.json()["documents"][0]["evidence_count"] == 2
    assert evidence_response.status_code == 200
    assert evidence_response.json()["evidence"][0]["evidence_key"] == (
        "COMPANY-KB-CASE"
    )
    assert delete_response.status_code == 200
    assert captured["delete"] == (
        client,
        {
            "company_id": COMPANY_ID,
            "document_id": DOCUMENT_ID_1,
            "bucket_name": "company-knowledge",
        },
    )


def test_update_company_profile_endpoint_regenerates_company_evidence(
    monkeypatch: Any,
) -> None:
    client = FakeSupabaseClient()
    settings = SimpleNamespace(
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="service-role",
    )
    captured: dict[str, Any] = {}

    monkeypatch.setattr(api_server, "load_settings", lambda: settings)
    monkeypatch.setitem(
        sys.modules,
        "supabase",
        SimpleNamespace(create_client=lambda _url, _key: client),
    )
    monkeypatch.setattr(
        api_server,
        "require_company_admin",
        lambda *_args, **_kwargs: ORG_ID,
    )

    def record_update(
        supabase_client: object,
        *,
        company_id: str,
        profile_update: dict[str, Any],
    ) -> dict[str, Any]:
        captured["update"] = (supabase_client, company_id, profile_update)
        return {"id": company_id, "tenant_key": "demo", **profile_update}

    def record_evidence(
        supabase_client: object,
        *,
        company_id: UUID,
        company_profile: dict[str, Any],
    ) -> SimpleNamespace:
        captured["evidence"] = (supabase_client, company_id, company_profile)
        return SimpleNamespace(evidence_count=3)

    monkeypatch.setattr(api_server, "update_company_profile_row", record_update)
    monkeypatch.setattr(api_server, "upsert_company_profile_evidence", record_evidence)
    custom_company_id = "33333333-3333-4333-8333-333333333333"
    api_server.app.dependency_overrides[api_server.require_authenticated_user] = (
        lambda: AuthenticatedUser(user_id=SUPERADMIN_ID, email="ops@bidded.se")
    )
    try:
        response = TestClient(api_server.app).put(
            f"/api/company/profile?company_id={custom_company_id}",
            json={"name": "Nordic Digital Delivery AB", "certifications": []},
        )
    finally:
        api_server.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"company_id": custom_company_id, "evidence_count": 3}
    assert captured["update"] == (
        client,
        custom_company_id,
        {"name": "Nordic Digital Delivery AB", "certifications": []},
    )
    assert captured["evidence"][0] is client
    assert captured["evidence"][1] == UUID(custom_company_id)


def test_start_run_requires_bearer_token() -> None:
    client = TestClient(api_server.app)

    response = client.post("/api/runs/start", json={"tender_id": TENDER_ID})

    assert response.status_code == 401


def test_require_tender_member_allows_active_user_membership() -> None:
    client = FakeSupabaseClient()

    organization_id = api_server.require_tender_member(
        client,
        AuthenticatedUser(user_id=USER_ID, email="user@example.com"),
        TENDER_ID,
    )

    assert organization_id == ORG_ID


def test_require_company_admin_rejects_regular_user() -> None:
    client = FakeSupabaseClient()

    try:
        api_server.require_company_admin(
            client,
            AuthenticatedUser(user_id=USER_ID, email="user@example.com"),
            COMPANY_ID,
        )
    except api_server.HTTPException as exc:
        assert exc.status_code == 403
    else:  # pragma: no cover - assertion guard
        raise AssertionError("regular users must not resync company evidence")


def test_require_company_admin_allows_superadmin_without_membership() -> None:
    client = FakeSupabaseClient()

    organization_id = api_server.require_company_admin(
        client,
        AuthenticatedUser(user_id=SUPERADMIN_ID, email="ops@bidded.se"),
        COMPANY_ID,
    )

    assert organization_id == ORG_ID
