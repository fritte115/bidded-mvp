from __future__ import annotations

from collections.abc import Mapping, Sequence
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
    document_id: UUID | str | None = None,
    document_ids: Sequence[UUID | str] | None = None,
    created_via: str = DEFAULT_CREATED_VIA,
    metadata: Mapping[str, Any] | None = None,
) -> PendingRunContextResult:
    """Validate target rows and create a pending Supabase agent run."""

    normalized_tender_id = _normalize_uuid(tender_id, "tender_id")
    normalized_company_id = _normalize_uuid(company_id, "company_id")
    normalized_document_ids = _normalize_document_ids(
        document_id=document_id,
        document_ids=document_ids,
    )

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
    for normalized_document_id in normalized_document_ids:
        document_row = _require_row(
            client,
            table_name="documents",
            columns="id,parse_status",
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
        _require_parsed_document(document_row, normalized_document_id)

    run_config = build_pending_run_config(document_ids=normalized_document_ids)
    run_metadata: dict[str, Any] = {
        "created_via": created_via,
        "document_ids": [str(document_id) for document_id in normalized_document_ids],
    }
    if metadata:
        run_metadata.update(dict(metadata))
    payload: dict[str, Any] = {
        "tenant_key": DEMO_TENANT_KEY,
        "tender_id": str(normalized_tender_id),
        "company_id": str(normalized_company_id),
        "status": AgentRunStatus.PENDING.value,
        "run_config": run_config,
        "metadata": run_metadata,
    }
    response = client.table("agent_runs").insert(payload).execute()
    run_id = _first_returned_id(response, "agent_runs")

    return PendingRunContextResult(
        run_id=run_id,
        tender_id=normalized_tender_id,
        company_id=normalized_company_id,
        document_ids=list(normalized_document_ids),
        run_config=run_config,
    )


def build_pending_run_config(*, document_ids: Sequence[UUID]) -> dict[str, Any]:
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


def _require_parsed_document(
    row: Mapping[str, Any],
    document_id: UUID,
) -> None:
    parse_status = str(row.get("parse_status") or "")
    if parse_status != "parsed":
        raise PendingRunContextError(
            "Tender procurement document must be a parsed tender document before "
            f"creating a pending run: {document_id} has parse_status "
            f"{parse_status!r}."
        )


def _normalize_uuid(value: UUID | str, field_name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except ValueError as exc:
        raise PendingRunContextError(f"{field_name} must be a UUID.") from exc


def _normalize_document_ids(
    *,
    document_id: UUID | str | None,
    document_ids: Sequence[UUID | str] | None,
) -> tuple[UUID, ...]:
    if document_id is not None and document_ids is not None:
        raise PendingRunContextError(
            "Use either document_id or document_ids, not both."
        )

    raw_document_ids: Sequence[UUID | str]
    if document_ids is not None:
        raw_document_ids = document_ids
    elif document_id is not None:
        raw_document_ids = [document_id]
    else:
        raise PendingRunContextError("At least one tender document ID is required.")

    normalized = tuple(
        _normalize_uuid(raw_document_id, "document_ids")
        for raw_document_id in raw_document_ids
    )
    if not normalized:
        raise PendingRunContextError("At least one tender document ID is required.")
    if len(set(normalized)) != len(normalized):
        raise PendingRunContextError("document_ids must not contain duplicates.")
    return normalized


__all__ = [
    "PendingRunContextError",
    "PendingRunContextResult",
    "build_pending_run_config",
    "create_pending_run_context",
]
