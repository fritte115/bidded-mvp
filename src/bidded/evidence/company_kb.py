from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Protocol
from uuid import UUID

from bidded.retrieval import RetrievedDocumentChunk, list_document_chunks_for_document

DEMO_TENANT_KEY = "demo"
ATTACHMENT_TYPES = {
    "certificate",
    "cv",
    "reference_case",
    "policy_document",
    "pricing_document",
    "other",
}


class SupabaseCompanyKbQuery(Protocol):
    def select(self, columns: str) -> SupabaseCompanyKbQuery: ...

    def eq(self, column: str, value: object) -> SupabaseCompanyKbQuery: ...

    def execute(self) -> Any: ...


class SupabaseCompanyKbEvidenceTable(Protocol):
    def upsert(
        self,
        payload: list[dict[str, Any]],
        *,
        on_conflict: str | None = None,
    ) -> Any: ...


class SupabaseCompanyKbClient(Protocol):
    def table(
        self,
        table_name: str,
    ) -> SupabaseCompanyKbQuery | SupabaseCompanyKbEvidenceTable: ...


@dataclass(frozen=True)
class CompanyKbEvidenceUpsertResult:
    evidence_count: int
    evidence_keys: tuple[str, ...]
    rows_returned: int


def ensure_company_kb_evidence_items_for_document(
    client: SupabaseCompanyKbClient,
    *,
    document_id: UUID | str,
    tenant_key: str = DEMO_TENANT_KEY,
) -> CompanyKbEvidenceUpsertResult:
    """Materialize company_profile evidence from one approved company KB PDF."""

    document_row = _fetch_company_document(
        client,
        document_id=_normalize_uuid(document_id),
        tenant_key=tenant_key,
    )
    chunks = list_document_chunks_for_document(
        client,
        document_id=document_row["id"],
        tenant_key=tenant_key,
    )
    evidence_items = build_company_kb_evidence_items(
        document_row=document_row,
        chunks=chunks,
        tenant_key=tenant_key,
    )
    return upsert_company_kb_evidence_items(
        client,
        evidence_items,
    )


def build_company_kb_evidence_items(
    *,
    document_row: Mapping[str, Any],
    chunks: Sequence[RetrievedDocumentChunk],
    tenant_key: str = DEMO_TENANT_KEY,
) -> list[dict[str, Any]]:
    company_id = str(document_row.get("company_id") or "")
    document_id = str(document_row.get("id") or "")
    if not company_id or not document_id:
        return []

    metadata = _mapping(document_row.get("metadata"))
    source_label = _source_label(document_row)
    attachment_type = infer_attachment_type(
        " ".join(
            [
                source_label,
                str(document_row.get("original_filename") or ""),
                str(metadata.get("kb_attachment_type") or ""),
            ]
        )
    )
    category = _category_for_attachment_type(attachment_type)

    items: list[dict[str, Any]] = []
    for chunk in chunks:
        excerpt = _excerpt(chunk.text)
        if not excerpt:
            continue
        evidence_key = _evidence_key(
            document_id=document_id,
            source_label=source_label,
            chunk=chunk,
            excerpt=excerpt,
        )
        items.append(
            {
                "tenant_key": tenant_key,
                "evidence_key": evidence_key,
                "source_type": "company_profile",
                "excerpt": excerpt,
                "normalized_meaning": (
                    f"Company KB document '{source_label}' contains supporting "
                    f"{attachment_type.replace('_', ' ')} evidence."
                ),
                "category": category,
                "confidence": 0.86,
                "source_metadata": {
                    "source_label": source_label,
                    "source_document_id": document_id,
                },
                "company_id": company_id,
                "field_path": f"kb_documents.{document_id}.chunks[{chunk.chunk_index}]",
                "metadata": {
                    "source": "company_kb_pdf",
                    "attachment_type": attachment_type,
                    "source_document_id": document_id,
                    "source_chunk_id": chunk.chunk_id,
                    "source_storage_path": document_row.get("storage_path"),
                    "source_original_filename": document_row.get("original_filename"),
                    "page_start": chunk.page_start,
                    "page_end": chunk.page_end,
                    "approved_for_bid_drafts": bool(
                        metadata.get("approved_for_bid_drafts", True)
                    ),
                },
            }
        )
    return items


