from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import fitz
import pytest

from bidded.documents import PdfIngestionError, ingest_tender_pdf_document

DOCUMENT_ID = UUID("44444444-4444-4444-8444-444444444444")


class RecordingStorageBucket:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files
        self.downloads: list[str] = []

    def download(self, path: str) -> bytes:
        self.downloads.append(path)
        return self.files[path]


class RecordingStorage:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.bucket_names: list[str] = []
        self.bucket = RecordingStorageBucket(files)

    def from_(self, bucket_name: str) -> RecordingStorageBucket:
        self.bucket_names.append(bucket_name)
        return self.bucket


class RecordingQuery:
    def __init__(self, client: RecordingSupabaseClient, table_name: str) -> None:
        self.client = client
        self.table_name = table_name
        self.filters: list[tuple[str, str]] = []
        self.selected_columns: str | None = None
        self.insert_payload: list[dict[str, Any]] | None = None
        self.update_payload: dict[str, Any] | None = None
        self.delete_requested = False
        self.upsert_payload: list[dict[str, Any]] | None = None
        self.on_conflict: str | None = None

    def select(self, columns: str) -> RecordingQuery:
        self.selected_columns = columns
        return self

    def eq(self, column: str, value: object) -> RecordingQuery:
        self.filters.append((column, str(value)))
        return self

    def insert(self, payload: list[dict[str, Any]]) -> RecordingQuery:
        self.insert_payload = payload
        return self

    def upsert(
        self,
        payload: list[dict[str, Any]],
        *,
        on_conflict: str | None = None,
    ) -> RecordingQuery:
        self.upsert_payload = payload
        self.on_conflict = on_conflict
        return self

    def update(self, payload: dict[str, Any]) -> RecordingQuery:
        self.update_payload = payload
        return self

    def delete(self) -> RecordingQuery:
        self.delete_requested = True
        return self

    def execute(self) -> object:
        if self.upsert_payload is not None:
            self.client.inserts.setdefault("evidence_items", []).append(
                self.upsert_payload
            )
            rows = [
                {**row, "id": f"ev-{index}"}
                for index, row in enumerate(self.upsert_payload, start=1)
            ]
            self.client.rows.setdefault("evidence_items", []).extend(rows)
            self.upsert_payload = None
            return type("Response", (), {"data": rows})()

        if self.insert_payload is not None:
            inserted_rows = []
            for _index, payload in enumerate(self.insert_payload, start=1):
                row = {**payload, "id": str(uuid4())}
                inserted_rows.append(row)
                self.client.rows.setdefault(self.table_name, []).append(row)
            self.client.inserts.setdefault(self.table_name, []).append(
                self.insert_payload
            )
            return type("Response", (), {"data": inserted_rows})()

        if self.update_payload is not None:
            self.client.updates.setdefault(self.table_name, []).append(
                (self.update_payload, self.filters)
            )
            rows = self._filtered_rows()
            for row in rows:
                row.update(self.update_payload)
            return type("Response", (), {"data": rows})()

        if self.delete_requested:
            self.client.deletes.setdefault(self.table_name, []).append(self.filters)
            rows = self.client.rows.get(self.table_name, [])
            self.client.rows[self.table_name] = [
                row
                for row in rows
                if not all(
                    str(row.get(column)) == value
                    for column, value in self.filters
                )
            ]
            return type("Response", (), {"data": []})()

        return type("Response", (), {"data": self._filtered_rows()})()

    def _filtered_rows(self) -> list[dict[str, Any]]:
        rows = self.client.rows.get(self.table_name, [])
        return [
            row
            for row in rows
            if all(str(row.get(column)) == value for column, value in self.filters)
        ]


class RecordingSupabaseClient:
    def __init__(self, *, pdf_bytes: bytes, document_row: dict[str, Any]) -> None:
        storage_path = document_row["storage_path"]
        self.storage = RecordingStorage({storage_path: pdf_bytes})
        self.rows: dict[str, list[dict[str, Any]]] = {
            "documents": [document_row],
            "document_chunks": [
                {
                    "document_id": str(DOCUMENT_ID),
                    "chunk_index": 99,
                    "text": "stale chunk",
                }
            ],
        }
        self.inserts: dict[str, list[list[dict[str, Any]]]] = {}
        self.updates: dict[str, list[tuple[dict[str, Any], list[tuple[str, str]]]]] = {}
        self.deletes: dict[str, list[list[tuple[str, str]]]] = {}
        self.table_names: list[str] = []

    def table(self, table_name: str) -> RecordingQuery:
        self.table_names.append(table_name)
        return RecordingQuery(self, table_name)


def _document_row(**overrides: Any) -> dict[str, Any]:
    row = {
        "id": str(DOCUMENT_ID),
        "tenant_key": "demo",
        "storage_path": "demo/tenders/skakrav/tender.pdf",
        "content_type": "application/pdf",
        "document_role": "tender_document",
        "parse_status": "pending",
        "original_filename": "Tender.pdf",
        "metadata": {
            "source_label": "registered tender PDF",
            "registered_via": "bidded_cli",
        },
    }
    row.update(overrides)
    return row


