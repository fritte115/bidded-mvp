from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

import fitz

from bidded.documents.chunk_embeddings import (
    ChunkEmbeddingAdapter,
    ChunkEmbeddingError,
    DocumentChunkEmbeddingResult,
    populate_document_chunk_embeddings,
)
from bidded.documents.tender_registration import DOCX_CONTENT_TYPE, PDF_CONTENT_TYPE
from bidded.evidence.company_kb import ensure_company_kb_evidence_items_for_document
from bidded.evidence.tender_document import (
    TenderEvidenceUpsertResult,
    build_tender_evidence_candidates,
    upsert_tender_evidence_items,
)
from bidded.retrieval import list_document_chunks_for_document

DEMO_TENANT_KEY = "demo"
UNSUPPORTED_DOCUMENT_MESSAGE = (
    "Only text-based PDF and DOCX ingestion are supported; OCR, legacy DOC, "
    "and RTF are non-goals for Bidded v1."
)
DEFAULT_MAX_CHUNK_CHARS = 1800
CHUNKING_STRATEGY = "page_text_char_budget_v1"
DEFAULT_DOCX_CONVERSION_TIMEOUT_SECONDS = 30


class PdfIngestionError(RuntimeError):
    """Raised when a tender document cannot be parsed into document chunks."""


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


class DocxPdfConverter(Protocol):
    name: str

    def convert_docx_to_pdf(self, docx_bytes: bytes) -> bytes: ...


@dataclass(frozen=True)
class TenderDocumentFormat:
    source_format: str
    source_content_type: str
    parser: str = "pymupdf"
    conversion_tool: str | None = None


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
    embedding_result: DocumentChunkEmbeddingResult | None = None


def ingest_tender_pdf_document(
    client: SupabasePdfIngestionClient,
    *,
    document_id: UUID | str,
    bucket_name: str,
    max_chunk_chars: int = DEFAULT_MAX_CHUNK_CHARS,
    embedding_adapter: ChunkEmbeddingAdapter | None = None,
    require_embeddings: bool = False,
) -> PdfIngestionResult:
    """Parse a registered tender text-PDF and persist page-referenced chunks."""
    return ingest_tender_document(
        client,
        document_id=document_id,
        bucket_name=bucket_name,
        max_chunk_chars=max_chunk_chars,
        embedding_adapter=embedding_adapter,
        require_embeddings=require_embeddings,
        allowed_source_formats=("pdf",),
    )


def ingest_tender_document(
    client: SupabasePdfIngestionClient,
    *,
    document_id: UUID | str,
    bucket_name: str,
    max_chunk_chars: int = DEFAULT_MAX_CHUNK_CHARS,
    embedding_adapter: ChunkEmbeddingAdapter | None = None,
    require_embeddings: bool = False,
    docx_pdf_converter: DocxPdfConverter | None = None,
    allowed_source_formats: tuple[str, ...] = ("pdf", "docx"),
) -> PdfIngestionResult:
    """Parse a registered tender PDF or DOCX and persist page-referenced chunks."""

    normalized_document_id = _normalize_uuid(document_id, "document_id")
    if max_chunk_chars <= 0:
        raise PdfIngestionError("max_chunk_chars must be greater than zero.")

    document_row = _fetch_tender_document(client, normalized_document_id)
    source_metadata = _source_metadata(document_row, normalized_document_id)
    document_format: TenderDocumentFormat | None = None

    try:
        document_format = _document_format(
            document_row,
            allowed_source_formats=allowed_source_formats,
        )
        _update_document_parse_status(
            client,
            document_id=normalized_document_id,
            parse_status="parsing",
            metadata={
                **source_metadata,
                "parser": _parser_metadata(
                    status="parsing",
                    document_format=document_format,
                ),
            },
        )
        document_bytes = _download_document_bytes(
            client,
            bucket_name=bucket_name,
            storage_path=str(document_row["storage_path"]),
        )
        pdf_bytes, document_format = _pdf_bytes_for_document(
            document_bytes,
            document_format=document_format,
            docx_pdf_converter=docx_pdf_converter,
        )
        pages = _extract_pdf_pages(pdf_bytes)
        source_metadata = {
            **source_metadata,
            "source_format": document_format.source_format,
            "source_content_type": document_format.source_content_type,
        }
        if document_format.conversion_tool is not None:
            source_metadata["conversion_tool"] = document_format.conversion_tool
        chunks = build_document_chunks(
            document_id=normalized_document_id,
            pages=pages,
            source_metadata=source_metadata,
            max_chunk_chars=max_chunk_chars,
        )
        if not chunks:
            raise PdfIngestionError(
                "No extractable text found in document. Text-based PDFs or "
                "convertible DOCX files are required; OCR is a non-goal for "
                "Bidded v1."
            )

        _replace_document_chunks(client, normalized_document_id, chunks)
        embedding_result = _populate_chunk_embeddings(
            client,
            document_id=normalized_document_id,
            embedding_adapter=embedding_adapter,
            require_embeddings=require_embeddings,
        )
        ensure_tender_evidence_items_for_document(
            client,
            document_id=normalized_document_id,
        )
        parsed_metadata: dict[str, Any] = {
            **source_metadata,
            "parser": _parser_metadata(
                status="parsed",
                document_format=document_format,
                page_count=len(pages),
                chunk_count=len(chunks),
                chunking_strategy=CHUNKING_STRATEGY,
            ),
        }
        if embedding_result is not None:
            parsed_metadata["embedding"] = embedding_result.parser_metadata()
        _update_document_parse_status(
            client,
            document_id=normalized_document_id,
            parse_status="parsed",
            metadata=parsed_metadata,
        )
        return PdfIngestionResult(
            document_id=normalized_document_id,
            page_count=len(pages),
            chunk_count=len(chunks),
            chunks=chunks,
            embedding_result=embedding_result,
        )
    except PdfIngestionError as exc:
        _update_document_parse_status(
            client,
            document_id=normalized_document_id,
            parse_status="parser_failed",
            metadata={
                **source_metadata,
                "parser": _parser_metadata(
                    status="parser_failed",
                    document_format=document_format
                    or _fallback_document_format(document_row),
                    error_message=str(exc),
                ),
            },
        )
        raise


