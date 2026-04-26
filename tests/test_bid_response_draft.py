from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from bidded.orchestration.bid_response_draft import (
    BidResponseDraftError,
    generate_bid_response_draft,
)

RUN_ID = "11111111-1111-4111-8111-111111111111"
TENDER_ID = "22222222-2222-4222-8222-222222222222"
COMPANY_ID = "33333333-3333-4333-8333-333333333333"
BID_ID = "44444444-4444-4444-8444-444444444444"
TENDER_DOC_ID = "55555555-5555-4555-8555-555555555555"
COMPANY_DOC_ID = "66666666-6666-4666-8666-666666666666"


class DraftQuery:
    def __init__(self, client: DraftClient, table_name: str) -> None:
        self.client = client
        self.table_name = table_name
        self.filters: list[tuple[str, str]] = []
        self.limit_count: int | None = None
        self.order_column: str | None = None
        self.order_desc = False
        self.insert_payload: dict[str, Any] | None = None

    def select(self, _columns: str) -> DraftQuery:
        return self

    def eq(self, column: str, value: object) -> DraftQuery:
        self.filters.append((column, str(value)))
        return self

    def order(self, column: str, *, desc: bool = False) -> DraftQuery:
        self.order_column = column
        self.order_desc = desc
        return self

    def limit(self, row_limit: int) -> DraftQuery:
        self.limit_count = row_limit
        return self

    def insert(self, payload: dict[str, Any]) -> DraftQuery:
        self.insert_payload = payload
        return self

    def execute(self) -> object:
        if self.insert_payload is not None:
            row = {"id": "77777777-7777-4777-8777-777777777777", **self.insert_payload}
            self.client.rows.setdefault(self.table_name, []).append(row)
            self.client.inserts.setdefault(self.table_name, []).append(row)
            return type("Response", (), {"data": [row]})()

        rows = [
            row
            for row in self.client.rows.get(self.table_name, [])
            if all(str(row.get(column)) == value for column, value in self.filters)
        ]
        if self.order_column is not None:
            rows = sorted(
                rows,
                key=lambda row: str(row.get(self.order_column) or ""),
                reverse=self.order_desc,
            )
        if self.limit_count is not None:
            rows = rows[: self.limit_count]
        return type("Response", (), {"data": rows})()


class DraftStorageBucket:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files
        self.downloads: list[str] = []

    def download(self, path: str) -> bytes:
        self.downloads.append(path)
        return self.files[path]


class DraftStorage:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.bucket_names: list[str] = []
        self.bucket = DraftStorageBucket(files)

    def from_(self, bucket_name: str) -> DraftStorageBucket:
        self.bucket_names.append(bucket_name)
        return self.bucket


