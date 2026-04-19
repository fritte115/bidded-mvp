from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from bidded.documents import ChunkEmbeddingAdapter, PdfIngestionError
from bidded.documents.pdf_ingestion import (
    DEFAULT_MAX_CHUNK_CHARS,
    ingest_tender_pdf_document,
)
from bidded.evidence.company_profile import upsert_company_profile_evidence
from bidded.evidence.contract_clause_classifier import ContractClauseClassifier
from bidded.evidence.tender_document import (
    build_tender_evidence_candidates,
    upsert_tender_evidence_items,
)
from bidded.orchestration.pending_run import (
    DEMO_TENANT_KEY,
    PendingRunContextResult,
    create_pending_run_context,
)
from bidded.orchestration.state import EvidenceSourceType
from bidded.retrieval import RetrievedDocumentChunk

DEFAULT_PREPARE_CREATED_VIA = "bidded_prepare_run"


class PrepareRunError(RuntimeError):
    """Raised when uploaded procurement documents cannot be prepared for agents."""


@dataclass(frozen=True)
class PreparedDocumentSummary:
    document_id: UUID
    parse_status: str
    chunk_count: int
    evidence_count: int


@dataclass(frozen=True)
class PrepareRunResult:
    tender_id: UUID
    company_id: UUID
    document_ids: tuple[UUID, ...]
    agent_run_id: UUID
    document_results: tuple[PreparedDocumentSummary, ...]
    tender_evidence_count: int
    company_evidence_count: int
    evidence_count: int
    warnings: tuple[str, ...]


def prepare_procurement_run(
    client: Any,
    *,
    tender_id: UUID | str,
    company_id: UUID | str,
    document_ids: Sequence[UUID | str],
    bucket_name: str,
    created_via: str = DEFAULT_PREPARE_CREATED_VIA,
    max_chunk_chars: int = DEFAULT_MAX_CHUNK_CHARS,
    embedding_adapter: ChunkEmbeddingAdapter | None = None,
    require_embeddings: bool = False,
    clause_classifier: ContractClauseClassifier | None = None,
    ingest_document: Callable[..., Any] = ingest_tender_pdf_document,
) -> PrepareRunResult:
    """Prepare an uploaded tender document set and create one pending run."""

    normalized_tender_id = _normalize_uuid(tender_id, "tender_id")
    normalized_company_id = _normalize_uuid(company_id, "company_id")
    normalized_document_ids = _normalize_document_ids(document_ids)

    _fetch_tender(client, normalized_tender_id)
    company_profile = _fetch_company_profile(client, normalized_company_id)
    document_rows = _fetch_and_validate_documents(
        client,
        tender_id=normalized_tender_id,
        document_ids=normalized_document_ids,
    )

    warnings: list[str] = []
    chunks_by_document: dict[UUID, list[RetrievedDocumentChunk]] = {}
    parse_status_by_document: dict[UUID, str] = {}
    for document_id in normalized_document_ids:
        document_row = document_rows[document_id]
        chunks = _fetch_document_chunks(client, document_id)
        parse_status = str(document_row.get("parse_status") or "")
        if parse_status != "parsed" or not chunks:
            if parse_status == "parser_failed":
                warnings.append(
                    f"Document {document_id} had parser_failed status; "
                    "preparation retried ingestion."
                )
            try:
                ingest_document(
                    client,
                    document_id=document_id,
                    bucket_name=bucket_name,
                    max_chunk_chars=max_chunk_chars,
                    embedding_adapter=embedding_adapter,
                    require_embeddings=require_embeddings,
                )
            except PdfIngestionError as exc:
                raise PrepareRunError(
                    f"Document {document_id} could not be parsed: {exc}"
                ) from exc

            document_row = _fetch_document(client, document_id)
            chunks = _fetch_document_chunks(client, document_id)
            parse_status = str(document_row.get("parse_status") or "")

        if parse_status != "parsed":
            raise PrepareRunError(
                f"Document {document_id} parse_status is {parse_status!r}; "
                "expected 'parsed' before creating an agent run."
            )
        if not chunks:
            raise PrepareRunError(
                f"Document {document_id} has no document_chunks after preparation."
            )

        chunks_by_document[document_id] = chunks
        parse_status_by_document[document_id] = parse_status

    all_chunks = [
        chunk
        for document_id in normalized_document_ids
        for chunk in chunks_by_document[document_id]
    ]
    tender_candidates = build_tender_evidence_candidates(all_chunks)
    tender_evidence = upsert_tender_evidence_items(
        client,
        tender_candidates,
        clause_classifier=clause_classifier,
    )
    company_evidence = upsert_company_profile_evidence(
        client,
        company_id=normalized_company_id,
        company_profile=company_profile,
    )
    pending_run = create_pending_run_context(
        client,
        tender_id=normalized_tender_id,
        company_id=normalized_company_id,
        document_ids=list(normalized_document_ids),
        created_via=created_via,
    )

    evidence_counts = Counter(candidate.document_id for candidate in tender_candidates)
    document_results = tuple(
        PreparedDocumentSummary(
            document_id=document_id,
            parse_status=parse_status_by_document[document_id],
            chunk_count=len(chunks_by_document[document_id]),
            evidence_count=evidence_counts[document_id],
        )
        for document_id in normalized_document_ids
    )
    return _prepare_result(
        tender_id=normalized_tender_id,
        company_id=normalized_company_id,
        document_ids=normalized_document_ids,
        pending_run=pending_run,
        document_results=document_results,
        tender_evidence_count=tender_evidence.evidence_count,
        company_evidence_count=company_evidence.evidence_count,
        warnings=tuple(warnings),
    )


