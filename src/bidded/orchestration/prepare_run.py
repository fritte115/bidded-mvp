from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

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
_AUDIT_SEVERITY_ORDER = {"info": 0, "warning": 1, "error": 2}


class PrepareRunError(RuntimeError):
    """Raised when uploaded procurement documents cannot be prepared for agents."""

    def __init__(
        self,
        message: str,
        *,
        audit: PreparationAudit | None = None,
    ) -> None:
        super().__init__(message)
        self.audit = audit


class PreparationAuditIssue(BaseModel):
    """One deterministic preparation audit finding."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    severity: Literal["info", "warning", "error"]
    check: str = Field(min_length=1)
    message: str = Field(min_length=1)
    document_id: UUID | None = None
    company_id: UUID | None = None
    evidence_key: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class PreparationAudit(BaseModel):
    """Readable audit attached to a prepared pending run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_severity: Literal["info", "warning", "error"]
    issues: tuple[PreparationAuditIssue, ...] = ()

    @property
    def has_errors(self) -> bool:
        return self.max_severity == "error"

    @property
    def warnings(self) -> tuple[PreparationAuditIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "warning")

    @property
    def errors(self) -> tuple[PreparationAuditIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "error")


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
    audit: PreparationAudit


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
            audit = _document_preparation_error_audit(
                document_id=document_id,
                check="documents_parsed",
                message=(
                    f"Document {document_id} parse_status is {parse_status!r}; "
                    "expected 'parsed' before creating an agent run."
                ),
            )
            raise PrepareRunError(str(audit.errors[0].message), audit=audit)
        if not chunks:
            audit = _document_preparation_error_audit(
                document_id=document_id,
                check="document_chunks",
                message=(
                    f"Document {document_id} has no document_chunks after "
                    "preparation."
                ),
            )
            raise PrepareRunError(str(audit.errors[0].message), audit=audit)

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
    tender_evidence_rows = _fetch_evidence_rows_by_keys(
        client,
        source_type=EvidenceSourceType.TENDER_DOCUMENT.value,
        evidence_keys=tender_evidence.evidence_keys,
    )
    company_evidence_rows = _fetch_evidence_rows_by_keys(
        client,
        source_type=EvidenceSourceType.COMPANY_PROFILE.value,
        evidence_keys=company_evidence.evidence_keys,
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
    audit = _build_preparation_audit(
        company_id=normalized_company_id,
        document_ids=normalized_document_ids,
        document_results=document_results,
        tender_candidates=tender_candidates,
        tender_evidence_keys=tender_evidence.evidence_keys,
        tender_evidence_rows=tender_evidence_rows,
        tender_evidence_count=tender_evidence.evidence_count,
        company_evidence_keys=company_evidence.evidence_keys,
        company_evidence_rows=company_evidence_rows,
        company_evidence_count=company_evidence.evidence_count,
        warnings=tuple(warnings),
    )
    _raise_for_preparation_audit_errors(audit)
    pending_run = create_pending_run_context(
        client,
        tender_id=normalized_tender_id,
        company_id=normalized_company_id,
        document_ids=list(normalized_document_ids),
        created_via=created_via,
        metadata={"preparation_audit": audit.model_dump(mode="json")},
    )
    return _prepare_result(
        tender_id=normalized_tender_id,
        company_id=normalized_company_id,
        document_ids=normalized_document_ids,
        pending_run=pending_run,
        document_results=document_results,
        tender_evidence_count=tender_evidence.evidence_count,
        company_evidence_count=company_evidence.evidence_count,
        warnings=tuple(issue.message for issue in audit.warnings),
        audit=audit,
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
    audit: PreparationAudit,
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
        audit=audit,
    )


def _build_preparation_audit(
    *,
    company_id: UUID,
    document_ids: tuple[UUID, ...],
    document_results: tuple[PreparedDocumentSummary, ...],
    tender_candidates: Sequence[Any],
    tender_evidence_keys: Sequence[str],
    tender_evidence_rows: Sequence[Mapping[str, Any]],
    tender_evidence_count: int,
    company_evidence_keys: Sequence[str],
    company_evidence_rows: Sequence[Mapping[str, Any]],
    company_evidence_count: int,
    warnings: tuple[str, ...],
) -> PreparationAudit:
    selected_document_ids = set(document_ids)
    issues: list[PreparationAuditIssue] = []

    for warning in warnings:
        issues.append(
            PreparationAuditIssue(
                severity="warning",
                check="document_ingestion",
                message=warning,
            )
        )

    unparsed_documents = [
        summary for summary in document_results if summary.parse_status != "parsed"
    ]
    if unparsed_documents:
        for summary in unparsed_documents:
            issues.append(
                PreparationAuditIssue(
                    severity="error",
                    check="documents_parsed",
                    document_id=summary.document_id,
                    message=(
                        f"Document {summary.document_id} parse_status is "
                        f"{summary.parse_status!r}; expected 'parsed'."
                    ),
                )
            )
    else:
        issues.append(
            PreparationAuditIssue(
                severity="info",
                check="documents_parsed",
                message="All selected tender documents are parsed.",
                details={"document_count": len(document_results)},
            )
        )

    documents_without_chunks = [
        summary for summary in document_results if summary.chunk_count == 0
    ]
    if documents_without_chunks:
        for summary in documents_without_chunks:
            issues.append(
                PreparationAuditIssue(
                    severity="error",
                    check="document_chunks",
                    document_id=summary.document_id,
                    message=f"Document {summary.document_id} has no chunks.",
                )
            )
    else:
        issues.append(
            PreparationAuditIssue(
                severity="info",
                check="document_chunks",
                message="All selected tender documents have chunks.",
                details={
                    "chunk_count": sum(
                        summary.chunk_count for summary in document_results
                    )
                },
            )
        )

    documents_without_tender_evidence = [
        summary for summary in document_results if summary.evidence_count == 0
    ]
    if documents_without_tender_evidence:
        for summary in documents_without_tender_evidence:
            issues.append(
                PreparationAuditIssue(
                    severity="warning",
                    check="tender_evidence",
                    document_id=summary.document_id,
                    message=(
                        f"Document {summary.document_id} produced no tender "
                        "evidence items; agents will rely on chunks and other "
                        "evidence for this document."
                    ),
                )
            )
    else:
        issues.append(
            PreparationAuditIssue(
                severity="info",
                check="tender_evidence",
                message="Tender evidence exists for every selected document.",
                details={"tender_evidence_count": tender_evidence_count},
            )
        )

    if company_evidence_count <= 0:
        issues.append(
            PreparationAuditIssue(
                severity="error",
                check="company_evidence",
                company_id=company_id,
                message=f"Company {company_id} produced no company profile evidence.",
            )
        )
    else:
        issues.append(
            PreparationAuditIssue(
                severity="info",
                check="company_evidence",
                company_id=company_id,
                message="Company profile evidence exists for the selected company.",
                details={"company_evidence_count": company_evidence_count},
            )
        )

    provenance_errors = _evidence_provenance_errors(
        company_id=company_id,
        document_ids=selected_document_ids,
        tender_evidence_keys=tender_evidence_keys,
        tender_evidence_rows=tender_evidence_rows,
        company_evidence_keys=company_evidence_keys,
        company_evidence_rows=company_evidence_rows,
    )
    stale_candidates = [
        candidate
        for candidate in tender_candidates
        if getattr(candidate, "document_id", None) not in selected_document_ids
    ]
    for candidate in stale_candidates:
        provenance_errors.append(
            PreparationAuditIssue(
                severity="error",
                check="evidence_provenance",
                document_id=getattr(candidate, "document_id", None),
                message=(
                    "Tender evidence candidate points outside the selected "
                    f"document set: {getattr(candidate, 'document_id', None)}."
                ),
            )
        )
    if provenance_errors:
        issues.extend(provenance_errors)
    else:
        issues.append(
            PreparationAuditIssue(
                severity="info",
                check="evidence_provenance",
                message=(
                    "Prepared tender evidence provenance points to selected "
                    "documents and company evidence points to the selected company."
                ),
                details={
                    "document_ids": [str(document_id) for document_id in document_ids],
                    "company_id": str(company_id),
                },
            )
        )

    typed_requirement_count = sum(
        1
        for row in tender_evidence_rows
        if row.get("requirement_type") is not None
    )
    issues.append(
        PreparationAuditIssue(
            severity="info",
            check="requirement_types",
            message=(
                "Requirement types are present on detected tender evidence."
                if typed_requirement_count
                else "No requirement types were detected in prepared tender evidence."
            ),
            details={"typed_tender_evidence_count": typed_requirement_count},
        )
    )

    return _preparation_audit(issues)


def _document_preparation_error_audit(
    *,
    document_id: UUID,
    check: Literal["documents_parsed", "document_chunks"],
    message: str,
) -> PreparationAudit:
    return _preparation_audit(
        [
            PreparationAuditIssue(
                severity="error",
                check=check,
                document_id=document_id,
                message=message,
            )
        ]
    )


def _evidence_provenance_errors(
    *,
    company_id: UUID,
    document_ids: set[UUID],
    tender_evidence_keys: Sequence[str],
    tender_evidence_rows: Sequence[Mapping[str, Any]],
    company_evidence_keys: Sequence[str],
    company_evidence_rows: Sequence[Mapping[str, Any]],
) -> list[PreparationAuditIssue]:
    issues: list[PreparationAuditIssue] = []
    tender_rows_by_key = {
        str(row.get("evidence_key")): row for row in tender_evidence_rows
    }
    company_rows_by_key = {
        str(row.get("evidence_key")): row for row in company_evidence_rows
    }

    for evidence_key in sorted(
        set(tender_evidence_keys).difference(tender_rows_by_key)
    ):
        issues.append(
            PreparationAuditIssue(
                severity="error",
                check="evidence_provenance",
                evidence_key=evidence_key,
                message=(
                    f"Tender evidence {evidence_key} was not readable after upsert."
                ),
            )
        )

    for evidence_key, row in sorted(tender_rows_by_key.items()):
        row_document_id = _optional_uuid(row.get("document_id"))
        if row_document_id not in document_ids:
            issues.append(
                PreparationAuditIssue(
                    severity="error",
                    check="evidence_provenance",
                    document_id=row_document_id,
                    evidence_key=evidence_key,
                    message=(
                        f"Tender evidence {evidence_key} points to document "
                        f"{row_document_id}; expected one of the selected documents."
                    ),
                )
            )

    for evidence_key in sorted(
        set(company_evidence_keys).difference(company_rows_by_key)
    ):
        issues.append(
            PreparationAuditIssue(
                severity="error",
                check="evidence_provenance",
                evidence_key=evidence_key,
                message=(
                    f"Company evidence {evidence_key} was not readable after upsert."
                ),
            )
        )

    for evidence_key, row in sorted(company_rows_by_key.items()):
        row_company_id = _optional_uuid(row.get("company_id"))
        if row_company_id != company_id:
            issues.append(
                PreparationAuditIssue(
                    severity="error",
                    check="evidence_provenance",
                    company_id=row_company_id,
                    evidence_key=evidence_key,
                    message=(
                        f"Company evidence {evidence_key} points to company "
                        f"{row_company_id}; expected {company_id}."
                    ),
                )
            )

    return issues


def _raise_for_preparation_audit_errors(audit: PreparationAudit) -> None:
    if not audit.has_errors:
        return
    error_checks = {issue.check for issue in audit.errors}
    if "company_evidence" in error_checks:
        message = "Company evidence audit failed."
    elif "evidence_provenance" in error_checks:
        message = "Evidence provenance audit failed."
    else:
        message = "Preparation input audit failed."
    raise PrepareRunError(message, audit=audit)


def _preparation_audit(
    issues: Sequence[PreparationAuditIssue],
) -> PreparationAudit:
    max_severity = max(
        (issue.severity for issue in issues),
        key=lambda severity: _AUDIT_SEVERITY_ORDER[severity],
        default="info",
    )
    return PreparationAudit(max_severity=max_severity, issues=tuple(issues))


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


def _fetch_evidence_rows_by_keys(
    client: Any,
    *,
    source_type: str,
    evidence_keys: Sequence[str],
) -> tuple[dict[str, Any], ...]:
    expected_keys = set(evidence_keys)
    if not expected_keys:
        return ()

    rows = _response_rows(
        client.table("evidence_items")
        .select(
            "id,tenant_key,evidence_key,source_type,document_id,company_id,"
            "chunk_id,page_start,page_end,field_path,requirement_type"
        )
        .eq("tenant_key", DEMO_TENANT_KEY)
        .eq("source_type", source_type)
        .execute()
    )
    return tuple(
        sorted(
            (
                dict(row)
                for row in rows
                if str(row.get("evidence_key")) in expected_keys
            ),
            key=lambda row: str(row.get("evidence_key") or ""),
        )
    )


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


def _optional_uuid(value: Any) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


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
    "PreparationAudit",
    "PreparationAuditIssue",
    "PrepareRunError",
    "PrepareRunResult",
    "PreparedDocumentSummary",
    "prepare_procurement_run",
]