class DraftClient:
    def __init__(self, *, include_company_attachment: bool = True) -> None:
        company_evidence = (
            [
                {
                    "id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                    "tenant_key": "demo",
                    "evidence_key": "COMPANY-KB-ISO-27001",
                    "source_type": "company_profile",
                    "excerpt": "ISO/IEC 27001 certificate valid through 2027.",
                    "normalized_meaning": (
                        "The company has a valid ISO 27001 certificate."
                    ),
                    "category": "certification",
                    "confidence": 0.94,
                    "source_metadata": {
                        "source_label": "ISO 27001 certificate",
                        "source_document_id": COMPANY_DOC_ID,
                    },
                    "company_id": COMPANY_ID,
                    "field_path": f"kb_documents.{COMPANY_DOC_ID}.chunks[0]",
                    "metadata": {
                        "attachment_type": "certificate",
                        "source_document_id": COMPANY_DOC_ID,
                        "source_storage_path": "demo/company-kb/iso.pdf",
                        "source_original_filename": "iso.pdf",
                    },
                }
            ]
            if include_company_attachment
            else []
        )
        self.rows: dict[str, list[dict[str, Any]]] = {
            "agent_runs": [
                {
                    "id": RUN_ID,
                    "tenant_key": "demo",
                    "tender_id": TENDER_ID,
                    "company_id": COMPANY_ID,
                    "run_config": {"language_policy": {"output_language": "en"}},
                    "metadata": {},
                }
            ],
            "tenders": [
                {
                    "id": TENDER_ID,
                    "tenant_key": "demo",
                    "title": "Identity platform",
                    "language_policy": {"draft_language": "sv"},
                }
            ],
            "companies": [
                {
                    "id": COMPANY_ID,
                    "tenant_key": "demo",
                    "financial_assumptions": {
                        "target_gross_margin_percent": 22,
                    },
                }
            ],
            "documents": [
                {
                    "id": TENDER_DOC_ID,
                    "tenant_key": "demo",
                    "tender_id": TENDER_ID,
                    "company_id": None,
                    "document_role": "tender_document",
                    "storage_path": "demo/tenders/main.pdf",
                    "checksum_sha256": "a" * 64,
                    "original_filename": "main.pdf",
                    "metadata": {"source_label": "Main tender"},
                },
                {
                    "id": COMPANY_DOC_ID,
                    "tenant_key": "demo",
                    "tender_id": None,
                    "company_id": COMPANY_ID,
                    "document_role": "company_profile",
                    "storage_path": "demo/company-kb/iso.pdf",
                    "checksum_sha256": "b" * 64,
                    "original_filename": "iso.pdf",
                    "metadata": {
                        "source_label": "ISO 27001 certificate",
                        "kb_attachment_type": "certificate",
                        "approved_for_bid_drafts": True,
                    },
                },
            ],
            "bid_decisions": [
                {
                    "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                    "tenant_key": "demo",
                    "agent_run_id": RUN_ID,
                    "verdict": "conditional_bid",
                    "confidence": 0.76,
                    "final_decision": {
                        "verdict": "conditional_bid",
                        "confidence": 0.76,
                        "cited_memo": "Conditional bid with ISO attachment.",
                        "missing_info": ["Confirm named project manager."],
                        "recommended_actions": ["Attach ISO certificate."],
                    },
                }
            ],
            "bids": [
                {
                    "id": BID_ID,
                    "tenant_key": "demo",
                    "tender_id": TENDER_ID,
                    "agent_run_id": RUN_ID,
                    "rate_sek": 1330,
                    "margin_pct": 14,
                    "hours_estimated": 800,
                    "updated_at": "2026-04-23T10:00:00Z",
                }
            ],
            "evidence_items": [
                {
                    "id": "99999999-9999-4999-8999-999999999999",
                    "tenant_key": "demo",
                    "evidence_key": "TENDER-ISO-CERT",
                    "source_type": "tender_document",
                    "excerpt": "Anbudet ska innehålla ISO 27001-certifikat.",
                    "normalized_meaning": (
                        "The tender requires an ISO 27001 certificate."
                    ),
                    "category": "required_submission_document",
                    "requirement_type": "submission_document",
                    "confidence": 0.91,
                    "source_metadata": {"source_label": "Main tender"},
                    "document_id": TENDER_DOC_ID,
                    "chunk_id": "aaaaaaaa-0000-4000-8000-000000000000",
                    "page_start": 4,
                    "page_end": 4,
                    "metadata": {},
                },
                *company_evidence,
            ],
            "bid_response_drafts": [],
        }
        self.inserts: dict[str, list[dict[str, Any]]] = {}
        self.storage = DraftStorage({"demo/company-kb/iso.pdf": b"%PDF-iso"})

    def table(self, table_name: str) -> DraftQuery:
        return DraftQuery(self, table_name)


def test_generate_bid_response_draft_uses_saved_price_and_attaches_kb_pdf(
    tmp_path: Path,
) -> None:
    client = DraftClient()

    draft = generate_bid_response_draft(
        client,
        run_id=RUN_ID,
        bid_id=BID_ID,
        storage_bucket="public-procurements",
        packet_dir=tmp_path / "packet",
    )

    assert draft.language == "sv"
    assert draft.status == "needs_review"
    assert draft.pricing.source == "bid_row"
    assert draft.pricing.rate_sek == 1330
    assert draft.pricing.total_value_sek == 1_064_000
    assert draft.answers[0].status == "drafted"
    assert draft.answers[0].evidence_keys == [
        "TENDER-ISO-CERT",
        "COMPANY-KB-ISO-27001",
    ]
    assert draft.attachments[0].status == "attached"
    assert draft.attachments[0].attachment_type == "certificate"
    assert draft.attachments[0].storage_path == "demo/company-kb/iso.pdf"
    assert Path(draft.attachments[0].packet_path or "").read_bytes() == b"%PDF-iso"

    persisted = client.inserts["bid_response_drafts"][0]
    assert persisted["agent_run_id"] == RUN_ID
    assert persisted["bid_id"] == BID_ID
    assert persisted["pricing_snapshot"]["source"] == "bid_row"
    assert persisted["attachment_manifest"][0]["status"] == "attached"


def test_generate_bid_response_draft_marks_missing_required_attachment() -> None:
    client = DraftClient(include_company_attachment=False)

    draft = generate_bid_response_draft(client, run_id=RUN_ID)

    assert draft.pricing.source == "bid_row"
    assert draft.answers[0].status == "needs_input"
    assert [attachment.model_dump() for attachment in draft.attachments] == [
        {
            "filename": "certificate required by TENDER-ISO-CERT",
            "storage_path": None,
            "checksum_sha256": None,
            "attachment_type": "certificate",
            "required_by_evidence_key": "TENDER-ISO-CERT",
            "status": "missing",
            "source_evidence_keys": ["TENDER-ISO-CERT"],
            "packet_path": None,
        }
    ]
    assert "Missing certificate attachment for TENDER-ISO-CERT." in draft.missing_info


