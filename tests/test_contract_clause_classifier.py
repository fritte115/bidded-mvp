from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

from bidded.evidence.contract_clause_classifier import (
    ContractClauseClassificationRequest,
    ContractClauseProvenance,
    MockContractClauseClassifier,
    classify_contract_clause,
)

DOCUMENT_ID = UUID("11111111-1111-1111-1111-111111111111")
CHUNK_ID = UUID("22222222-2222-2222-2222-222222222222")


def _classification_request() -> ContractClauseClassificationRequest:
    return ContractClauseClassificationRequest(
        evidence_key="TENDER-P8-contract-risk-ABC12345",
        document_id=DOCUMENT_ID,
        chunk_id=CHUNK_ID,
        page_start=8,
        page_end=8,
        excerpt=(
            "The supplier's aggregate financial exposure is limited to twelve "
            "months of fees."
        ),
        source_label="Tender.pdf",
        clause_provenance=ContractClauseProvenance(
            document_id=DOCUMENT_ID,
            section_number="8",
            heading="Commercial exposure",
            page_start=8,
            page_end=8,
            chunk_ids=(CHUNK_ID,),
        ),
    )


def test_clause_classifier_accepts_known_tag_with_evidence_key() -> None:
    request = _classification_request()

    classification = classify_contract_clause(
        request,
        lambda received: {
            "tag_id": "liability_caps",
            "confidence": 0.84,
            "rationale": "The clause limits aggregate financial exposure.",
            "evidence_key": received.evidence_key,
        },
    )

    assert classification.tag_id == "liability_caps"
    assert classification.confidence == 0.84
    assert classification.rationale == (
        "The clause limits aggregate financial exposure."
    )
    assert classification.evidence_key == request.evidence_key


def test_clause_classifier_rejects_unknown_tag_id() -> None:
    with pytest.raises(ValidationError):
        classify_contract_clause(
            _classification_request(),
            lambda received: {
                "tag_id": "uncapped_financial_exposure",
                "confidence": 0.91,
                "rationale": "Free-form tags are not allowed.",
                "evidence_key": received.evidence_key,
            },
        )


def test_clause_classifier_rejects_known_tag_outside_request_allow_list() -> None:
    request = _classification_request().model_copy(
        update={"allowed_tag_ids": ("liability_caps", "unknown_contract_clause")}
    )

    with pytest.raises(ValueError, match="allowed_tag_ids"):
        classify_contract_clause(
            request,
            lambda received: {
                "tag_id": "gdpr_dpa",
                "confidence": 0.87,
                "rationale": "The clause mentions data processing duties.",
                "evidence_key": received.evidence_key,
            },
        )


def test_clause_classifier_rejects_missing_request_citation() -> None:
    with pytest.raises(ValueError, match="request evidence key or clause provenance"):
        classify_contract_clause(
            _classification_request(),
            lambda _received: {
                "tag_id": "liability_caps",
                "confidence": 0.81,
                "rationale": "The clause limits aggregate financial exposure.",
                "evidence_key": "TENDER-P9-unrelated-99999999",
            },
        )


def test_clause_classifier_falls_back_to_unknown_for_low_confidence() -> None:
    classification = classify_contract_clause(
        _classification_request(),
        lambda received: {
            "tag_id": "liability_caps",
            "confidence": 0.42,
            "rationale": "The wording may limit exposure, but it is ambiguous.",
            "evidence_key": received.evidence_key,
        },
    )

    assert classification.tag_id == "unknown_contract_clause"
    assert classification.confidence == 0.42
    assert classification.review_warnings == (
        "Classifier confidence 0.42 is below threshold 0.60; "
        "routed to unknown_contract_clause.",
    )


def test_mock_clause_classifier_records_requests_and_cites_evidence() -> None:
    request = _classification_request()
    classifier = MockContractClauseClassifier(
        tag_id="public_access",
        confidence=0.72,
        rationale="The clause appears to concern public records disclosure.",
    )

    classification = classify_contract_clause(request, classifier)

    assert classifier.requests == [request]
    assert classification.tag_id == "public_access"
    assert classification.evidence_key == request.evidence_key