def _text_pdf(page_texts: list[str]) -> bytes:
    document = fitz.open()
    for text in page_texts:
        page = document.new_page()
        if text:
            page.insert_text((72, 72), text, fontsize=11)
    try:
        return document.tobytes()
    finally:
        document.close()


def test_ingest_tender_pdf_document_extracts_and_persists_page_chunks() -> None:
    client = RecordingSupabaseClient(
        pdf_bytes=_text_pdf(
            [
                "Mandatory requirement: Supplier must provide ISO 27001.",
                "Award criterion: Delivery model and consultant quality.",
            ]
        ),
        document_row=_document_row(),
    )

    result = ingest_tender_pdf_document(
        client,
        document_id=DOCUMENT_ID,
        bucket_name="procurement-fixtures",
        max_chunk_chars=160,
    )

    assert result.document_id == DOCUMENT_ID
    assert result.page_count == 2
    assert result.chunk_count == 2
    assert [chunk.chunk_index for chunk in result.chunks] == [0, 1]
    assert [chunk.page_start for chunk in result.chunks] == [1, 2]
    assert [chunk.page_end for chunk in result.chunks] == [1, 2]
    assert "ISO 27001" in result.chunks[0].text
    assert "consultant quality" in result.chunks[1].text

    assert client.storage.bucket_names == ["procurement-fixtures"]
    assert client.storage.bucket.downloads == ["demo/tenders/skakrav/tender.pdf"]
    assert client.deletes["document_chunks"] == [
        [("document_id", str(DOCUMENT_ID))]
    ]

    inserted_chunks = client.inserts["document_chunks"][0]
    assert [chunk["chunk_index"] for chunk in inserted_chunks] == [0, 1]
    assert inserted_chunks[0]["document_id"] == str(DOCUMENT_ID)
    assert inserted_chunks[0]["tenant_key"] == "demo"
    assert inserted_chunks[0]["page_start"] == 1
    assert inserted_chunks[0]["page_end"] == 1
    assert inserted_chunks[0]["metadata"]["source_label"] == "registered tender PDF"
    assert inserted_chunks[0]["metadata"]["parser"] == "pymupdf"
    assert inserted_chunks[0]["metadata"]["page_numbers"] == [1]
    assert inserted_chunks[0]["metadata"]["source_document_id"] == str(DOCUMENT_ID)

    status_updates = client.updates["documents"]
    assert [update["parse_status"] for update, _filters in status_updates] == [
        "parsing",
        "parsed",
    ]
    parsed_metadata = status_updates[-1][0]["metadata"]
    assert parsed_metadata["parser"]["status"] == "parsed"
    assert parsed_metadata["parser"]["page_count"] == 2
    assert parsed_metadata["parser"]["chunk_count"] == 2
    assert "error_message" not in parsed_metadata["parser"]

    assert "evidence_items" in client.inserts
    assert client.inserts["evidence_items"]


def test_ingest_tender_pdf_document_marks_empty_text_pdf_as_parser_failed() -> None:
    client = RecordingSupabaseClient(
        pdf_bytes=_text_pdf(["", ""]),
        document_row=_document_row(),
    )

    with pytest.raises(PdfIngestionError, match="No extractable text"):
        ingest_tender_pdf_document(
            client,
            document_id=DOCUMENT_ID,
            bucket_name="procurement-fixtures",
        )

    assert "document_chunks" not in client.inserts
    status_updates = client.updates["documents"]
    assert [update["parse_status"] for update, _filters in status_updates] == [
        "parsing",
        "parser_failed",
    ]
    failed_metadata = status_updates[-1][0]["metadata"]
    assert failed_metadata["parser"]["status"] == "parser_failed"
    assert "OCR is a non-goal" in failed_metadata["parser"]["error_message"]


def test_ingest_tender_pdf_document_persists_parser_failure_error() -> None:
    client = RecordingSupabaseClient(
        pdf_bytes=b"%PDF-1.4\nnot a complete pdf",
        document_row=_document_row(),
    )

    with pytest.raises(PdfIngestionError, match="PDF extraction failed"):
        ingest_tender_pdf_document(
            client,
            document_id=DOCUMENT_ID,
            bucket_name="procurement-fixtures",
        )

    assert "document_chunks" not in client.inserts
    failed_update = client.updates["documents"][-1][0]
    assert failed_update["parse_status"] == "parser_failed"
    assert failed_update["metadata"]["parser"]["status"] == "parser_failed"
    assert failed_update["metadata"]["parser"]["error_message"]


def test_ingest_tender_pdf_document_rejects_docx_as_out_of_scope() -> None:
    client = RecordingSupabaseClient(
        pdf_bytes=b"not used",
        document_row=_document_row(
            content_type=(
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
            original_filename="requirements.docx",
            storage_path="demo/tenders/skakrav/requirements.docx",
        ),
    )

    with pytest.raises(PdfIngestionError, match="DOCX"):
        ingest_tender_pdf_document(
            client,
            document_id=DOCUMENT_ID,
            bucket_name="procurement-fixtures",
        )

    assert client.storage.bucket.downloads == []
    failed_update = client.updates["documents"][-1][0]
    assert failed_update["parse_status"] == "parser_failed"
    assert "DOCX" in failed_update["metadata"]["parser"]["error_message"]