def upsert_company_kb_evidence_items(
    client: SupabaseCompanyKbClient,
    evidence_items: Sequence[Mapping[str, Any]],
) -> CompanyKbEvidenceUpsertResult:
    payload = [dict(item) for item in evidence_items]
    if not payload:
        return CompanyKbEvidenceUpsertResult(
            evidence_count=0,
            evidence_keys=(),
            rows_returned=0,
        )

    response = (
        client.table("evidence_items")
        .upsert(payload, on_conflict="tenant_key,evidence_key")
        .execute()
    )
    data = getattr(response, "data", [])
    rows_returned = len(data) if isinstance(data, list) else 0
    return CompanyKbEvidenceUpsertResult(
        evidence_count=len(payload),
        evidence_keys=tuple(str(item["evidence_key"]) for item in payload),
        rows_returned=rows_returned,
    )


def infer_attachment_type(text: str) -> str:
    lowered = _ascii_lower(text)
    if any(term in lowered for term in ("certifikat", "certificate", "iso 27001")):
        return "certificate"
    if any(term in lowered for term in ("cv", "resume", "curriculum", "nyckelperson")):
        return "cv"
    if any(term in lowered for term in ("reference", "referens", "case study")):
        return "reference_case"
    if any(term in lowered for term in ("price", "pricing", "pris", "rate card")):
        return "pricing_document"
    if any(term in lowered for term in ("policy", "rutin", "dpa", "gdpr")):
        return "policy_document"
    return "other"


def _fetch_company_document(
    client: SupabaseCompanyKbClient,
    *,
    document_id: UUID,
    tenant_key: str,
) -> dict[str, Any]:
    response = (
        client.table("documents")
        .select(
            "id,tenant_key,company_id,storage_path,content_type,document_role,"
            "parse_status,original_filename,metadata,checksum_sha256"
        )
        .eq("id", str(document_id))
        .eq("tenant_key", tenant_key)
        .execute()
    )
    data = getattr(response, "data", None)
    if not isinstance(data, list) or not data or not isinstance(data[0], Mapping):
        raise ValueError(f"Company KB document does not exist: {document_id}")
    row = dict(data[0])
    if row.get("document_role") != "company_profile":
        raise ValueError(f"Document is not a company_profile document: {document_id}")
    return row


def _source_label(document_row: Mapping[str, Any]) -> str:
    metadata = _mapping(document_row.get("metadata"))
    source_label = metadata.get("source_label")
    if isinstance(source_label, str) and source_label.strip():
        return source_label.strip()
    filename = document_row.get("original_filename")
    if isinstance(filename, str) and filename.strip():
        return filename.strip()
    return "company KB PDF"


def _category_for_attachment_type(attachment_type: str) -> str:
    return {
        "certificate": "certification",
        "cv": "cv_summary",
        "reference_case": "reference",
        "pricing_document": "economics",
        "policy_document": "policy_document",
    }.get(attachment_type, "company_kb")


def _evidence_key(
    *,
    document_id: str,
    source_label: str,
    chunk: RetrievedDocumentChunk,
    excerpt: str,
) -> str:
    digest = sha256(
        "|".join(
            [
                document_id,
                chunk.chunk_id,
                str(chunk.page_start),
                str(chunk.chunk_index),
                excerpt,
            ]
        ).encode("utf-8")
    ).hexdigest()[:8]
    return (
        f"COMPANY-KB-{_slug(source_label)}-P{chunk.page_start}-"
        f"C{chunk.chunk_index}-{digest.upper()}"
    )


def _excerpt(text: str, *, limit: int = 600) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "..."


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").upper()
    return slug or "UNKNOWN"


def _ascii_lower(value: str) -> str:
    return value.casefold().replace("å", "a").replace("ä", "a").replace("ö", "o")


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _normalize_uuid(value: UUID | str) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


__all__ = [
    "ATTACHMENT_TYPES",
    "CompanyKbEvidenceUpsertResult",
    "build_company_kb_evidence_items",
    "ensure_company_kb_evidence_items_for_document",
    "infer_attachment_type",
    "upsert_company_kb_evidence_items",
]