def ingest_company_kb_pdf_document(
    client: SupabasePdfIngestionClient,
    *,
    document_id: UUID | str,
    bucket_name: str,
    max_chunk_chars: int = DEFAULT_MAX_CHUNK_CHARS,
    embedding_adapter: ChunkEmbeddingAdapter | None = None,
    require_embeddings: bool = False,
) -> PdfIngestionResult:
    """Parse a registered company KB text-PDF and persist company evidence."""

    normalized_document_id = _normalize_uuid(document_id, "document_id")
    if max_chunk_chars <= 0:
        raise PdfIngestionError("max_chunk_chars must be greater than zero.")

    document_row = _fetch_company_kb_document(client, normalized_document_id)
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
        embedding_result = _populate_chunk_embeddings(
            client,
            document_id=normalized_document_id,
            embedding_adapter=embedding_adapter,
            require_embeddings=require_embeddings,
        )
        ensure_company_kb_evidence_items_for_document(
            client,
            document_id=normalized_document_id,
        )
        parsed_metadata: dict[str, Any] = {
            **source_metadata,
            "parser": {
                "status": "parsed",
                "parser": "pymupdf",
                "page_count": len(pages),
                "chunk_count": len(chunks),
                "chunking_strategy": CHUNKING_STRATEGY,
                "non_goals": ["ocr", "docx"],
            },
        }
        if embedding_result is not None:
            parsed_metadata["embedding"] = embedding_result.parser_metadata()
        _update_document_parse_status(
            client,
            document_id=normalized_document_id,
            parse_status="parsed",
            metadata=parsed_metadata,
        )
        return PdfIngestionResult(
            document_id=normalized_document_id,
            page_count=len(pages),
            chunk_count=len(chunks),
            chunks=chunks,
            embedding_result=embedding_result,
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


def _populate_chunk_embeddings(
    client: SupabasePdfIngestionClient,
    *,
    document_id: UUID,
    embedding_adapter: ChunkEmbeddingAdapter | None,
    require_embeddings: bool,
) -> DocumentChunkEmbeddingResult | None:
    if embedding_adapter is None:
        if require_embeddings:
            raise PdfIngestionError(
                "Embedding adapter is required when embeddings are required."
            )
        return None

    try:
        return populate_document_chunk_embeddings(
            client,
            document_id=document_id,
            embedding_adapter=embedding_adapter,
            require_embeddings=require_embeddings,
        )
    except ChunkEmbeddingError as exc:
        raise PdfIngestionError(str(exc)) from exc


def ensure_tender_evidence_items_for_document(
    client: SupabasePdfIngestionClient,
    *,
    document_id: UUID | str,
) -> TenderEvidenceUpsertResult:
    """Materialize deterministic tender evidence rows for one parsed document."""

    normalized_document_id = _normalize_uuid(document_id, "document_id")
    chunks = list_document_chunks_for_document(
        client,
        document_id=normalized_document_id,
        tenant_key=DEMO_TENANT_KEY,
    )
    candidates = build_tender_evidence_candidates(chunks)
    return upsert_tender_evidence_items(
        client,
        candidates,
        tenant_key=DEMO_TENANT_KEY,
    )


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
                        "procurement_document_role": source_metadata.get(
                            "procurement_document_role"
                        ),
                        "parser": "pymupdf",
                        "source_format": source_metadata.get("source_format"),
                        "source_content_type": source_metadata.get(
                            "source_content_type"
                        ),
                        "conversion_tool": source_metadata.get("conversion_tool"),
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
    row = _fetch_registered_pdf_document(client, document_id)
    if row.get("document_role") != "tender_document":
        raise PdfIngestionError(f"Document is not a tender_document: {document_id}")
    return row


def _fetch_company_kb_document(
    client: SupabasePdfIngestionClient,
    document_id: UUID,
) -> dict[str, Any]:
    row = _fetch_registered_pdf_document(client, document_id)
    if row.get("document_role") != "company_profile":
        raise PdfIngestionError(
            f"Document is not a company_profile document: {document_id}"
        )
    return row


def _fetch_registered_pdf_document(
    client: SupabasePdfIngestionClient,
    document_id: UUID,
) -> dict[str, Any]:
    response = (
        client.table("documents")
        .select(
            "id,tenant_key,tender_id,company_id,storage_path,content_type,"
            "document_role,parse_status,original_filename,metadata,checksum_sha256"
        )
        .eq("id", str(document_id))
        .eq("tenant_key", DEMO_TENANT_KEY)
        .execute()
    )
    data = getattr(response, "data", None)
    if isinstance(data, list) and data and isinstance(data[0], Mapping):
        return dict(data[0])

    raise PdfIngestionError(f"PDF document does not exist: {document_id}")


class LibreOfficeDocxPdfConverter:
    name = "libreoffice"

    def __init__(
        self,
        *,
        executable_path: str | None = None,
        timeout_seconds: int = DEFAULT_DOCX_CONVERSION_TIMEOUT_SECONDS,
    ) -> None:
        self.executable_path = executable_path
        self.timeout_seconds = timeout_seconds

    def convert_docx_to_pdf(self, docx_bytes: bytes) -> bytes:
        executable = self.executable_path or shutil.which("soffice") or shutil.which(
            "libreoffice"
        )
        if not executable:
            raise PdfIngestionError(
                "DOCX conversion requires LibreOffice/soffice on the worker PATH."
            )

        with tempfile.TemporaryDirectory(prefix="bidded-docx-") as temp_dir:
            work_dir = Path(temp_dir)
            input_path = work_dir / "input.docx"
            output_dir = work_dir / "out"
            profile_dir = work_dir / "lo-profile"
            output_dir.mkdir()
            profile_dir.mkdir()
            input_path.write_bytes(docx_bytes)
            command = [
                executable,
                f"-env:UserInstallation={profile_dir.as_uri()}",
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(output_dir),
                str(input_path),
            ]
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    check=False,
                    text=True,
                    timeout=self.timeout_seconds,
                )
            except subprocess.TimeoutExpired as exc:
                raise PdfIngestionError(
                    f"DOCX conversion timed out after {self.timeout_seconds} seconds."
                ) from exc
            except OSError as exc:
                raise PdfIngestionError(f"DOCX conversion failed: {exc}") from exc

            if completed.returncode != 0:
                message = (completed.stderr or completed.stdout or "").strip()
                if not message:
                    message = f"LibreOffice exited with code {completed.returncode}."
                raise PdfIngestionError(f"DOCX conversion failed: {message}")

            output_path = output_dir / "input.pdf"
            if not output_path.exists():
                pdf_outputs = sorted(output_dir.glob("*.pdf"))
                if not pdf_outputs:
                    raise PdfIngestionError(
                        "DOCX conversion failed: LibreOffice produced no PDF output."
                    )
                output_path = pdf_outputs[0]
            pdf_bytes = output_path.read_bytes()
            if not pdf_bytes.startswith(b"%PDF-"):
                raise PdfIngestionError(
                    "DOCX conversion failed: LibreOffice output was not a PDF."
                )
            return pdf_bytes


