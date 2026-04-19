"""Text-PDF document registration, extraction, and chunking boundaries."""

from bidded.documents.chunk_embeddings import (
    ChunkEmbeddingAdapter,
    ChunkEmbeddingError,
    DocumentChunkEmbeddingResult,
    populate_document_chunk_embeddings,
)
from bidded.documents.pdf_ingestion import (
    ExtractedPdfPage,
    PdfDocumentChunk,
    PdfIngestionError,
    PdfIngestionResult,
    build_document_chunks,
    ensure_tender_evidence_items_for_document,
    ingest_tender_pdf_document,
)
from bidded.documents.tender_registration import (
    TenderPdfRegistrationError,
    TenderPdfRegistrationResult,
    register_demo_tender_pdf,
)

__all__ = [
    "ChunkEmbeddingAdapter",
    "ChunkEmbeddingError",
    "DocumentChunkEmbeddingResult",
    "ExtractedPdfPage",
    "PdfDocumentChunk",
    "PdfIngestionError",
    "PdfIngestionResult",
    "TenderPdfRegistrationError",
    "TenderPdfRegistrationResult",
    "build_document_chunks",
    "ensure_tender_evidence_items_for_document",
    "ingest_tender_pdf_document",
    "populate_document_chunk_embeddings",
    "register_demo_tender_pdf",
]
