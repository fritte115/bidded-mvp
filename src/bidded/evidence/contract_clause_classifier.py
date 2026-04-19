from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

ContractClauseTagId = Literal[
    "penalties_liquidated_damages",
    "liability_caps",
    "gdpr_dpa",
    "subprocessors",
    "confidentiality",
    "insurance",
    "gross_negligence_wilful_misconduct",
    "public_access",
    "reporting",
    "termination",
    "subcontractors",
    "unknown_contract_clause",
]

KNOWN_CONTRACT_CLAUSE_TAG_IDS: tuple[ContractClauseTagId, ...] = (
    "penalties_liquidated_damages",
    "liability_caps",
    "gdpr_dpa",
    "subprocessors",
    "confidentiality",
    "insurance",
    "gross_negligence_wilful_misconduct",
    "public_access",
    "reporting",
    "termination",
    "subcontractors",
    "unknown_contract_clause",
)
UNKNOWN_CONTRACT_CLAUSE_TAG_ID: ContractClauseTagId = "unknown_contract_clause"
DEFAULT_MIN_CLASSIFIER_CONFIDENCE = 0.6


class ContractClauseProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: UUID
    section_number: str | None = None
    heading: str = Field(min_length=1)
    page_start: int = Field(gt=0)
    page_end: int = Field(gt=0)
    chunk_ids: tuple[UUID, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_page_range(self) -> ContractClauseProvenance:
        if self.page_end < self.page_start:
            raise ValueError("page_end must be greater than or equal to page_start")
        return self


class ContractClauseClassificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_key: str | None = Field(default=None, min_length=1)
    document_id: UUID
    chunk_id: UUID
    page_start: int = Field(gt=0)
    page_end: int = Field(gt=0)
    excerpt: str = Field(min_length=1)
    source_label: str = Field(min_length=1)
    allowed_tag_ids: tuple[ContractClauseTagId, ...] = Field(
        default=KNOWN_CONTRACT_CLAUSE_TAG_IDS,
        min_length=1,
    )
    deterministic_tag_ids: tuple[ContractClauseTagId, ...] = ()
    clause_provenance: ContractClauseProvenance | None = None

    @model_validator(mode="after")
    def validate_request(self) -> ContractClauseClassificationRequest:
        if self.page_end < self.page_start:
            raise ValueError("page_end must be greater than or equal to page_start")
        return self


class ContractClauseClassificationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tag_id: ContractClauseTagId
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1, max_length=320)
    evidence_key: str | None = Field(default=None, min_length=1)
    clause_provenance: ContractClauseProvenance | None = None
    missing_info: tuple[str, ...] = ()
    review_warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_citation(self) -> ContractClauseClassificationOutput:
        if self.evidence_key is None and self.clause_provenance is None:
            raise ValueError(
                "classification must cite an evidence key or clause provenance"
            )
        return self


ClassifierRawOutput = Mapping[str, Any] | ContractClauseClassificationOutput


class ContractClauseClassifierModel(Protocol):
    def classify(
        self,
        request: ContractClauseClassificationRequest,
    ) -> ClassifierRawOutput: ...


ContractClauseClassifier = (
    ContractClauseClassifierModel
    | Callable[[ContractClauseClassificationRequest], ClassifierRawOutput]
)


class MockContractClauseClassifier:
    def __init__(
        self,
        *,
        tag_id: ContractClauseTagId = UNKNOWN_CONTRACT_CLAUSE_TAG_ID,
        confidence: float = 0.7,
        rationale: str = "Deterministic mocked clause classification.",
        missing_info: Sequence[str] = (),
        review_warnings: Sequence[str] = (),
        outputs: Sequence[ClassifierRawOutput] | None = None,
    ) -> None:
        self.tag_id = tag_id
        self.confidence = confidence
        self.rationale = rationale
        self.missing_info = tuple(missing_info)
        self.review_warnings = tuple(review_warnings)
        self._outputs = list(outputs or ())
        self.requests: list[ContractClauseClassificationRequest] = []

    def classify(
        self,
        request: ContractClauseClassificationRequest,
    ) -> ClassifierRawOutput:
        self.requests.append(request)
        if self._outputs:
            return self._outputs.pop(0)

        output: dict[str, Any] = {
            "tag_id": self.tag_id,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "missing_info": self.missing_info,
            "review_warnings": self.review_warnings,
        }
        if request.evidence_key is not None:
            output["evidence_key"] = request.evidence_key
        elif request.clause_provenance is not None:
            output["clause_provenance"] = request.clause_provenance
        return output


