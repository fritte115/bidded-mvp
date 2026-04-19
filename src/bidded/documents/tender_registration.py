from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from bidded.db.seed_demo_company import build_demo_company_payload


class TenderPdfRegistrationError(RuntimeError):
    """Raised when a local tender PDF cannot be registered."""


class SupabaseUpsertQuery(Protocol):
    def execute(self) -> Any: ...


class SupabaseTable(Protocol):
    def upsert(
        self,
        payload: dict[str, Any],
        *,
        on_conflict: str | None = None,
    ) -> SupabaseUpsertQuery: ...


class SupabaseStorageBucket(Protocol):
    def upload(
        self,
        path: str,
        file: bytes,
        *,
        file_options: dict[str, str] | None = None,
    ) -> Any: ...


class SupabaseStorage(Protocol):
    def from_(self, bucket_name: str) -> SupabaseStorageBucket: ...


class SupabaseTenderRegistrationClient(Protocol):
    storage: SupabaseStorage

    def table(self, table_name: str) -> SupabaseTable: ...


@dataclass(frozen=True)
class TenderPdfRegistrationResult:
    company_id: str
    tender_id: str
    document_id: str
    storage_path: str
    checksum_sha256: str
    content_type: str
    original_filename: str


def register_demo_tender_pdf(
    client: SupabaseTenderRegistrationClient,
    *,
    pdf_path: Path,
    bucket_name: str,
    tender_title: str,
    issuing_authority: str,
    procurement_reference: str | None = None,
    procurement_metadata: Mapping[str, Any] | None = None,
    source_label: str = "registered tender PDF",
    procurement_document_role: str | None = None,
    created_via: str = "bidded_cli",
) -> TenderPdfRegistrationResult:
    """Upload a local PDF and register it as the demo tender document."""
    path = Path(pdf_path)
    pdf_bytes = _read_valid_pdf(path)
    checksum_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    storage_path = _storage_path(
        title=tender_title,
        checksum_sha256=checksum_sha256,
        original_filename=path.name,
    )

    company_id = _upsert_demo_company(client)
    tender_id = _upsert_tender(
        client,
        tender_title=tender_title,
        issuing_authority=issuing_authority,
        procurement_reference=procurement_reference,
        procurement_metadata=dict(procurement_metadata or {}),
        demo_company_id=company_id,
        created_via=created_via,
    )
    client.storage.from_(bucket_name).upload(
        storage_path,
        pdf_bytes,
        file_options={"content-type": "application/pdf", "upsert": "true"},
    )
    document_id = _upsert_tender_document(
        client,
        tender_id=tender_id,
        demo_company_id=company_id,
        storage_path=storage_path,
        checksum_sha256=checksum_sha256,
        original_filename=path.name,
        source_label=source_label,
        procurement_document_role=procurement_document_role,
        created_via=created_via,
    )

    return TenderPdfRegistrationResult(
        company_id=company_id,
        tender_id=tender_id,
        document_id=document_id,
        storage_path=storage_path,
        checksum_sha256=checksum_sha256,
        content_type="application/pdf",
        original_filename=path.name,
    )


def _read_valid_pdf(path: Path) -> bytes:
    if not path.exists():
        raise TenderPdfRegistrationError(f"PDF file does not exist: {path}")
    if not path.is_file():
        raise TenderPdfRegistrationError(f"PDF path is not a file: {path}")
    if path.suffix.lower() != ".pdf":
        raise TenderPdfRegistrationError(f"Input file is not a PDF: {path}")

    pdf_bytes = path.read_bytes()
    if not pdf_bytes.startswith(b"%PDF-"):
        raise TenderPdfRegistrationError(f"Input file is not a PDF: {path}")
    return pdf_bytes


def _upsert_demo_company(client: SupabaseTenderRegistrationClient) -> str:
    response = (
        client.table("companies")
        .upsert(build_demo_company_payload(), on_conflict="tenant_key,name")
        .execute()
    )
    return _first_returned_id(response, "companies")


def _upsert_tender(
    client: SupabaseTenderRegistrationClient,
    *,
    tender_title: str,
    issuing_authority: str,
    procurement_reference: str | None,
    procurement_metadata: dict[str, Any],
    demo_company_id: str,
    created_via: str,
) -> str:
    payload: dict[str, Any] = {
        "tenant_key": "demo",
        "title": tender_title,
        "issuing_authority": issuing_authority,
        "procurement_reference": procurement_reference,
        "procurement_context": procurement_metadata,
        "language_policy": {
            "source_document_language": "sv",
            "agent_output_language": "en",
        },
        "metadata": {
            "registered_via": created_via,
            "demo_company_id": demo_company_id,
        },
    }
    response = (
        client.table("tenders")
        .upsert(payload, on_conflict="tenant_key,title,issuing_authority")
        .execute()
    )
    return _first_returned_id(response, "tenders")


def _upsert_tender_document(
    client: SupabaseTenderRegistrationClient,
    *,
    tender_id: str,
    demo_company_id: str,
    storage_path: str,
    checksum_sha256: str,
    original_filename: str,
    source_label: str,
    procurement_document_role: str | None,
    created_via: str,
) -> str:
    metadata: dict[str, Any] = {
        "registered_via": created_via,
        "source_label": source_label.strip() or "registered tender PDF",
        "demo_company_id": demo_company_id,
    }
    if procurement_document_role is not None:
        metadata["procurement_document_role"] = procurement_document_role
    payload: dict[str, Any] = {
        "tenant_key": "demo",
        "tender_id": tender_id,
        "company_id": None,
        "storage_path": storage_path,
        "checksum_sha256": checksum_sha256,
        "content_type": "application/pdf",
        "document_role": "tender_document",
        "parse_status": "pending",
        "original_filename": original_filename,
        "metadata": metadata,
    }
    response = (
        client.table("documents")
        .upsert(payload, on_conflict="storage_path")
        .execute()
    )
    return _first_returned_id(response, "documents")


def _first_returned_id(response: Any, table_name: str) -> str:
    data = getattr(response, "data", None)
    if isinstance(data, list) and data and isinstance(data[0], Mapping):
        row_id = data[0].get("id")
        if row_id:
            return str(row_id)

    raise TenderPdfRegistrationError(
        f"Supabase {table_name} upsert did not return a row id."
    )


def _storage_path(
    *,
    title: str,
    checksum_sha256: str,
    original_filename: str,
) -> str:
    title_slug = _slugify(title) or "tender"
    filename = _safe_pdf_filename(original_filename)
    return f"demo/tenders/{title_slug}/{checksum_sha256[:12]}-{filename}"


def _safe_pdf_filename(filename: str) -> str:
    path = Path(filename)
    stem = _slugify(path.stem) or "document"
    return f"{stem}.pdf"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return re.sub(r"-{2,}", "-", slug)