def _prepare_result(
    *,
    tender_id: UUID,
    company_id: UUID,
    document_ids: tuple[UUID, ...],
    pending_run: PendingRunContextResult,
    document_results: tuple[PreparedDocumentSummary, ...],
    tender_evidence_count: int,
    company_evidence_count: int,
    warnings: tuple[str, ...],
) -> PrepareRunResult:
    return PrepareRunResult(
        tender_id=tender_id,
        company_id=company_id,
        document_ids=document_ids,
        agent_run_id=pending_run.run_id,
        document_results=document_results,
        tender_evidence_count=tender_evidence_count,
        company_evidence_count=company_evidence_count,
        evidence_count=tender_evidence_count + company_evidence_count,
        warnings=warnings,
    )


def _fetch_tender(client: Any, tender_id: UUID) -> dict[str, Any]:
    return _fetch_required_row(
        client,
        table_name="tenders",
        columns="id,tenant_key",
        filters={"id": str(tender_id), "tenant_key": DEMO_TENANT_KEY},
        missing_message=f"Demo tender does not exist: {tender_id}",
    )


def _fetch_company_profile(client: Any, company_id: UUID) -> dict[str, Any]:
    return _fetch_required_row(
        client,
        table_name="companies",
        columns=(
            "id,tenant_key,name,profile_label,organization_number,"
            "headquarters_country,employee_count,annual_revenue_sek,"
            "capabilities,certifications,reference_projects,"
            "financial_assumptions,profile_details,metadata"
        ),
        filters={"id": str(company_id), "tenant_key": DEMO_TENANT_KEY},
        missing_message=f"Demo company does not exist: {company_id}",
    )


def _fetch_and_validate_documents(
    client: Any,
    *,
    tender_id: UUID,
    document_ids: tuple[UUID, ...],
) -> dict[UUID, dict[str, Any]]:
    documents: dict[UUID, dict[str, Any]] = {}
    for document_id in document_ids:
        row = _fetch_document(client, document_id)
        if row.get("document_role") != EvidenceSourceType.TENDER_DOCUMENT.value:
            raise PrepareRunError(f"Document is not a tender_document: {document_id}")
        if str(row.get("tender_id")) != str(tender_id):
            raise PrepareRunError(
                f"Document {document_id} belongs to tender {row.get('tender_id')}; "
                f"expected {tender_id}."
            )
        documents[document_id] = row
    return documents


