from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import fitz

from bidded.documents import (
    ingest_company_kb_pdf_document,
    register_company_kb_pdf,
)

COMPANY_ID = UUID("33333333-3333-4333-8333-333333333333")
DOCUMENT_ID = UUID("66666666-6666-4666-8666-666666666666")


class CompanyKbBucket:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files
        self.uploads: list[tuple[str, bytes, dict[str, str] | None]] = []
        self.downloads: list[str] = []

    def upload(
        self,
        path: str,
        file: bytes,
        *,
        file_options: dict[str, str] | None = None,
    ) -> object:
        self.uploads.append((path, file, file_options))
        self.files[path] = file
        return type("Response", (), {"data": {"path": path}})()

    def download(self, path: str) -> bytes:
        self.downloads.append(path)
        return self.files[path]


class CompanyKbStorage:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.bucket_names: list[str] = []
        self.bucket = CompanyKbBucket(files)

    def from_(self, bucket_name: str) -> CompanyKbBucket:
        self.bucket_names.append(bucket_name)
        return self.bucket


class CompanyKbQuery:
    def __init__(self, client: CompanyKbClient, table_name: str) -> None:
        self.client = client
        self.table_name = table_name
        self.filters: list[tuple[str, str]] = []
        self.insert_payload: list[dict[str, Any]] | None = None
        self.upsert_payload: dict[str, Any] | list[dict[str, Any]] | None = None
        self.update_payload: dict[str, Any] | None = None
        self.delete_requested = False
        self.on_conflict: str | None = None

    def select(self, _columns: str) -> CompanyKbQuery:
        return self

    def eq(self, column: str, value: object) -> CompanyKbQuery:
        self.filters.append((column, str(value)))
        return self

    def insert(self, payload: list[dict[str, Any]]) -> CompanyKbQuery:
        self.insert_payload = payload
        return self

    def upsert(
        self,
        payload: dict[str, Any] | list[dict[str, Any]],
        *,
        on_conflict: str | None = None,
    ) -> CompanyKbQuery:
        self.upsert_payload = payload
        self.on_conflict = on_conflict
        return self

    def update(self, payload: dict[str, Any]) -> CompanyKbQuery:
        self.update_payload = payload
        return self

    def delete(self) -> CompanyKbQuery:
        self.delete_requested = True
        return self

    def execute(self) -> object:
        if self.upsert_payload is not None:
            payloads = (
                self.upsert_payload
                if isinstance(self.upsert_payload, list)
                else [self.upsert_payload]
            )
            rows = []
            for payload in payloads:
                row = {"id": str(uuid4()), **payload}
                existing = self._matching_conflict_row(row)
                if existing is not None:
                    existing.update(row)
                    rows.append(existing)
                else:
                    self.client.rows.setdefault(self.table_name, []).append(row)
                    rows.append(row)
            self.client.upserts.setdefault(self.table_name, []).append(
                (payloads, self.on_conflict)
            )
            return type("Response", (), {"data": rows})()

        if self.insert_payload is not None:
            rows = []
            for payload in self.insert_payload:
                row = {"id": str(uuid4()), **payload}
                self.client.rows.setdefault(self.table_name, []).append(row)
                rows.append(row)
            self.client.inserts.setdefault(self.table_name, []).append(rows)
            return type("Response", (), {"data": rows})()

        if self.update_payload is not None:
            rows = self._filtered_rows()
            for row in rows:
                row.update(self.update_payload)
            self.client.updates.setdefault(self.table_name, []).append(
                (self.update_payload, self.filters)
            )
            return type("Response", (), {"data": rows})()

        if self.delete_requested:
            self.client.rows[self.table_name] = [
                row
                for row in self.client.rows.get(self.table_name, [])
                if not all(
                    str(row.get(column)) == value
                    for column, value in self.filters
                )
            ]
            return type("Response", (), {"data": []})()

        return type("Response", (), {"data": self._filtered_rows()})()

    def _filtered_rows(self) -> list[dict[str, Any]]:
        return [
            row
            for row in self.client.rows.get(self.table_name, [])
            if all(str(row.get(column)) == value for column, value in self.filters)
        ]

    def _matching_conflict_row(self, row: dict[str, Any]) -> dict[str, Any] | None:
        if self.on_conflict == "storage_path":
            return next(
                (
                    existing
                    for existing in self.client.rows.get(self.table_name, [])
                    if existing.get("storage_path") == row.get("storage_path")
                ),
                None,
            )
        if self.on_conflict == "tenant_key,evidence_key":
            return next(
                (
                    existing
                    for existing in self.client.rows.get(self.table_name, [])
                    if existing.get("tenant_key") == row.get("tenant_key")
                    and existing.get("evidence_key") == row.get("evidence_key")
                ),
                None,
            )
        return None


