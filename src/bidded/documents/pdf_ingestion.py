from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

import fitz

DEMO_TENANT_KEY = "demo"
PDF_TEXT_EXTRACTION_NON_GOAL_MESSAGE = (
    "Only text-based PDF ingestion is supported; OCR and DOCX are non-goals "
    "for Bidded v1."
)
DEFAULT_MAX_CHUNK_CHARS = 1800
CHUNKING_STRATEGY = "page_text_char_budget_v1"


class PdfIngestionError(RuntimeError):
    """Raised when a tender PDF cannot be parsed into document chunks."""


class SupabasePdfIngestionQuery(Protocol):
    def select(self, columns: str) -> SupabasePdfIngestionQuery: ...

    def eq(self, column: str, value: object) -> SupabasePdfIngestionQuery: ...

    def insert(
        self,
        payload: list[dict[str, Any]],
    ) -> SupabasePdfIngestionQuery: ...

    def update(self, payload: dict[str, Any]) -> SupabasePdfIngestionQuery: ...

    def delete(self) -> SupabasePdfIngestionQuery: ...

    def execute(self) -> Any: ...


class SupabasePdfStorageBucket(Protocol):
    def download(self, path: str) -> bytes: ...


class SupabasePdfStorage(Protocol):
    def from_(self, bucket_name: str) -> SupabasePdfStorageBucket: ...


class SupabasePdfIngestionClient(Protocol):
    storage: SupabasePdfStorage

    def table(self, table_name: str) -> SupabasePdfIngestionQuery: ...


@dataclass(frozen=True)
class ExtractedPdfPage:
    page_number: int
    text: str