def _fetch_document(client: Any, document_id: UUID) -> dict[str, Any]:
    return _fetch_required_row(
        client,
        table_name="documents",
        columns=(
            "id,tenant_key,tender_id,company_id,document_role,parse_status,"
            "content_type,storage_path,original_filename,metadata"
        ),
        filters={"id": str(document_id), "tenant_key": DEMO_TENANT_KEY},
        missing_message=f"Tender document does not exist: {document_id}",
    )


def _fetch_document_chunks(
    client: Any,
    document_id: UUID,
) -> list[RetrievedDocumentChunk]:
    rows = _response_rows(
        client.table("document_chunks")
        .select(
            "id,tenant_key,document_id,page_start,page_end,chunk_index,text,metadata"
        )
        .eq("tenant_key", DEMO_TENANT_KEY)
        .eq("document_id", str(document_id))
        .execute()
    )
    chunks = [_retrieved_chunk_from_row(row) for row in rows]
    return sorted(chunks, key=lambda chunk: (chunk.chunk_index, chunk.chunk_id))


def _retrieved_chunk_from_row(row: Mapping[str, Any]) -> RetrievedDocumentChunk:
    return RetrievedDocumentChunk(
        chunk_id=str(row.get("id") or ""),
        document_id=_normalize_uuid(row.get("document_id"), "document_chunks.id"),
        page_start=_positive_int(row.get("page_start"), "page_start"),
        page_end=_positive_int(row.get("page_end"), "page_end"),
        chunk_index=_non_negative_int(row.get("chunk_index"), "chunk_index"),
        text=str(row.get("text") or ""),
        metadata=_mapping(row.get("metadata")),
    )


def _fetch_required_row(
    client: Any,
    *,
    table_name: str,
    columns: str,
    filters: Mapping[str, object],
    missing_message: str,
) -> dict[str, Any]:
    query = client.table(table_name).select(columns)
    for column, value in filters.items():
        query = query.eq(column, value)
    rows = _response_rows(query.execute())
    if rows:
        return dict(rows[0])
    raise PrepareRunError(missing_message)


def _response_rows(response: Any) -> list[Mapping[str, Any]]:
    data = getattr(response, "data", None)
    if not isinstance(data, list):
        raise PrepareRunError("Supabase query did not return a row list.")
    return [row for row in data if isinstance(row, Mapping)]


def _normalize_document_ids(document_ids: Sequence[UUID | str]) -> tuple[UUID, ...]:
    normalized = tuple(
        _normalize_uuid(document_id, "document_ids") for document_id in document_ids
    )
    if not normalized:
        raise PrepareRunError("At least one tender document ID is required.")
    if len(set(normalized)) != len(normalized):
        raise PrepareRunError("document_ids must not contain duplicates.")
    return normalized


def _normalize_uuid(value: Any, field_name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise PrepareRunError(f"{field_name} must be a UUID.") from exc


def _positive_int(value: object, field_name: str) -> int:
    parsed = _int_value(value, field_name)
    if parsed <= 0:
        raise PrepareRunError(f"{field_name} must be greater than zero.")
    return parsed


def _non_negative_int(value: object, field_name: str) -> int:
    parsed = _int_value(value, field_name)
    if parsed < 0:
        raise PrepareRunError(f"{field_name} must be non-negative.")
    return parsed


def _int_value(value: object, field_name: str) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError) as exc:
        raise PrepareRunError(f"{field_name} must be an integer.") from exc


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


__all__ = [
    "DEFAULT_PREPARE_CREATED_VIA",
    "PrepareRunError",
    "PrepareRunResult",
    "PreparedDocumentSummary",
    "prepare_procurement_run",
]
