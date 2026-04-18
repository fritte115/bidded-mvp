from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from bidded.orchestration.state import (
    AgentRunStatus,
    EvidenceSourceType,
    GraphNodeName,
    SpecialistRole,
)

DEMO_TENANT_KEY = "demo"
DEFAULT_CREATED_VIA = "bidded_cli"


class PendingRunContextError(RuntimeError):
    """Raised when a pending agent run cannot be created."""


class SupabaseRunQuery(Protocol):
    def select(self, columns: str) -> SupabaseRunQuery: ...

    def eq(self, column: str, value: object) -> SupabaseRunQuery: ...

    def insert(self, payload: dict[str, Any]) -> SupabaseRunQuery: ...

    def execute(self) -> Any: ...


class SupabaseRunContextClient(Protocol):
    def table(self, table_name: str) -> SupabaseRunQuery: ...


@dataclass(frozen=True)
class PendingRunContextResult:
    run_id: UUID
    tender_id: UUID
    company_id: UUID
    document_ids: list[UUID]
    run_config: dict[str, Any]


def create_pending_run_context(
    client: SupabaseRunContextClient,
    *,
    tender_id: UUID | str,
    company_id: UUID | str,
    document_id: UUID | str,
    created_via: str = DEFAULT_CREATED_VIA,
) -> PendingRunContextResult:
    """Validate target rows and create a pending Supabase agent run."""

    normalized_tender_id = _normalize_uuid(tender_id, "tender_id")
    normalized_company_id = _normalize_uuid(company_id, "company_id")
    normalized_document_id = _normalize_uuid(document_id, "document_id")

    _require_row(
        client,
        table_name="companies",
        columns="id",
        filters={
            "id": str(normalized_company_id),
            "tenant_key": DEMO_TENANT_KEY,
        },
        missing_message=f"Demo company does not exist: {normalized_company_id}",
    )
    _require_row(
        client,
        table_name="tenders",
        columns="id",
        filters={
            "id": str(normalized_tender_id),
            "tenant_key": DEMO_TENANT_KEY,
        },
        missing_message=f"Demo tender does not exist: {normalized_tender_id}",
    )
    _require_row(
        client,
        table_name="documents",
        columns="id",
        filters={
            "id": str(normalized_document_id),
            "tenant_key": DEMO_TENANT_KEY,
            "tender_id": str(normalized_tender_id),
            "document_role": EvidenceSourceType.TENDER_DOCUMENT.value,
        },
        missing_message=(
            "Tender procurement document does not exist for tender "
            f"{normalized_tender_id}: {normalized_document_id}"
        ),
    )

    document_ids = [normalized_document_id]
    run_config = build_pending_run_config(document_ids=document_ids)
    payload: dict[str, Any] = {
        "tenant_key": DEMO_TENANT_KEY,
        "tender_id": str(normalized_tender_id),
        "company_id": str(normalized_company_id),
        "status": AgentRunStatus.PENDING.value,
        "run_config": run_config,
        "metadata": {
            "created_via": created_via,
            "document_ids": [str(document_id) for document_id in document_ids],
        },
    }
    response = client.table("agent_runs").insert(payload).execute()
    run_id = _first_returned_id(response, "agent_runs")

    return PendingRunContextResult(
        run_id=run_id,
        tender_id=normalized_tender_id,
        company_id=normalized_company_id,
        document_ids=document_ids,
        run_config=run_config,
    )


def build_pending_run_config(*, document_ids: list[UUID]) -> dict[str, Any]:
    """Return the deterministic default run config for a Bidded v1 run."""

    return {
        "language_policy": {
            "input_language": "en",
            "output_language": "en",
        },
        "procurement_context": {
            "jurisdiction": "SE",
            "market": "Swedish public procurement",
            "procedure_family": "public_procurement",
        },
        "active_agent_roles": [
            GraphNodeName.EVIDENCE_SCOUT.value,
            SpecialistRole.COMPLIANCE.value,
            SpecialistRole.WIN_STRATEGIST.value,
            SpecialistRole.DELIVERY_CFO.value,
            SpecialistRole.RED_TEAM.value,
            GraphNodeName.JUDGE.value,
        ],
        "evidence_lock": {
            "enabled": True,
            "allowed_source_types": [
                EvidenceSourceType.TENDER_DOCUMENT.value,
                EvidenceSourceType.COMPANY_PROFILE.value,
            ],
            "require_material_claim_evidence": True,
            "allow_new_external_sources": False,
        },
        "document_ids": [str(document_id) for document_id in document_ids],
    }


def _require_row(
    client: SupabaseRunContextClient,
    *,
    table_name: str,
    columns: str,
    filters: Mapping[str, object],
    missing_message: str,
) -> dict[str, Any]:
    query = client.table(table_name).select(columns)
    for column, value in filters.items():
        query = query.eq(column, value)

    data = getattr(query.execute(), "data", None)
    if isinstance(data, list) and data and isinstance(data[0], Mapping):
        return dict(data[0])

    raise PendingRunContextError(missing_message)


def _first_returned_id(response: Any, table_name: str) -> UUID:
    data = getattr(response, "data", None)
    if isinstance(data, list) and data and isinstance(data[0], Mapping):
        row_id = data[0].get("id")
        if row_id:
            return _normalize_uuid(row_id, f"{table_name}.id")

    raise PendingRunContextError(
        f"Supabase {table_name} insert did not return a row id."
    )


def _normalize_uuid(value: UUID | str, field_name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except ValueError as exc:
        raise PendingRunContextError(f"{field_name} must be a UUID.") from exc


__all__ = [
    "PendingRunContextError",
    "PendingRunContextResult",
    "build_pending_run_config",
    "create_pending_run_context",
]
