from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from bidded.documents.company_kb import (
    CompanyKbDocumentType,
    CompanyKbError,
    CompanyKbUploadFile,
    EvidenceExcerptRef,
    ExtractedCompanyKbFact,
    ExtractedCompanyKbFacts,
    delete_company_kb_document,
    ingest_company_kb_document,
    list_company_kb_documents,
    list_company_kb_evidence,
    register_company_kb_documents,
)

COMPANY_ID = UUID("22222222-2222-4222-8222-222222222222")
DOCUMENT_ID = UUID("44444444-4444-4444-8444-444444444444")


class RecordingStorageBucket:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.uploads: list[tuple[str, bytes, dict[str, str] | None]] = []
        self.downloads: list[str] = []
        self.removes: list[list[str]] = []

    def upload(
        self,
        path: str,
        file: bytes,
        *,
        file_options: dict[str, str] | None = None,
    ) -> object:
        self.uploads.append((path, file, file_options))
        self.files[path] = file
        return SimpleNamespace(data={"path": path})

    def download(self, path: str) -> bytes:
        self.downloads.append(path)
        return self.files[path]

    def remove(self, paths: list[str]) -> object:
        self.removes.append(paths)
        for path in paths:
            self.files.pop(path, None)
        return SimpleNamespace(data=paths)


class RecordingStorage:
    def __init__(self) -> None:
        self.bucket_names: list[str] = []
        self.bucket = RecordingStorageBucket()

    def from_(self, bucket_name: str) -> RecordingStorageBucket:
        self.bucket_names.append(bucket_name)
        return self.bucket