def _document_format(
    document_row: Mapping[str, Any],
    *,
    allowed_source_formats: tuple[str, ...],
) -> TenderDocumentFormat:
    content_type = str(document_row.get("content_type") or "")
    filename = str(document_row.get("original_filename") or "")
    storage_path = str(document_row.get("storage_path") or "")
    lowered_name = f"{filename} {storage_path}".lower()

    if lowered_name.endswith(".doc") or content_type == "application/msword":
        raise PdfIngestionError(
            "Legacy DOC is not supported. Upload a PDF or modern .docx document."
        )
    if lowered_name.endswith(".rtf") or content_type == "application/rtf":
        raise PdfIngestionError(
            "RTF is not supported. Upload a PDF or modern .docx document."
        )

    if content_type == PDF_CONTENT_TYPE or lowered_name.endswith(".pdf"):
        source_format = "pdf"
        source_content_type = PDF_CONTENT_TYPE
    elif content_type == DOCX_CONTENT_TYPE or lowered_name.endswith(".docx"):
        source_format = "docx"
        source_content_type = DOCX_CONTENT_TYPE
    else:
        raise PdfIngestionError(UNSUPPORTED_DOCUMENT_MESSAGE)

    if source_format not in allowed_source_formats:
        if source_format == "docx":
            raise PdfIngestionError(
                "DOCX documents are supported by ingest_tender_document; "
                "ingest_tender_pdf_document only accepts PDFs."
            )
        raise PdfIngestionError(UNSUPPORTED_DOCUMENT_MESSAGE)

    return TenderDocumentFormat(
        source_format=source_format,
        source_content_type=source_content_type,
    )