def test_generate_bid_response_draft_answers_from_company_kb_evidence() -> None:
    client = DraftClient()
    client.rows["evidence_items"] = [
        {
            "id": "12121212-1212-4212-8212-121212121212",
            "tenant_key": "demo",
            "evidence_key": "TENDER-IAM-EXPERIENCE",
            "source_type": "tender_document",
            "excerpt": "Leverantören ska beskriva erfarenhet av IAM-plattformar.",
            "normalized_meaning": (
                "The tender asks for IAM platform delivery experience."
            ),
            "category": "delivery_capability",
            "requirement_type": "shall_requirement",
            "confidence": 0.9,
            "source_metadata": {"source_label": "Main tender"},
            "document_id": TENDER_DOC_ID,
            "chunk_id": "aaaaaaaa-0000-4000-8000-000000000000",
            "page_start": 6,
            "page_end": 6,
            "metadata": {},
        },
        {
            "id": "13131313-1313-4313-8313-131313131313",
            "tenant_key": "demo",
            "evidence_key": "COMPANY-KB-IAM-REFERENCE",
            "source_type": "company_profile",
            "excerpt": "Company delivered IAM platforms for public-sector clients.",
            "normalized_meaning": (
                "The company has delivered IAM platforms for public-sector clients."
            ),
            "category": "delivery_capability",
            "confidence": 0.89,
            "source_metadata": {
                "source_label": "IAM reference case",
                "source_document_id": COMPANY_DOC_ID,
            },
            "company_id": COMPANY_ID,
            "field_path": f"kb_documents.{COMPANY_DOC_ID}.chunks[1]",
            "metadata": {
                "attachment_type": "other",
                "source_document_id": COMPANY_DOC_ID,
            },
        },
    ]

    draft = generate_bid_response_draft(client, run_id=RUN_ID)

    assert draft.answers[0].status == "drafted"
    assert draft.answers[0].evidence_keys == [
        "TENDER-IAM-EXPERIENCE",
        "COMPANY-KB-IAM-REFERENCE",
    ]
    assert "IAM reference case" in draft.answers[0].answer


def test_generate_bid_response_draft_marks_unsupported_answer_needs_input() -> None:
    client = DraftClient(include_company_attachment=False)
    client.rows["evidence_items"] = [
        {
            "id": "14141414-1414-4414-8414-141414141414",
            "tenant_key": "demo",
            "evidence_key": "TENDER-IAM-EXPERIENCE",
            "source_type": "tender_document",
            "excerpt": "Leverantören ska beskriva erfarenhet av IAM-plattformar.",
            "normalized_meaning": (
                "The tender asks for IAM platform delivery experience."
            ),
            "category": "delivery_capability",
            "requirement_type": "shall_requirement",
            "confidence": 0.9,
            "source_metadata": {"source_label": "Main tender"},
            "document_id": TENDER_DOC_ID,
            "chunk_id": "aaaaaaaa-0000-4000-8000-000000000000",
            "page_start": 6,
            "page_end": 6,
            "metadata": {},
        }
    ]

    draft = generate_bid_response_draft(client, run_id=RUN_ID)

    assert draft.answers[0].status == "needs_input"
    assert draft.answers[0].evidence_keys == ["TENDER-IAM-EXPERIENCE"]
    assert (
        "Missing approved company evidence for TENDER-IAM-EXPERIENCE."
        in draft.missing_info
    )


def test_generate_bid_response_draft_falls_back_to_swedish_and_estimator() -> None:
    client = DraftClient()
    client.rows["tenders"][0]["language_policy"] = {}
    client.rows["bids"] = []

    draft = generate_bid_response_draft(client, run_id=RUN_ID)

    assert draft.language == "sv"
    assert draft.pricing.source == "estimator"
    assert draft.pricing.rate_sek > 0
    assert draft.pricing.hours_estimated == 1600


def test_generate_bid_response_draft_refuses_no_bid_decision() -> None:
    client = DraftClient()
    client.rows["bid_decisions"][0]["verdict"] = "no_bid"
    client.rows["bid_decisions"][0]["final_decision"]["verdict"] = "no_bid"

    with pytest.raises(BidResponseDraftError, match="no_bid"):
        generate_bid_response_draft(client, run_id=RUN_ID)