class CompanyKbClient:
    def __init__(self, *, pdf_bytes: bytes | None = None) -> None:
        storage_path = "demo/company-kb/iso.pdf"
        self.storage = CompanyKbStorage({storage_path: pdf_bytes or b"%PDF-empty"})
        self.rows: dict[str, list[dict[str, Any]]] = {
            "documents": [
                {
                    "id": str(DOCUMENT_ID),
                    "tenant_key": "demo",
                    "tender_id": None,
                    "company_id": str(COMPANY_ID),
                    "storage_path": storage_path,
                    "checksum_sha256": "a" * 64,
                    "content_type": "application/pdf",
                    "document_role": "company_profile",
                    "parse_status": "pending",
                    "original_filename": "iso.pdf",
                    "metadata": {
                        "source_label": "ISO 27001 certificate",
                        "kb_attachment_type": "certificate",
                        "approved_for_bid_drafts": True,
                    },
                }
            ],
            "document_chunks": [],
            "evidence_items": [],
        }
        self.inserts: dict[str, list[list[dict[str, Any]]]] = {}
        self.upserts: dict[str, list[tuple[list[dict[str, Any]], str | None]]] = {}
        self.updates: dict[str, list[tuple[dict[str, Any], list[tuple[str, str]]]]] = {}

    def table(self, table_name: str) -> CompanyKbQuery:
        return CompanyKbQuery(self, table_name)


def _text_pdf(text: str) -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text, fontsize=11)
    try:
        return document.tobytes()
    finally:
        document.close()


def test_register_company_kb_pdf_uploads_approved_company_profile_document(
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "iso.pdf"
    pdf_path.write_bytes(b"%PDF-registered")
    client = CompanyKbClient()
    client.rows["documents"] = []

    result = register_company_kb_pdf(
        client,
        pdf_path=pdf_path,
        bucket_name="public-procurements",
        company_id=COMPANY_ID,
        source_label="ISO 27001 certificate",
        attachment_type="certificate",
    )

    assert result.company_id == str(COMPANY_ID)
    assert result.original_filename == "iso.pdf"
    assert result.storage_path.startswith(f"demo/company-kb/{COMPANY_ID}/")
    assert client.storage.bucket_names == ["public-procurements"]
    assert client.storage.bucket.uploads[0][0] == result.storage_path
    document_row = client.rows["documents"][0]
    assert document_row["document_role"] == "company_profile"
    assert document_row["company_id"] == str(COMPANY_ID)
    assert document_row["metadata"]["approved_for_bid_drafts"] is True
    assert document_row["metadata"]["kb_attachment_type"] == "certificate"


def test_ingest_company_kb_pdf_materializes_company_profile_evidence() -> None:
    client = CompanyKbClient(
        pdf_bytes=_text_pdf("ISO/IEC 27001 certificate valid through 2027.")
    )

    result = ingest_company_kb_pdf_document(
        client,
        document_id=DOCUMENT_ID,
        bucket_name="public-procurements",
        max_chunk_chars=200,
    )

    assert result.document_id == DOCUMENT_ID
    assert result.page_count == 1
    assert result.chunk_count == 1
    assert client.rows["documents"][0]["parse_status"] == "parsed"
    evidence_payloads, on_conflict = client.upserts["evidence_items"][0]
    assert on_conflict == "tenant_key,evidence_key"
    assert len(evidence_payloads) == 1
    evidence = evidence_payloads[0]
    assert evidence["source_type"] == "company_profile"
    assert evidence["company_id"] == str(COMPANY_ID)
    assert evidence["category"] == "certification"
    assert evidence["source_metadata"]["source_label"] == "ISO 27001 certificate"
    assert evidence["metadata"]["attachment_type"] == "certificate"
    assert evidence["metadata"]["source_document_id"] == str(DOCUMENT_ID)
    assert evidence["metadata"]["source_storage_path"] == "demo/company-kb/iso.pdf"
    assert evidence.get("document_id") is None
    assert evidence.get("chunk_id") is None