def _fallback_document_format(document_row: Mapping[str, Any]) -> TenderDocumentFormat:
    content_type = str(document_row.get("content_type") or "")
    filename = str(document_row.get("original_filename") or "")
    storage_path = str(document_row.get("storage_path") or "")
    lowered_name = f"{filename} {storage_path}".lower()
    if content_type == DOCX_CONTENT_TYPE or lowered_name.endswith(".docx"):
        return TenderDocumentFormat("docx", DOCX_CONTENT_TYPE)
    if content_type == PDF_CONTENT_TYPE or lowered_name.endswith(".pdf"):
        return TenderDocumentFormat("pdf", PDF_CONTENT_TYPE)
    if content_type == "application/msword" or lowered_name.endswith(".doc"):
        return TenderDocumentFormat("doc", content_type or "application/msword")
    return TenderDocumentFormat("unsupported", content_type or "unknown")


def _parser_metadata(
    *,
    status: str,
    document_format: TenderDocumentFormat,
    **extra: Any,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "status": status,
        "parser": document_format.parser,
        "source_format": document_format.source_format,
        "source_content_type": document_format.source_content_type,
        "non_goals": ["ocr", "legacy_doc", "rtf"],
    }
    if document_format.conversion_tool is not None:
        metadata["conversion_tool"] = document_format.conversion_tool
    metadata.update(extra)
    return metadata


def _pdf_bytes_for_document(
    document_bytes: bytes,
    *,
    document_format: TenderDocumentFormat,
    docx_pdf_converter: DocxPdfConverter | None,
) -> tuple[bytes, TenderDocumentFormat]:
    if document_format.source_format == "pdf":
        return document_bytes, document_format

    converter = docx_pdf_converter or LibreOfficeDocxPdfConverter()
    pdf_bytes = converter.convert_docx_to_pdf(document_bytes)
    return (
        pdf_bytes,
        TenderDocumentFormat(
            source_format=document_format.source_format,
            source_content_type=document_format.source_content_type,
            parser=document_format.parser,
            conversion_tool=converter.name,
        ),
    )


def _ensure_text_pdf_document(document_row: Mapping[str, Any]) -> None:
    _document_format(document_row, allowed_source_formats=("pdf",))


def _download_document_bytes(
    client: SupabasePdfIngestionClient,
    *,
    bucket_name: str,
    storage_path: str,
) -> bytes:
    try:
        document_bytes = client.storage.from_(bucket_name).download(storage_path)
    except Exception as exc:  # pragma: no cover - depends on Supabase internals
        raise PdfIngestionError(f"Document download failed: {exc}") from exc

    if not isinstance(document_bytes, bytes):
        raise PdfIngestionError("Document download did not return bytes.")
    return document_bytes


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
    metadata["content_type"] = document_row.get("content_type")
    metadata["source_document_id"] = str(document_id)
    return metadata


def _source_label(source_metadata: Mapping[str, Any]) -> str:
    source_label = source_metadata.get("source_label")
    if isinstance(source_label, str) and source_label.strip():
        return source_label.strip()
    return "tender document"


def _default_source_label(document_row: Mapping[str, Any]) -> str:
    filename = document_row.get("original_filename")
    if isinstance(filename, str) and filename.strip():
        return filename.strip()
    return "tender document"


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
    "DocxPdfConverter",
    "ExtractedPdfPage",
    "LibreOfficeDocxPdfConverter",
    "PdfDocumentChunk",
    "PdfIngestionError",
    "PdfIngestionResult",
    "build_document_chunks",
    "ensure_tender_evidence_items_for_document",
    "ingest_tender_document",
    "ingest_tender_pdf_document",
]
