from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from bidded.evidence.company_kb import ATTACHMENT_TYPES

DEMO_TENANT_KEY = "demo"


class CompanyKbRegistrationError(RuntimeError):
    """Raised when a company KB PDF cannot be registered."""


class SupabaseCompanyKbUpsertQuery(Protocol):
    def execute(self) -> Any: ...


class SupabaseCompanyKbTable(Protocol):
    def upsert(
        self,
        payload: dict[str, Any],
        *,
        on_conflict: str | None = None,
    ) -> SupabaseCompanyKbUpsertQuery: ...


class SupabaseCompanyKbStorageBucket(Protocol):
    def upload(
        self,
        path: str,
        file: bytes,
        *,
        file_options: dict[str, str] | None = None,
    ) -> Any: ...


class SupabaseCompanyKbStorage(Protocol):
    def from_(self, bucket_name: str) -> SupabaseCompanyKbStorageBucket: ...


class SupabaseCompanyKbRegistrationClient(Protocol):
    storage: SupabaseCompanyKbStorage

    def table(self, table_name: str) -> SupabaseCompanyKbTable: ...


@dataclass(frozen=True)
class CompanyKbPdfRegistrationResult:
    company_id: str
    document_id: str
    storage_path: str
    checksum_sha256: str
    content_type: str
    original_filename: str
    attachment_type: str


def register_company_kb_pdf(
    client: SupabaseCompanyKbRegistrationClient,
    *,
    pdf_path: Path,
    bucket_name: str,
    company_id: UUID | str,
    source_label: str,
    attachment_type: str = "other",
    created_via: str = "bidded_cli",
) -> CompanyKbPdfRegistrationResult:
    """Upload an approved company KB text-PDF and register it for draft use."""

    normalized_company_id = str(company_id)
    normalized_attachment_type = _normalize_attachment_type(attachment_type)
    path = Path(pdf_path)
    pdf_bytes = _read_valid_pdf(path)
    checksum_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    storage_path = _storage_path(
        company_id=normalized_company_id,
        checksum_sha256=checksum_sha256,
        original_filename=path.name,
    )

    client.storage.from_(bucket_name).upload(
        storage_path,
        pdf_bytes,
        file_options={"content-type": "application/pdf", "upsert": "true"},
    )
    document_id = _upsert_company_document(
        client,
        company_id=normalized_company_id,
        storage_path=storage_path,
        checksum_sha256=checksum_sha256,
        original_filename=path.name,
        source_label=source_label,
        attachment_type=normalized_attachment_type,
        created_via=created_via,
    )
    return CompanyKbPdfRegistrationResult(
        company_id=normalized_company_id,
        document_id=document_id,
        storage_path=storage_path,
        checksum_sha256=checksum_sha256,
        content_type="application/pdf",
        original_filename=path.name,
        attachment_type=normalized_attachment_type,
    )


def _upsert_company_document(
    client: SupabaseCompanyKbRegistrationClient,
    *,
    company_id: str,
    storage_path: str,
    checksum_sha256: str,
    original_filename: str,
    source_label: str,
    attachment_type: str,
    created_via: str,
) -> str:
    metadata = {
        "registered_via": created_via,
        "source_label": source_label.strip() or original_filename,
        "kb_attachment_type": attachment_type,
        "approved_for_bid_drafts": True,
    }
    payload = {
        "tenant_key": DEMO_TENANT_KEY,
        "tender_id": None,
        "company_id": company_id,
        "storage_path": storage_path,
        "checksum_sha256": checksum_sha256,
        "content_type": "application/pdf",
        "document_role": "company_profile",
        "parse_status": "pending",
        "original_filename": original_filename,
        "metadata": metadata,
    }
    response = (
        client.table("documents").upsert(payload, on_conflict="storage_path").execute()
    )
    return _first_returned_id(response, "documents")


def _read_valid_pdf(path: Path) -> bytes:
    if not path.exists():
        raise CompanyKbRegistrationError(f"PDF file does not exist: {path}")
    if not path.is_file():
        raise CompanyKbRegistrationError(f"PDF path is not a file: {path}")
    if path.suffix.lower() != ".pdf":
        raise CompanyKbRegistrationError(f"Input file is not a PDF: {path}")

    pdf_bytes = path.read_bytes()
    if not pdf_bytes.startswith(b"%PDF-"):
        raise CompanyKbRegistrationError(f"Input file is not a PDF: {path}")
    return pdf_bytes


def _storage_path(
    *,
    company_id: str,
    checksum_sha256: str,
    original_filename: str,
) -> str:
    return (
        f"demo/company-kb/{company_id}/"
        f"{checksum_sha256[:12]}-{_slug_filename(original_filename)}"
    )


def _slug_filename(filename: str) -> str:
    stem = Path(filename).stem
    suffix = Path(filename).suffix.lower() or ".pdf"
    slug = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-") or "document"
    return f"{slug}{suffix}"


def _normalize_attachment_type(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in ATTACHMENT_TYPES:
        raise CompanyKbRegistrationError(
            "attachment_type must be one of: "
            f"{', '.join(sorted(ATTACHMENT_TYPES))}."
        )
    return normalized


def _first_returned_id(response: Any, table_name: str) -> str:
    data = getattr(response, "data", None)
    if isinstance(data, list) and data and isinstance(data[0], Mapping):
        row_id = data[0].get("id")
        if row_id:
            return str(row_id)
    raise CompanyKbRegistrationError(
        f"Supabase {table_name} upsert did not return a row id."
    )


__all__ = [
    "CompanyKbPdfRegistrationResult",
    "CompanyKbRegistrationError",
    "register_company_kb_pdf",
]
