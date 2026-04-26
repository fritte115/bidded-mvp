from __future__ import annotations

import hashlib
import re
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Protocol

from bidded.db.seed_demo_company import build_demo_company_payload

PDF_CONTENT_TYPE = "application/pdf"
DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


class TenderDocumentRegistrationError(RuntimeError):
    """Raised when a local tender document cannot be registered."""


TenderPdfRegistrationError = TenderDocumentRegistrationError


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
class TenderDocumentRegistrationResult:
    company_id: str
    tender_id: str
    document_id: str
    storage_path: str
    checksum_sha256: str
    content_type: str
    original_filename: str


TenderPdfRegistrationResult = TenderDocumentRegistrationResult


@dataclass(frozen=True)
class ValidatedTenderDocument:
    path: Path
    content: bytes
    content_type: str
    source_format: str


def register_demo_tender_document(
    client: SupabaseTenderRegistrationClient,
    *,
    document_path: Path,
    bucket_name: str,
    tender_title: str,
    issuing_authority: str,
    procurement_reference: str | None = None,
    procurement_metadata: Mapping[str, Any] | None = None,
    source_label: str = "registered tender document",
    procurement_document_role: str | None = None,
    created_via: str = "bidded_cli",
) -> TenderDocumentRegistrationResult:
    """Upload a local PDF or DOCX and register it as a demo tender document."""

    validated_document = _read_valid_tender_document(Path(document_path))
    checksum_sha256 = hashlib.sha256(validated_document.content).hexdigest()
    storage_path = _storage_path(
        title=tender_title,
        checksum_sha256=checksum_sha256,
        original_filename=validated_document.path.name,
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
        validated_document.content,
        file_options={
            "content-type": validated_document.content_type,
            "upsert": "true",
        },
    )
    document_id = _upsert_tender_document(
        client,
        tender_id=tender_id,
        demo_company_id=company_id,
        storage_path=storage_path,
        checksum_sha256=checksum_sha256,
        content_type=validated_document.content_type,
        original_filename=validated_document.path.name,
        source_label=source_label,
        procurement_document_role=procurement_document_role,
        created_via=created_via,
    )

    return TenderDocumentRegistrationResult(
        company_id=company_id,
        tender_id=tender_id,
        document_id=document_id,
        storage_path=storage_path,
        checksum_sha256=checksum_sha256,
        content_type=validated_document.content_type,
        original_filename=validated_document.path.name,
    )


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
    if Path(pdf_path).suffix.lower() != ".pdf":
        raise TenderDocumentRegistrationError(f"Input file is not a PDF: {pdf_path}")
    return register_demo_tender_document(
        client,
        document_path=pdf_path,
        bucket_name=bucket_name,
        tender_title=tender_title,
        issuing_authority=issuing_authority,
        procurement_reference=procurement_reference,
        procurement_metadata=procurement_metadata,
        source_label=source_label,
        procurement_document_role=procurement_document_role,
        created_via=created_via,
    )


def _read_valid_tender_document(path: Path) -> ValidatedTenderDocument:
    if not path.exists():
        raise TenderDocumentRegistrationError(
            f"Tender document file does not exist: {path}"
        )
    if not path.is_file():
        raise TenderDocumentRegistrationError(
            f"Tender document path is not a file: {path}"
        )

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        document_bytes = path.read_bytes()
        if not document_bytes.startswith(b"%PDF-"):
            raise TenderDocumentRegistrationError(f"Input file is not a PDF: {path}")
        return ValidatedTenderDocument(
            path=path,
            content=document_bytes,
            content_type=PDF_CONTENT_TYPE,
            source_format="pdf",
        )

    if suffix == ".docx":
        document_bytes = path.read_bytes()
        if not _is_valid_docx(document_bytes):
            raise TenderDocumentRegistrationError(f"Input file is not a DOCX: {path}")
        return ValidatedTenderDocument(
            path=path,
            content=document_bytes,
            content_type=DOCX_CONTENT_TYPE,
            source_format="docx",
        )

    raise TenderDocumentRegistrationError(
        f"Unsupported document type: {path}. Supported types are PDF and DOCX."
    )


def _read_valid_pdf(path: Path) -> bytes:
    validated_document = _read_valid_tender_document(path)
    if validated_document.content_type != PDF_CONTENT_TYPE:
        raise TenderDocumentRegistrationError(f"Input file is not a PDF: {path}")
    return validated_document.content


def _is_valid_docx(document_bytes: bytes) -> bool:
    try:
        with zipfile.ZipFile(BytesIO(document_bytes)) as archive:
            return "word/document.xml" in archive.namelist()
    except zipfile.BadZipFile:
        return False


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
    content_type: str,
    original_filename: str,
    source_label: str,
    procurement_document_role: str | None,
    created_via: str,
) -> str:
    metadata: dict[str, Any] = {
        "registered_via": created_via,
        "source_label": source_label.strip() or "registered tender document",
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
        "content_type": content_type,
        "document_role": "tender_document",
        "parse_status": "pending",
        "original_filename": original_filename,
        "metadata": metadata,
    }
    response = (
        client.table("documents").upsert(payload, on_conflict="storage_path").execute()
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
    filename = _safe_document_filename(original_filename)
    return f"demo/procurements/{title_slug}/{checksum_sha256[:12]}-{filename}"


def _safe_document_filename(filename: str) -> str:
    path = Path(filename)
    stem = _slugify(path.stem) or "document"
    suffix = path.suffix.lower()
    if suffix not in {".pdf", ".docx"}:
        suffix = ".pdf"
    return f"{stem}{suffix}"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return re.sub(r"-{2,}", "-", slug)
