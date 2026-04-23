from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from bidded import api_server
from bidded.auth import AuthenticatedUser

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
            "companies": [
                {"id": COMPANY_ID, "tenant_key": "demo", "organization_id": ORG_ID}
            ],
            "tenders": [
                {"id": TENDER_ID, "tenant_key": "demo", "organization_id": ORG_ID}
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

    monkeypatch.setattr(api_server, "ingest_tender_pdf_document", record_ingestion)
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