def classify_contract_clause(
    request: ContractClauseClassificationRequest,
    classifier: ContractClauseClassifier,
    *,
    min_confidence: float = DEFAULT_MIN_CLASSIFIER_CONFIDENCE,
) -> ContractClauseClassificationOutput:
    raw_output = _call_classifier(classifier, request)
    output = ContractClauseClassificationOutput.model_validate(raw_output)
    _validate_output_cites_request(output, request)
    _validate_output_allowed_by_request(output, request)
    if output.confidence < min_confidence:
        fallback_output = _fallback_low_confidence(
            output,
            min_confidence=min_confidence,
        )
        _validate_output_allowed_by_request(fallback_output, request)
        return fallback_output
    return output


def contract_clause_classification_metadata(
    output: ContractClauseClassificationOutput,
) -> dict[str, Any]:
    return {
        "tag_id": output.tag_id,
        "confidence": output.confidence,
        "rationale": output.rationale,
        "evidence_key": output.evidence_key,
        "clause_provenance": (
            output.clause_provenance.model_dump(mode="json")
            if output.clause_provenance is not None
            else None
        ),
        "missing_info": list(output.missing_info),
        "review_warnings": list(output.review_warnings),
    }


def _call_classifier(
    classifier: ContractClauseClassifier,
    request: ContractClauseClassificationRequest,
) -> ClassifierRawOutput:
    classify_method = getattr(classifier, "classify", None)
    if callable(classify_method):
        return classify_method(request)
    return classifier(request)


def _validate_output_cites_request(
    output: ContractClauseClassificationOutput,
    request: ContractClauseClassificationRequest,
) -> None:
    cites_evidence_key = (
        output.evidence_key is not None and output.evidence_key == request.evidence_key
    )
    cites_clause_provenance = (
        output.clause_provenance is not None
        and output.clause_provenance == request.clause_provenance
    )
    if cites_evidence_key or cites_clause_provenance:
        return
    raise ValueError(
        "classification must cite the request evidence key or clause provenance"
    )


def _validate_output_allowed_by_request(
    output: ContractClauseClassificationOutput,
    request: ContractClauseClassificationRequest,
) -> None:
    if output.tag_id in request.allowed_tag_ids:
        return
    raise ValueError(
        "classification tag_id must be one of request.allowed_tag_ids"
    )


def _fallback_low_confidence(
    output: ContractClauseClassificationOutput,
    *,
    min_confidence: float,
) -> ContractClauseClassificationOutput:
    if output.tag_id == UNKNOWN_CONTRACT_CLAUSE_TAG_ID:
        return output
    warning = (
        f"Classifier confidence {output.confidence:.2f} is below threshold "
        f"{min_confidence:.2f}; routed to unknown_contract_clause."
    )
    review_warnings = _dedupe_preserving_order((*output.review_warnings, warning))
    return output.model_copy(
        update={
            "tag_id": UNKNOWN_CONTRACT_CLAUSE_TAG_ID,
            "review_warnings": review_warnings,
        }
    )


def _dedupe_preserving_order(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return tuple(deduped)


__all__ = [
    "ContractClauseClassificationOutput",
    "ContractClauseClassificationRequest",
    "ContractClauseClassifier",
    "ContractClauseClassifierModel",
    "ContractClauseProvenance",
    "ContractClauseTagId",
    "DEFAULT_MIN_CLASSIFIER_CONFIDENCE",
    "KNOWN_CONTRACT_CLAUSE_TAG_IDS",
    "MockContractClauseClassifier",
    "UNKNOWN_CONTRACT_CLAUSE_TAG_ID",
    "classify_contract_clause",
    "contract_clause_classification_metadata",
]
