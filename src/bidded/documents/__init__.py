"""Text-PDF document registration, extraction, and chunking boundaries."""

from bidded.documents.tender_registration import (
    TenderPdfRegistrationError,
    TenderPdfRegistrationResult,
    register_demo_tender_pdf,
)

__all__ = [
    "TenderPdfRegistrationError",
    "TenderPdfRegistrationResult",
    "register_demo_tender_pdf",
]