@dataclass(frozen=True)
class PdfDocumentChunk:
    document_id: UUID
    page_start: int
    page_end: int
    chunk_index: int
    text: str
    metadata: dict[str, Any]

    def to_payload(self) -> dict[str, Any]:
        return {
            "tenant_key": DEMO_TENANT_KEY,
            "document_id": str(self.document_id),
            "page_start": self.page_start,
            "page_end": self.page_end,
            "chunk_index": self.chunk_index,
            "text": self.text,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class PdfIngestionResult:
    document_id: UUID
    page_count: int
    chunk_count: int
    chunks: list[PdfDocumentChunk]


def ingest_tender_pdf_document(
    client: SupabasePdfIngestionClient,
    *,
    document_id: UUID | str,
    bucket_name: str,
    max_chunk_chars: int = DEFAULT_MAX_CHUNK_CHARS,
) -> PdfIngestionResult:
    """Parse a registered tender text-PDF and persist page-referenced chunks."""

    normalized_document_id = _normalize_uuid(document_id, "document_id")
    if max_chunk_chars <= 0:
        raise PdfIngestionError("max_chunk_chars must be greater than zero.")

    document_row = _fetch_tender_document(client, normalized_document_id)
    source_metadata = _source_metadata(document_row, normalized_document_id)

    try:
        _ensure_text_pdf_document(document_row)
        _update_document_parse_status(
            client,
            document_id=normalized_document_id,
            parse_status="parsing",
            metadata={
                **source_metadata,
                "parser": {
                    "status": "parsing",
                    "parser": "pymupdf",
                    "non_goals": ["ocr", "docx"],
                },
            },
        )
        pdf_bytes = _download_document_bytes(
            client,
            bucket_name=bucket_name,
            storage_path=str(document_row["storage_path"]),
        )
        pages = _extract_pdf_pages(pdf_bytes)
        chunks = build_document_chunks(
            document_id=normalized_document_id,
            pages=pages,
            source_metadata=source_metadata,
            max_chunk_chars=max_chunk_chars,
        )
        if not chunks:
            raise PdfIngestionError(
                "No extractable text found in PDF. Text-based PDFs are required; "
                "OCR is a non-goal for Bidded v1."
            )

        _replace_document_chunks(client, normalized_document_id, chunks)
        _update_document_parse_status(
            client,
            document_id=normalized_document_id,
            parse_status="parsed",
            metadata={
                **source_metadata,
                "parser": {
                    "status": "parsed",
                    "parser": "pymupdf",
                    "page_count": len(pages),
                    "chunk_count": len(chunks),
                    "chunking_strategy": CHUNKING_STRATEGY,
                    "non_goals": ["ocr", "docx"],
                },
            },
        )
        return PdfIngestionResult(
            document_id=normalized_document_id,
            page_count=len(pages),
            chunk_count=len(chunks),
            chunks=chunks,
        )
    except PdfIngestionError as exc:
        _update_document_parse_status(
            client,
            document_id=normalized_document_id,
            parse_status="parser_failed",
            metadata={
                **source_metadata,
                "parser": {
                    "status": "parser_failed",
                    "parser": "pymupdf",
                    "error_message": str(exc),
                    "non_goals": ["ocr", "docx"],
                },
            },
        )
        raise


def build_document_chunks(
    *,
    document_id: UUID,
    pages: list[ExtractedPdfPage],
    source_metadata: Mapping[str, Any],
    max_chunk_chars: int = DEFAULT_MAX_CHUNK_CHARS,
) -> list[PdfDocumentChunk]:
    """Split extracted page text into deterministic page-referenced chunks."""

    chunks: list[PdfDocumentChunk] = []
    source_label = _source_label(source_metadata)
    for page in pages:
        for page_segment_index, chunk_text in enumerate(
            _split_page_text(page.text, max_chunk_chars=max_chunk_chars)
        ):
            chunks.append(
                PdfDocumentChunk(
                    document_id=document_id,
                    page_start=page.page_number,
                    page_end=page.page_number,
                    chunk_index=len(chunks),
                    text=chunk_text,
                    metadata={
                        "source_label": source_label,
                        "source_document_id": str(document_id),
                        "source_storage_path": source_metadata.get("storage_path"),
                        "source_original_filename": source_metadata.get(
                            "original_filename"
                        ),
                        "parser": "pymupdf",
                        "chunking_strategy": CHUNKING_STRATEGY,
                        "max_chunk_chars": max_chunk_chars,
                        "page_numbers": [page.page_number],
                        "page_segment_index": page_segment_index,
                    },
                )
            )

    return chunks


def _fetch_tender_document(
    client: SupabasePdfIngestionClient,
    document_id: UUID,
) -> dict[str, Any]:
    response = (
        client.table("documents")
        .select(
            "id,tenant_key,storage_path,content_type,document_role,"
            "parse_status,original_filename,metadata"
        )
        .eq("id", str(document_id))
        .eq("tenant_key", DEMO_TENANT_KEY)
        .execute()
    )
    data = getattr(response, "data", None)
    if isinstance(data, list) and data and isinstance(data[0], Mapping):
        row = dict(data[0])
        if row.get("document_role") != "tender_document":
            raise PdfIngestionError(
                f"Document is not a tender_document: {document_id}"
            )
        return row

    raise PdfIngestionError(f"Tender document does not exist: {document_id}")


def _ensure_text_pdf_document(document_row: Mapping[str, Any]) -> None:
    content_type = str(document_row.get("content_type") or "")
    filename = str(document_row.get("original_filename") or "")
    storage_path = str(document_row.get("storage_path") or "")

    if filename.lower().endswith(".docx") or storage_path.lower().endswith(".docx"):
        raise PdfIngestionError(PDF_TEXT_EXTRACTION_NON_GOAL_MESSAGE)

    if content_type != "application/pdf":
        raise PdfIngestionError(PDF_TEXT_EXTRACTION_NON_GOAL_MESSAGE)


def _download_document_bytes(
    client: SupabasePdfIngestionClient,
    *,
    bucket_name: str,
    storage_path: str,
) -> bytes:
    try:
        pdf_bytes = client.storage.from_(bucket_name).download(storage_path)
    except Exception as exc:  # pragma: no cover - depends on Supabase internals
        raise PdfIngestionError(f"PDF download failed: {exc}") from exc

    if not isinstance(pdf_bytes, bytes):
        raise PdfIngestionError("PDF download did not return bytes.")
    return pdf_bytes


def _extract_pdf_pages(pdf_bytes: bytes) -> list[ExtractedPdfPage]:
    try:
        document = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise PdfIngestionError(f"PDF extraction failed: {exc}") from exc

    try:
        return [
            ExtractedPdfPage(
                page_number=page.number + 1,
                text=_normalize_page_text(page.get_text("text")),
            )
            for page in document
        ]
    except Exception as exc:
        raise PdfIngestionError(f"PDF extraction failed: {exc}") from exc
    finally:
        document.close()


def _replace_document_chunks(
    client: SupabasePdfIngestionClient,
    document_id: UUID,
    chunks: list[PdfDocumentChunk],
) -> None:
    (
        client.table("document_chunks")
        .delete()
        .eq("document_id", str(document_id))
        .execute()
    )
    client.table("document_chunks").insert(
        [chunk.to_payload() for chunk in chunks]
    ).execute()


def _update_document_parse_status(
    client: SupabasePdfIngestionClient,
    *,
    document_id: UUID,
    parse_status: str,
    metadata: dict[str, Any],
) -> None:
    (
        client.table("documents")
        .update({"parse_status": parse_status, "metadata": metadata})
        .eq("id", str(document_id))
        .execute()
    )


def _source_metadata(
    document_row: Mapping[str, Any],
    document_id: UUID,
) -> dict[str, Any]:
    row_metadata = document_row.get("metadata")
    metadata = dict(row_metadata) if isinstance(row_metadata, Mapping) else {}
    metadata.setdefault("source_label", _default_source_label(document_row))
    metadata["storage_path"] = document_row.get("storage_path")
    metadata["original_filename"] = document_row.get("original_filename")
    metadata["source_document_id"] = str(document_id)
    return metadata


def _source_label(source_metadata: Mapping[str, Any]) -> str:
    source_label = source_metadata.get("source_label")
    if isinstance(source_label, str) and source_label.strip():
        return source_label.strip()
    return "tender PDF"


def _default_source_label(document_row: Mapping[str, Any]) -> str:
    filename = document_row.get("original_filename")
    if isinstance(filename, str) and filename.strip():
        return filename.strip()
    return "tender PDF"


def _split_page_text(text: str, *, max_chunk_chars: int) -> list[str]:
    normalized = _normalize_page_text(text)
    if not normalized:
        return []

    chunks: list[str] = []
    remaining = normalized
    while len(remaining) > max_chunk_chars:
        split_at = _boundary_index(remaining, max_chunk_chars)
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()

    if remaining:
        chunks.append(remaining)
    return chunks


def _boundary_index(text: str, max_chunk_chars: int) -> int:
    window = text[: max_chunk_chars + 1]
    candidates = [
        window.rfind("\n\n"),
        window.rfind("\n"),
        window.rfind(". "),
        window.rfind(" "),
    ]
    minimum_boundary = max(1, max_chunk_chars // 2)
    for candidate in candidates:
        if candidate >= minimum_boundary:
            return candidate + 1
    return max_chunk_chars


def _normalize_page_text(text: str) -> str:
    lines = [line.strip() for line in text.replace("\r\n", "\n").split("\n")]
    normalized = "\n".join(line for line in lines).strip()
    return re.sub(r"\n{3,}", "\n\n", normalized)


def _normalize_uuid(value: UUID | str, field_name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except ValueError as exc:
        raise PdfIngestionError(f"{field_name} must be a UUID.") from exc


__all__ = [
    "ExtractedPdfPage",
    "PdfDocumentChunk",
    "PdfIngestionError",
    "PdfIngestionResult",
    "build_document_chunks",
    "ingest_tender_pdf_document",
]
