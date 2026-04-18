from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from bidded.documents import (
    TenderPdfRegistrationError,
    register_demo_tender_pdf,
)


class RecordingStorageBucket:
    def __init__(self) -> None:
        self.uploads: list[tuple[str, bytes, dict[str, str] | None]] = []

    def upload(
        self,
        path: str,
        file: bytes,
        *,
        file_options: dict[str, str] | None = None,
    ) -> object:
        self.uploads.append((path, file, file_options))
        return type("StorageResponse", (), {"path": path})()


class RecordingStorage:
    def __init__(self) -> None:
        self.bucket_names: list[str] = []
        self.bucket = RecordingStorageBucket()

    def from_(self, bucket_name: str) -> RecordingStorageBucket:
        self.bucket_names.append(bucket_name)
        return self.bucket


class RecordingTable:
    def __init__(self, table_name: str) -> None:
        self.table_name = table_name
        self.upserts: list[tuple[dict[str, Any], str | None]] = []

    def upsert(
        self,
        payload: dict[str, Any],
        *,
        on_conflict: str | None = None,
    ) -> RecordingTable:
        self.upserts.append((payload, on_conflict))
        return self

    def execute(self) -> object:
        payload = self.upserts[-1][0]
        id_by_table = {
            "companies": "company-1",
            "tenders": "tender-1",
            "documents": "document-1",
        }
        return type(
            "Response",
            (),
            {"data": [{**payload, "id": id_by_table[self.table_name]}]},
        )()


class RecordingSupabaseClient:
    def __init__(self) -> None:
        self.storage = RecordingStorage()
        self.tables: dict[str, RecordingTable] = {}
        self.table_names: list[str] = []

    def table(self, table_name: str) -> RecordingTable:
        self.table_names.append(table_name)
        table = self.tables.get(table_name)
        if table is None:
            table = RecordingTable(table_name)
            self.tables[table_name] = table
        return table


def _write_pdf(path: Path) -> bytes:
    content = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n"
    path.write_bytes(content)
    return content


def test_register_demo_tender_pdf_uploads_and_persists_document(
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "Bilaga Skakrav.pdf"
    pdf_bytes = _write_pdf(pdf_path)
    client = RecordingSupabaseClient()

    result = register_demo_tender_pdf(
        client,
        pdf_path=pdf_path,
        bucket_name="procurement-fixtures",
        tender_title="Skakrav for IT consultancy",
        issuing_authority="Example Municipality",
        procurement_reference="REF-2026-001",
        procurement_metadata={"procedure": "open", "cpv": "72000000"},
    )

    checksum = hashlib.sha256(pdf_bytes).hexdigest()
    assert result.company_id == "company-1"
    assert result.tender_id == "tender-1"
    assert result.document_id == "document-1"
    assert result.checksum_sha256 == checksum
    assert result.original_filename == "Bilaga Skakrav.pdf"
    assert result.content_type == "application/pdf"
    assert result.storage_path.endswith("bilaga-skakrav.pdf")

    assert client.storage.bucket_names == ["procurement-fixtures"]
    assert client.storage.bucket.uploads == [
        (
            result.storage_path,
            pdf_bytes,
            {"content-type": "application/pdf", "upsert": "true"},
        )
    ]

    company_payload, company_conflict = client.tables["companies"].upserts[0]
    assert company_payload["tenant_key"] == "demo"
    assert company_conflict == "tenant_key,name"

    tender_payload, tender_conflict = client.tables["tenders"].upserts[0]
    assert tender_payload["title"] == "Skakrav for IT consultancy"
    assert tender_payload["issuing_authority"] == "Example Municipality"
    assert tender_payload["procurement_reference"] == "REF-2026-001"
    assert tender_payload["procurement_context"] == {
        "procedure": "open",
        "cpv": "72000000",
    }
    assert tender_payload["language_policy"] == {
        "source_document_language": "sv",
        "agent_output_language": "en",
    }
    assert tender_payload["metadata"]["demo_company_id"] == "company-1"
    assert tender_conflict == "tenant_key,title,issuing_authority"

    document_payload, document_conflict = client.tables["documents"].upserts[0]
    assert document_payload["tender_id"] == "tender-1"
    assert document_payload["company_id"] is None
    assert document_payload["storage_path"] == result.storage_path
    assert document_payload["checksum_sha256"] == checksum
    assert document_payload["content_type"] == "application/pdf"
    assert document_payload["document_role"] == "tender_document"
    assert document_payload["parse_status"] == "pending"
    assert document_payload["original_filename"] == "Bilaga Skakrav.pdf"
    assert document_payload["metadata"]["demo_company_id"] == "company-1"
    assert document_conflict == "storage_path"


def test_register_demo_tender_pdf_rejects_missing_file(tmp_path: Path) -> None:
    missing_pdf = tmp_path / "missing.pdf"

    with pytest.raises(TenderPdfRegistrationError, match="does not exist"):
        register_demo_tender_pdf(
            RecordingSupabaseClient(),
            pdf_path=missing_pdf,
            bucket_name="procurement-fixtures",
            tender_title="Skakrav",
            issuing_authority="Example Municipality",
        )


def test_register_demo_tender_pdf_rejects_non_pdf(tmp_path: Path) -> None:
    text_file = tmp_path / "requirements.txt"
    text_file.write_text("not a pdf")

    with pytest.raises(TenderPdfRegistrationError, match="not a PDF"):
        register_demo_tender_pdf(
            RecordingSupabaseClient(),
            pdf_path=text_file,
            bucket_name="procurement-fixtures",
            tender_title="Skakrav",
            issuing_authority="Example Municipality",
        )