class RecordingQuery:
    def __init__(self, client: RecordingCompanyKbClient, table_name: str) -> None:
        self.client = client
        self.table_name = table_name
        self.filters: list[tuple[str, str]] = []
        self.selected_columns: str | None = None
        self.upsert_payload: dict[str, Any] | list[dict[str, Any]] | None = None
        self.insert_payload: list[dict[str, Any]] | None = None
        self.update_payload: dict[str, Any] | None = None
        self.delete_requested = False
        self.on_conflict: str | None = None

    def select(self, columns: str) -> RecordingQuery:
        self.selected_columns = columns
        return self

    def eq(self, column: str, value: object) -> RecordingQuery:
        self.filters.append((column, str(value)))
        return self

    def upsert(
        self,
        payload: dict[str, Any] | list[dict[str, Any]],
        *,
        on_conflict: str | None = None,
    ) -> RecordingQuery:
        self.upsert_payload = payload
        self.on_conflict = on_conflict
        return self

    def insert(self, payload: list[dict[str, Any]]) -> RecordingQuery:
        self.insert_payload = payload
        return self

    def update(self, payload: dict[str, Any]) -> RecordingQuery:
        self.update_payload = payload
        return self

    def delete(self) -> RecordingQuery:
        self.delete_requested = True
        return self

    def execute(self) -> object:
        if self.upsert_payload is not None:
            payloads = (
                [self.upsert_payload]
                if isinstance(self.upsert_payload, dict)
                else self.upsert_payload
            )
            rows = []
            for payload in payloads:
                row_id = (
                    str(DOCUMENT_ID) if self.table_name == "documents" else str(uuid4())
                )
                existing = self._find_existing(payload)
                row = {
                    **payload,
                    "id": existing.get("id", row_id) if existing else row_id,
                }
                if existing:
                    existing.update(row)
                else:
                    self.client.rows.setdefault(self.table_name, []).append(row)
                rows.append(row)
            self.client.upserts.setdefault(self.table_name, []).append(
                (payloads, self.on_conflict)
            )
            return SimpleNamespace(data=rows)

        if self.insert_payload is not None:
            rows = []
            for payload in self.insert_payload:
                row = {**payload, "id": str(uuid4())}
                self.client.rows.setdefault(self.table_name, []).append(row)
                rows.append(row)
            self.client.inserts.setdefault(self.table_name, []).append(
                self.insert_payload
            )
            return SimpleNamespace(data=rows)

        if self.update_payload is not None:
            rows = self._filtered_rows()
            for row in rows:
                if "metadata" in self.update_payload and isinstance(
                    row.get("metadata"), dict
                ):
                    row["metadata"] = {
                        **row["metadata"],
                        **self.update_payload["metadata"],
                    }
                    for key, value in self.update_payload.items():
                        if key != "metadata":
                            row[key] = value
                else:
                    row.update(self.update_payload)
            self.client.updates.setdefault(self.table_name, []).append(
                (self.update_payload, self.filters)
            )
            return SimpleNamespace(data=rows)

        if self.delete_requested:
            rows = self._filtered_rows()
            self.client.deletes.setdefault(self.table_name, []).append(self.filters)
            self.client.rows[self.table_name] = [
                row
                for row in self.client.rows.get(self.table_name, [])
                if row not in rows
            ]
            if self.table_name == "documents":
                deleted_ids = {row["id"] for row in rows}
                self.client.rows["document_chunks"] = [
                    row
                    for row in self.client.rows.get("document_chunks", [])
                    if row.get("document_id") not in deleted_ids
                ]
                self.client.rows["evidence_items"] = [
                    row
                    for row in self.client.rows.get("evidence_items", [])
                    if row.get("document_id") not in deleted_ids
                ]
            return SimpleNamespace(data=rows)

        return SimpleNamespace(data=self._filtered_rows())

    def _find_existing(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        if self.on_conflict == "storage_path":
            for row in self.client.rows.get(self.table_name, []):
                if row.get("storage_path") == payload.get("storage_path"):
                    return row
        if self.on_conflict == "tenant_key,evidence_key":
            for row in self.client.rows.get(self.table_name, []):
                if row.get("tenant_key") == payload.get("tenant_key") and row.get(
                    "evidence_key"
                ) == payload.get("evidence_key"):
                    return row
        return None

    def _filtered_rows(self) -> list[dict[str, Any]]:
        rows = self.client.rows.get(self.table_name, [])
        return [
            row
            for row in rows
            if all(str(row.get(column)) == value for column, value in self.filters)
        ]


class RecordingCompanyKbClient:
    def __init__(self) -> None:
        self.storage = RecordingStorage()
        self.rows: dict[str, list[dict[str, Any]]] = {
            "documents": [],
            "document_chunks": [],
            "evidence_items": [],
        }
        self.upserts: dict[str, list[tuple[list[dict[str, Any]], str | None]]] = {}
        self.inserts: dict[str, list[list[dict[str, Any]]]] = {}
        self.updates: dict[str, list[tuple[dict[str, Any], list[tuple[str, str]]]]] = {}
        self.deletes: dict[str, list[list[tuple[str, str]]]] = {}
        self.table_names: list[str] = []

    def table(self, table_name: str) -> RecordingQuery:
        self.table_names.append(table_name)
        return RecordingQuery(self, table_name)


class CertificationExtractor:
    def extract(self, request: Any) -> ExtractedCompanyKbFacts:
        chunk = request.chunks[0]
        return ExtractedCompanyKbFacts(
            facts=(
                ExtractedCompanyKbFact(
                    fact_type="certification",
                    category="certification",
                    claim=(
                        "Company holds ISO 27001 certification valid until "
                        "2027-03-31."
                    ),
                    normalized_meaning=(
                        "The company has active ISO 27001 certification until "
                        "2027-03-31."
                    ),
                    evidence_ref=EvidenceExcerptRef(
                        chunk_id=chunk.chunk_id,
                        excerpt="ISO 27001 certification valid until 2027-03-31",
                    ),
                    confidence=0.92,
                    metadata={"certification_name": "ISO 27001"},
                ),
            )
        )


class BadExtractor:
    def extract(self, _request: Any) -> ExtractedCompanyKbFacts:
        raise RuntimeError("model unavailable")


def test_register_company_kb_documents_uploads_private_company_profile_documents() -> (
    None
):
    client = RecordingCompanyKbClient()
    result = register_company_kb_documents(
        client,
        company_id=COMPANY_ID,
        bucket_name="company-knowledge",
        files=[
            CompanyKbUploadFile(
                filename="ISO 27001 Certificate.pdf",
                content=b"%PDF-1.7\ncertificate",
                content_type="application/pdf",
                kb_document_type=CompanyKbDocumentType.CERTIFICATION,
            )
        ],
    )

    assert len(result) == 1
    registered = result[0]
    assert registered.company_id == COMPANY_ID
    assert registered.original_filename == "ISO 27001 Certificate.pdf"
    assert registered.storage_path.startswith(f"demo/company-knowledge/{COMPANY_ID}/")
    assert client.storage.bucket_names == ["company-knowledge"]
    assert client.storage.bucket.uploads[0][2] == {
        "content-type": "application/pdf",
        "upsert": "true",
    }

    document_payload, conflict = client.upserts["documents"][0]
    assert conflict == "storage_path"
    assert document_payload[0]["document_role"] == "company_profile"
    assert document_payload[0]["company_id"] == str(COMPANY_ID)
    assert document_payload[0]["tender_id"] is None
    assert document_payload[0]["parse_status"] == "pending"
    assert document_payload[0]["metadata"]["kb_document_type"] == "certification"
    assert document_payload[0]["metadata"]["extraction_status"] == "pending"


def test_ingest_company_kb_document_extracts_text_and_materializes_cited_evidence() -> (
    None
):
    client = RecordingCompanyKbClient()
    [registered] = register_company_kb_documents(
        client,
        company_id=COMPANY_ID,
        bucket_name="company-knowledge",
        files=[
            CompanyKbUploadFile(
                filename="iso.txt",
                content=b"ISO 27001 certification valid until 2027-03-31.",
                content_type="text/plain",
                kb_document_type=CompanyKbDocumentType.CERTIFICATION,
            )
        ],
    )

    result = ingest_company_kb_document(
        client,
        document_id=registered.document_id,
        bucket_name="company-knowledge",
        extractor=CertificationExtractor(),
    )

    assert result.document_id == registered.document_id
    assert result.chunk_count == 1
    assert result.evidence_count == 1
    assert result.extraction_status == "extracted"
    assert client.rows["documents"][0]["parse_status"] == "parsed"
    assert client.rows["documents"][0]["metadata"]["extraction_status"] == "extracted"

    evidence = client.rows["evidence_items"][0]
    chunk = client.rows["document_chunks"][0]
    assert evidence["source_type"] == "company_profile"
    assert evidence["company_id"] == str(COMPANY_ID)
    assert evidence["document_id"] == str(registered.document_id)
    assert evidence["chunk_id"] == chunk["id"]
    assert evidence["field_path"].startswith("knowledge_base.certification.")
    assert evidence["source_metadata"]["source_label"] == "iso.txt"
    assert evidence["source_metadata"]["kb_document_type"] == "certification"
    assert "2027-03-31" in evidence["excerpt"]


def test_rule_based_company_kb_extraction_uses_resolvable_excerpt_for_long_text() -> (
    None
):
    client = RecordingCompanyKbClient()
    long_capability_text = (
        "Impact Solution delivers vending, retail, and workplace service concepts "
        "with documented routines for assortment planning, customer onboarding, "
        "operations, partner coordination, quality follow-up, and issue handling. "
        "The delivery material describes named roles, practical execution steps, "
        "and examples from previous public-sector-style bid responses."
    )
    [registered] = register_company_kb_documents(
        client,
        company_id=COMPANY_ID,
        bucket_name="company-knowledge",
        files=[
            CompanyKbUploadFile(
                filename="capability.txt",
                content=long_capability_text.encode(),
                content_type="text/plain",
                kb_document_type=CompanyKbDocumentType.CAPABILITY_STATEMENT,
            )
        ],
    )

    result = ingest_company_kb_document(
        client,
        document_id=registered.document_id,
        bucket_name="company-knowledge",
    )

    assert result.extraction_status == "extracted"
    assert result.warnings == ()
    evidence = client.rows["evidence_items"][0]
    chunk = client.rows["document_chunks"][0]
    assert evidence["excerpt"] in chunk["text"]
    assert evidence["metadata"]["extraction_method"] == "rule_based"


def test_ingest_company_kb_document_uses_fallback_on_extraction_failure() -> None:
    client = RecordingCompanyKbClient()
    [registered] = register_company_kb_documents(
        client,
        company_id=COMPANY_ID,
        bucket_name="company-knowledge",
        files=[
            CompanyKbUploadFile(
                filename="capability.md",
                content=(
                    b"# Capability\nCloud platform engineering and secure delivery."
                ),
                content_type="text/markdown",
                kb_document_type=CompanyKbDocumentType.CAPABILITY_STATEMENT,
            )
        ],
    )

    result = ingest_company_kb_document(
        client,
        document_id=registered.document_id,
        bucket_name="company-knowledge",
        extractor=BadExtractor(),
    )

    assert result.extraction_status == "fallback"
    assert result.warnings == ("model unavailable",)
    assert client.rows["documents"][0]["metadata"]["extraction_status"] == "fallback"
    evidence = client.rows["evidence_items"][0]
    assert evidence["category"] == "capability"
    assert evidence["confidence"] == 0.55
    assert evidence["metadata"]["fallback"] is True


def test_cv_profile_extraction_anonymizes_personal_identifiers() -> None:
    client = RecordingCompanyKbClient()
    [registered] = register_company_kb_documents(
        client,
        company_id=COMPANY_ID,
        bucket_name="company-knowledge",
        files=[
            CompanyKbUploadFile(
                filename="ada-cv.txt",
                content=(
                    b"Name: Ada Lovelace\nEmail: ada@example.com\n"
                    b"Senior data platform engineer with 12 years experience. "
                    b"Skills: Python, Azure, Kubernetes. Languages: Swedish, English."
                ),
                content_type="text/plain",
                kb_document_type=CompanyKbDocumentType.CV_PROFILE,
            )
        ],
    )

    result = ingest_company_kb_document(
        client,
        document_id=registered.document_id,
        bucket_name="company-knowledge",
    )

    assert result.extraction_status == "extracted"
    evidence = client.rows["evidence_items"][0]
    combined = f"{evidence['excerpt']} {evidence['normalized_meaning']}"
    assert "Ada Lovelace" not in combined
    assert "ada@example.com" not in combined
    assert "12 years" in combined
    assert evidence["category"] == "cv_summary"
    assert evidence["metadata"]["anonymized"] is True


def test_list_and_delete_company_kb_documents() -> None:
    client = RecordingCompanyKbClient()
    [registered] = register_company_kb_documents(
        client,
        company_id=COMPANY_ID,
        bucket_name="company-knowledge",
        files=[
            CompanyKbUploadFile(
                filename="case.csv",
                content=b"client,scope\nAgency,Case management delivery",
                content_type="text/csv",
                kb_document_type=CompanyKbDocumentType.CASE_STUDY,
            )
        ],
    )
    ingest_company_kb_document(
        client,
        document_id=registered.document_id,
        bucket_name="company-knowledge",
    )

    documents = list_company_kb_documents(client, company_id=COMPANY_ID)
    assert documents[0].evidence_count == 1
    assert documents[0].kb_document_type is CompanyKbDocumentType.CASE_STUDY
    assert list_company_kb_evidence(
        client,
        company_id=COMPANY_ID,
        document_id=registered.document_id,
    )[0]["document_id"] == str(registered.document_id)

    delete_company_kb_document(
        client,
        company_id=COMPANY_ID,
        document_id=registered.document_id,
        bucket_name="company-knowledge",
    )

    assert client.storage.bucket.removes == [[registered.storage_path]]
    assert client.rows["documents"] == []
    assert client.rows["document_chunks"] == []
    assert client.rows["evidence_items"] == []


def test_register_company_kb_documents_rejects_unsupported_files() -> None:
    client = RecordingCompanyKbClient()
    with pytest.raises(CompanyKbError, match="Unsupported company KB file type"):
        register_company_kb_documents(
            client,
            company_id=COMPANY_ID,
            bucket_name="company-knowledge",
            files=[
                CompanyKbUploadFile(
                    filename="scan.png",
                    content=b"png",
                    content_type="image/png",
                    kb_document_type=CompanyKbDocumentType.CERTIFICATION,
                )
            ],
        )
