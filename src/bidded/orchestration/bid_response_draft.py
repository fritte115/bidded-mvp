from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from bidded.evidence.company_kb import infer_attachment_type
from bidded.orchestration.pending_run import DEMO_TENANT_KEY

DraftAnswerStatus = Literal["drafted", "needs_input", "blocked", "not_applicable"]
DraftAttachmentStatus = Literal["attached", "suggested", "missing", "needs_review"]
DraftStatus = Literal["draft", "needs_review", "blocked"]
PricingSource = Literal["bid_row", "estimator"]

SCHEMA_VERSION = "2026-04-23.bid_response_draft.v1"
DRAFT_MATCH_STOPWORDS = {
    "and",
    "att",
    "bid",
    "company",
    "for",
    "from",
    "med",
    "och",
    "ska",
    "skall",
    "the",
    "tender",
    "this",
}


class BidResponseDraftError(RuntimeError):
    """Raised when an evidence-locked bid draft cannot be generated."""


class SupabaseBidDraftQuery(Protocol):
    def select(self, columns: str) -> SupabaseBidDraftQuery: ...

    def eq(self, column: str, value: object) -> SupabaseBidDraftQuery: ...

    def order(self, column: str, *, desc: bool = False) -> SupabaseBidDraftQuery: ...

    def limit(self, row_limit: int) -> SupabaseBidDraftQuery: ...

    def insert(self, payload: dict[str, Any]) -> SupabaseBidDraftQuery: ...

    def execute(self) -> Any: ...


class SupabaseBidDraftStorageBucket(Protocol):
    def download(self, path: str) -> bytes: ...


class SupabaseBidDraftStorage(Protocol):
    def from_(self, bucket_name: str) -> SupabaseBidDraftStorageBucket: ...


class SupabaseBidDraftClient(Protocol):
    storage: SupabaseBidDraftStorage

    def table(self, table_name: str) -> SupabaseBidDraftQuery: ...


class PricingSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: PricingSource
    rate_sek: int
    margin_pct: float
    hours_estimated: int
    total_value_sek: int
    bid_id: str | None = None


class BidDraftAnswer(BaseModel):
    model_config = ConfigDict(frozen=True)

    question_id: str
    prompt: str
    answer: str
    status: DraftAnswerStatus
    evidence_keys: list[str] = Field(default_factory=list)
    required_attachment_types: list[str] = Field(default_factory=list)


class BidDraftAttachment(BaseModel):
    model_config = ConfigDict(frozen=True)

    filename: str
    storage_path: str | None
    checksum_sha256: str | None
    attachment_type: str
    required_by_evidence_key: str
    status: DraftAttachmentStatus
    source_evidence_keys: list[str] = Field(default_factory=list)
    packet_path: str | None = None


class BidResponseDraft(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: str = SCHEMA_VERSION
    run_id: str
    tender_id: str
    bid_id: str | None = None
    language: str
    status: DraftStatus
    verdict: str
    confidence: float | None = None
    pricing: PricingSnapshot
    answers: list[BidDraftAnswer] = Field(default_factory=list)
    attachments: list[BidDraftAttachment] = Field(default_factory=list)
    missing_info: list[str] = Field(default_factory=list)
    source_evidence_keys: list[str] = Field(default_factory=list)


def generate_bid_response_draft(
    client: SupabaseBidDraftClient,
    *,
    run_id: UUID | str,
    bid_id: UUID | str | None = None,
    tenant_key: str = DEMO_TENANT_KEY,
    storage_bucket: str | None = None,
    packet_dir: Path | None = None,
) -> BidResponseDraft:
    """Create and persist a reviewable evidence-locked draft anbud packet."""

    normalized_run_id = _normalize_uuid_string(run_id, "run_id")
    normalized_bid_id = (
        _normalize_uuid_string(bid_id, "bid_id") if bid_id is not None else None
    )
    run_row = _require_single_row(
        client,
        "agent_runs",
        {"id": normalized_run_id, "tenant_key": tenant_key},
        f"Agent run does not exist: {normalized_run_id}",
    )
    tender_id = str(run_row.get("tender_id") or "")
    company_id = str(run_row.get("company_id") or "")
    if not tender_id or not company_id:
        raise BidResponseDraftError("Agent run must include tender_id and company_id.")

    tender_row = _require_single_row(
        client,
        "tenders",
        {"id": tender_id, "tenant_key": tenant_key},
        f"Tender does not exist: {tender_id}",
    )
    company_row = _first_row(
        client,
        "companies",
        {"id": company_id, "tenant_key": tenant_key},
    ) or {"id": company_id}
    decision_row = _require_single_row(
        client,
        "bid_decisions",
        {"agent_run_id": normalized_run_id, "tenant_key": tenant_key},
        f"No persisted final decision for agent run {normalized_run_id}.",
    )
    final_decision = _mapping(decision_row.get("final_decision"))
    verdict = str(final_decision.get("verdict") or decision_row.get("verdict") or "")
    if verdict in {"no_bid", "needs_human_review"}:
        raise BidResponseDraftError(
            f"Cannot generate a draft anbud from {verdict} decision."
        )
    if verdict not in {"bid", "conditional_bid"}:
        raise BidResponseDraftError(f"Unsupported draftable verdict: {verdict!r}.")

    documents = _rows(client, "documents", {"tenant_key": tenant_key})
    tender_document_ids = {
        str(row.get("id"))
        for row in documents
        if row.get("document_role") == "tender_document"
        and str(row.get("tender_id")) == tender_id
    }
    company_documents = [
        row
        for row in documents
        if row.get("document_role") == "company_profile"
        and str(row.get("company_id")) == company_id
        and _mapping(row.get("metadata")).get("approved_for_bid_drafts", True)
    ]
    company_document_by_id = {str(row.get("id")): row for row in company_documents}
    approved_company_document_ids = set(company_document_by_id)

    evidence_rows = _rows(client, "evidence_items", {"tenant_key": tenant_key})
    tender_evidence = [
        row
        for row in evidence_rows
        if row.get("source_type") == "tender_document"
        and str(row.get("document_id")) in tender_document_ids
    ]
    company_evidence = [
        row
        for row in evidence_rows
        if row.get("source_type") == "company_profile"
        and str(row.get("company_id")) == company_id
        and _company_evidence_document_id(row) in approved_company_document_ids
    ]

    pricing = _pricing_snapshot(
        client,
        tender_id=tender_id,
        run_id=normalized_run_id,
        bid_id=normalized_bid_id,
        verdict=verdict,
        confidence=_float_or_none(
            final_decision.get("confidence", decision_row.get("confidence"))
        ),
        company_row=company_row,
        tenant_key=tenant_key,
    )
    language = _draft_language(tender_row, run_row)

    questions = _draftable_tender_evidence(tender_evidence)
    answers: list[BidDraftAnswer] = []
    attachments: list[BidDraftAttachment] = []
    missing_info = [str(item) for item in _sequence(final_decision.get("missing_info"))]
    for question in questions:
        supporting_evidence = _supporting_company_evidence_for_question(
            question,
            company_evidence,
        )
        question_attachments = _attachments_for_question(
            client,
            question=question,
            company_evidence=company_evidence,
            company_document_by_id=company_document_by_id,
            storage_bucket=storage_bucket,
            packet_dir=packet_dir,
        )
        attachments.extend(question_attachments)
        for attachment in question_attachments:
            if attachment.status == "missing":
                missing_info.append(
                    "Missing "
                    f"{attachment.attachment_type} attachment for "
                    f"{attachment.required_by_evidence_key}."
                )
        answers.append(
            _answer_for_question(
                question,
                attachments=question_attachments,
                supporting_evidence=supporting_evidence,
                language=language,
            )
        )
        if (
            answers[-1].status == "needs_input"
            and not any(
                attachment.status == "missing"
                for attachment in question_attachments
            )
        ):
            missing_info.append(
                f"Missing approved company evidence for {answers[-1].question_id}."
            )

    source_evidence_keys = _dedupe(
        [
            key
            for answer in answers
            for key in answer.evidence_keys
            if key.strip()
        ]
    )
    status: DraftStatus = (
        "needs_review"
        if missing_info
        or any(answer.status == "needs_input" for answer in answers)
        or any(
            attachment.status in {"missing", "needs_review"}
            for attachment in attachments
        )
        else "draft"
    )

    draft = BidResponseDraft(
        run_id=normalized_run_id,
        tender_id=tender_id,
        bid_id=pricing.bid_id,
        language=language,
        status=status,
        verdict=verdict,
        confidence=_float_or_none(
            final_decision.get("confidence", decision_row.get("confidence"))
        ),
        pricing=pricing,
        answers=answers,
        attachments=attachments,
        missing_info=_dedupe(missing_info),
        source_evidence_keys=source_evidence_keys,
    )
    _persist_draft(client, draft=draft, tenant_key=tenant_key)
    return draft


def fetch_latest_bid_response_draft(
    client: SupabaseBidDraftClient,
    *,
    run_id: UUID | str,
    tenant_key: str = DEMO_TENANT_KEY,
) -> BidResponseDraft | None:
    normalized_run_id = _normalize_uuid_string(run_id, "run_id")
    query = (
        client.table("bid_response_drafts")
        .select("*")
        .eq("tenant_key", tenant_key)
        .eq("agent_run_id", normalized_run_id)
        .order("created_at", desc=True)
        .limit(1)
    )
    rows = _response_rows(query.execute())
    if not rows:
        return None
    row = rows[0]
    metadata = _mapping(row.get("metadata"))
    return BidResponseDraft(
        run_id=str(row.get("agent_run_id") or normalized_run_id),
        tender_id=str(row.get("tender_id") or ""),
        bid_id=_optional_string(row.get("bid_id")),
        language=str(row.get("language") or "sv"),
        status=str(row.get("status") or "needs_review"),  # type: ignore[arg-type]
        verdict=str(metadata.get("verdict") or ""),
        confidence=_float_or_none(metadata.get("confidence")),
        pricing=PricingSnapshot.model_validate(_mapping(row.get("pricing_snapshot"))),
        answers=[
            BidDraftAnswer.model_validate(item)
            for item in _sequence(row.get("answers"))
            if isinstance(item, Mapping)
        ],
        attachments=[
            BidDraftAttachment.model_validate(item)
            for item in _sequence(row.get("attachment_manifest"))
            if isinstance(item, Mapping)
        ],
        missing_info=[str(item) for item in _sequence(row.get("missing_info"))],
        source_evidence_keys=[
            str(item) for item in _sequence(row.get("source_evidence_keys"))
        ],
    )


def bid_response_draft_to_payload(draft: BidResponseDraft) -> dict[str, Any]:
    return draft.model_dump(mode="json")


def _pricing_snapshot(
    client: SupabaseBidDraftClient,
    *,
    tender_id: str,
    run_id: str,
    bid_id: str | None,
    verdict: str,
    confidence: float | None,
    company_row: Mapping[str, Any],
    tenant_key: str,
) -> PricingSnapshot:
    bid_row = _selected_bid_row(
        client,
        tender_id=tender_id,
        run_id=run_id,
        bid_id=bid_id,
        tenant_key=tenant_key,
    )
    if bid_row is not None:
        rate = _positive_int(bid_row.get("rate_sek"), fallback=0)
        hours = _positive_int(bid_row.get("hours_estimated"), fallback=1600)
        margin = _float_or_none(bid_row.get("margin_pct")) or 0.0
        row_bid_id = bid_row.get("id") or bid_id
        return PricingSnapshot(
            source="bid_row",
            rate_sek=rate,
            margin_pct=margin,
            hours_estimated=hours,
            total_value_sek=rate * hours,
            bid_id=str(row_bid_id) if row_bid_id else None,
        )

    margin = _target_margin(company_row)
    rate = _estimate_rate(verdict=verdict, confidence=confidence, target_margin=margin)
    hours = 1600
    return PricingSnapshot(
        source="estimator",
        rate_sek=rate,
        margin_pct=margin,
        hours_estimated=hours,
        total_value_sek=rate * hours,
        bid_id=None,
    )


def _selected_bid_row(
    client: SupabaseBidDraftClient,
    *,
    tender_id: str,
    run_id: str,
    bid_id: str | None,
    tenant_key: str,
) -> Mapping[str, Any] | None:
    if bid_id is not None:
        return _first_row(
            client,
            "bids",
            {"id": bid_id, "tenant_key": tenant_key},
        )
    query = (
        client.table("bids")
        .select("*")
        .eq("tenant_key", tenant_key)
        .eq("tender_id", tender_id)
        .eq("agent_run_id", run_id)
        .order("updated_at", desc=True)
        .limit(1)
    )
    rows = _response_rows(query.execute())
    return rows[0] if rows else None


def _draft_language(
    tender_row: Mapping[str, Any],
    _run_row: Mapping[str, Any],
) -> str:
    tender_policy = _mapping(tender_row.get("language_policy"))
    for key in (
        "draft_language",
        "response_language",
        "output_language",
        "agent_output_language",
    ):
        value = tender_policy.get(key)
        if isinstance(value, str) and value.strip():
            return _normalize_language(value)
    return "sv"


def _normalize_language(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"se", "swe", "swedish", "svenska"}:
        return "sv"
    if normalized in {"eng", "english"}:
        return "en"
    return normalized or "sv"


def _draftable_tender_evidence(
    tender_evidence: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    relevant = [
        row
        for row in tender_evidence
        if _is_draft_question(row)
    ]
    return sorted(
        relevant,
        key=lambda row: (
            _optional_int(row.get("page_start")) or 0,
            str(row.get("evidence_key") or ""),
        ),
    )


def _is_draft_question(row: Mapping[str, Any]) -> bool:
    requirement_type = str(row.get("requirement_type") or "")
    category = str(row.get("category") or "")
    text = " ".join(
        [
            requirement_type,
            category,
            str(row.get("excerpt") or ""),
            str(row.get("normalized_meaning") or ""),
        ]
    ).lower()
    return (
        requirement_type
        in {
            "submission_document",
            "shall_requirement",
            "qualification_requirement",
            "financial_standing",
            "quality_management",
            "legal_or_regulatory_reference",
        }
        or any(
            marker in text
            for marker in (
                "submission",
                "required",
                "shall",
                "ska",
                "certifikat",
                "certificate",
                "cv",
                "reference",
                "referens",
            )
        )
    )


def _attachments_for_question(
    client: SupabaseBidDraftClient,
    *,
    question: Mapping[str, Any],
    company_evidence: Sequence[Mapping[str, Any]],
    company_document_by_id: Mapping[str, Mapping[str, Any]],
    storage_bucket: str | None,
    packet_dir: Path | None,
) -> list[BidDraftAttachment]:
    required_types = _required_attachment_types(question)
    if not required_types:
        return []

    attachments: list[BidDraftAttachment] = []
    for attachment_type in required_types:
        evidence = _matching_company_evidence(
            company_evidence,
            attachment_type=attachment_type,
        )
        if evidence is None:
            attachments.append(
                BidDraftAttachment(
                    filename=(
                        f"{attachment_type} required by "
                        f"{question['evidence_key']}"
                    ),
                    storage_path=None,
                    checksum_sha256=None,
                    attachment_type=attachment_type,
                    required_by_evidence_key=str(question["evidence_key"]),
                    status="missing",
                    source_evidence_keys=[str(question["evidence_key"])],
                )
            )
            continue

        evidence_metadata = _mapping(evidence.get("metadata"))
        document_id = str(
            evidence_metadata.get("source_document_id")
            or _mapping(evidence.get("source_metadata")).get("source_document_id")
            or ""
        )
        document = company_document_by_id.get(document_id, {})
        storage_path = _optional_string(
            document.get("storage_path") or evidence_metadata.get("source_storage_path")
        )
        filename = str(
            document.get("original_filename")
            or evidence_metadata.get("source_original_filename")
            or f"{attachment_type}.pdf"
        )
        packet_path = _stage_attachment(
            client,
            storage_bucket=storage_bucket,
            packet_dir=packet_dir,
            storage_path=storage_path,
            filename=filename,
        )
        status: DraftAttachmentStatus = "attached" if storage_path else "suggested"
        attachments.append(
            BidDraftAttachment(
                filename=filename,
                storage_path=storage_path,
                checksum_sha256=_optional_string(document.get("checksum_sha256")),
                attachment_type=attachment_type,
                required_by_evidence_key=str(question["evidence_key"]),
                status=status,
                source_evidence_keys=[
                    str(question["evidence_key"]),
                    str(evidence.get("evidence_key")),
                ],
                packet_path=str(packet_path) if packet_path is not None else None,
            )
        )
    return attachments


def _required_attachment_types(question: Mapping[str, Any]) -> list[str]:
    text = " ".join(
        [
            str(question.get("category") or ""),
            str(question.get("requirement_type") or ""),
            str(question.get("excerpt") or ""),
            str(question.get("normalized_meaning") or ""),
        ]
    )
    attachment_type = infer_attachment_type(text)
    if attachment_type != "other":
        return [attachment_type]
    lowered = _ascii_lower(text)
    if "bifogas" in lowered or "attach" in lowered or "include" in lowered:
        return ["other"]
    return []


def _matching_company_evidence(
    company_evidence: Sequence[Mapping[str, Any]],
    *,
    attachment_type: str,
) -> Mapping[str, Any] | None:
    for row in sorted(company_evidence, key=lambda item: str(item.get("evidence_key"))):
        metadata = _mapping(row.get("metadata"))
        source_metadata = _mapping(row.get("source_metadata"))
        row_attachment_type = _attachment_type_from_company_metadata(
            metadata,
            source_metadata,
        )
        if row_attachment_type == attachment_type:
            return row
        inferred = infer_attachment_type(
            " ".join(
                [
                    str(row.get("category") or ""),
                    str(row.get("excerpt") or ""),
                    str(row.get("normalized_meaning") or ""),
                    str(source_metadata.get("source_label") or ""),
                ]
            )
        )
        if inferred == attachment_type:
            return row
    return None


def _supporting_company_evidence_for_question(
    question: Mapping[str, Any],
    company_evidence: Sequence[Mapping[str, Any]],
    *,
    limit: int = 2,
) -> list[Mapping[str, Any]]:
    scored: list[tuple[int, str, Mapping[str, Any]]] = []
    for row in company_evidence:
        score = _company_evidence_match_score(question, row)
        if score > 0:
            scored.append((score, str(row.get("evidence_key") or ""), row))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [row for _, _, row in scored[:limit]]


def _company_evidence_match_score(
    question: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> int:
    question_text = " ".join(
        [
            str(question.get("category") or ""),
            str(question.get("requirement_type") or ""),
            str(question.get("excerpt") or ""),
            str(question.get("normalized_meaning") or ""),
        ]
    )
    evidence_text = " ".join(
        [
            str(evidence.get("category") or ""),
            str(evidence.get("excerpt") or ""),
            str(evidence.get("normalized_meaning") or ""),
            str(_mapping(evidence.get("source_metadata")).get("source_label") or ""),
        ]
    )
    question_tokens = _keyword_tokens(question_text)
    evidence_tokens = _keyword_tokens(evidence_text)
    score = len(question_tokens & evidence_tokens)
    if (
        question.get("category")
        and question.get("category") == evidence.get("category")
    ):
        score += 2
    return score


def _keyword_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", _ascii_lower(value))
        if len(token) >= 3 and token not in DRAFT_MATCH_STOPWORDS
    }


def _company_evidence_document_id(evidence: Mapping[str, Any]) -> str:
    metadata = _mapping(evidence.get("metadata"))
    source_metadata = _mapping(evidence.get("source_metadata"))
    return str(
        metadata.get("source_document_id")
        or source_metadata.get("source_document_id")
        or evidence.get("document_id")
        or ""
    )


def _attachment_type_from_company_metadata(
    metadata: Mapping[str, Any],
    source_metadata: Mapping[str, Any],
) -> str:
    attachment_type = str(metadata.get("attachment_type") or "")
    if attachment_type:
        return attachment_type
    kb_document_type = str(
        metadata.get("kb_document_type")
        or source_metadata.get("kb_document_type")
        or ""
    )
    return {
        "certification": "certificate",
        "cv_profile": "cv",
        "case_study": "reference_case",
        "policy_process": "policy_document",
        "financial_pricing": "pricing_document",
    }.get(kb_document_type, "")


def _evidence_source_label(evidence: Mapping[str, Any]) -> str:
    source_metadata = _mapping(evidence.get("source_metadata"))
    label = source_metadata.get("source_label")
    if isinstance(label, str) and label.strip():
        return label.strip()
    return str(evidence.get("evidence_key") or "company evidence")


def _answer_for_question(
    question: Mapping[str, Any],
    *,
    attachments: Sequence[BidDraftAttachment],
    supporting_evidence: Sequence[Mapping[str, Any]],
    language: str,
) -> BidDraftAnswer:
    evidence_key = str(question.get("evidence_key") or "")
    prompt = str(question.get("normalized_meaning") or question.get("excerpt") or "")
    required_types = _required_attachment_types(question)
    missing = [
        attachment
        for attachment in attachments
        if attachment.status == "missing"
    ]
    if missing:
        status: DraftAnswerStatus = "needs_input"
        answer = (
            f"Komplettera underlag innan anbudet färdigställs: {prompt}"
            if language == "sv"
            else f"Add supporting material before finalizing the bid: {prompt}"
        )
        evidence_keys = [evidence_key]
    elif attachments:
        filenames = ", ".join(attachment.filename for attachment in attachments)
        status = "drafted"
        answer = (
            f"Bifoga {filenames}. Kravet adresseras med bifogad evidens: {prompt}"
            if language == "sv"
            else (
                f"Attach {filenames}. The requirement is addressed by cited "
                f"evidence: {prompt}"
            )
        )
        evidence_keys = _dedupe(
            [
                key
                for attachment in attachments
                for key in attachment.source_evidence_keys
            ]
        )
    elif supporting_evidence:
        status = "drafted"
        snippets = "; ".join(
            f"{_evidence_source_label(row)}: {str(row.get('excerpt') or '').strip()}"
            for row in supporting_evidence
        )
        answer = (
            f"Vi adresserar kravet med godkänd bolagsevidens från {snippets}."
            if language == "sv"
            else (
                "We address the requirement with approved company evidence "
                f"from {snippets}."
            )
        )
        evidence_keys = _dedupe(
            [
                evidence_key,
                *[
                    str(row.get("evidence_key") or "")
                    for row in supporting_evidence
                ],
            ]
        )
    else:
        status = "needs_input"
        answer = (
            f"Saknar godkänd bolagsevidens för att besvara kravet: {prompt}"
            if language == "sv"
            else f"Missing approved company evidence to answer: {prompt}"
        )
        evidence_keys = [evidence_key]

    return BidDraftAnswer(
        question_id=evidence_key,
        prompt=prompt,
        answer=answer,
        status=status,
        evidence_keys=evidence_keys,
        required_attachment_types=required_types,
    )


def _stage_attachment(
    client: SupabaseBidDraftClient,
    *,
    storage_bucket: str | None,
    packet_dir: Path | None,
    storage_path: str | None,
    filename: str,
) -> Path | None:
    if packet_dir is None or storage_bucket is None or storage_path is None:
        return None
    packet_dir.mkdir(parents=True, exist_ok=True)
    data = client.storage.from_(storage_bucket).download(storage_path)
    if not isinstance(data, bytes):
        raise BidResponseDraftError(
            f"Attachment download did not return bytes: {storage_path}"
        )
    target = packet_dir / _safe_filename(filename)
    target.write_bytes(data)
    return target


def _persist_draft(
    client: SupabaseBidDraftClient,
    *,
    draft: BidResponseDraft,
    tenant_key: str,
) -> None:
    payload = {
        "tenant_key": tenant_key,
        "tender_id": draft.tender_id,
        "agent_run_id": draft.run_id,
        "bid_id": draft.bid_id,
        "status": draft.status,
        "language": draft.language,
        "pricing_snapshot": draft.pricing.model_dump(mode="json"),
        "answers": [answer.model_dump(mode="json") for answer in draft.answers],
        "attachment_manifest": [
            attachment.model_dump(mode="json") for attachment in draft.attachments
        ],
        "missing_info": list(draft.missing_info),
        "source_evidence_keys": list(draft.source_evidence_keys),
        "metadata": {
            "schema_version": draft.schema_version,
            "verdict": draft.verdict,
            "confidence": draft.confidence,
            "created_via": "bid_response_draft_generator",
        },
    }
    client.table("bid_response_drafts").insert(payload).execute()


def _target_margin(company_row: Mapping[str, Any]) -> float:
    assumptions = _mapping(company_row.get("financial_assumptions"))
    value = assumptions.get("target_gross_margin_percent")
    if isinstance(value, int | float):
        return float(value)
    return 12.0


def _estimate_rate(
    *,
    verdict: str,
    confidence: float | None,
    target_margin: float,
) -> int:
    base_target_cost = 1100.0
    fit_multiplier = 0.97 if verdict == "bid" else 1.0
    win_probability = confidence if confidence is not None else 0.5
    if win_probability < 0.4:
        win_adjustment = 0.95
    elif win_probability > 0.6:
        win_adjustment = 1.03
    else:
        win_adjustment = 1.0
    raw = (
        base_target_cost
        * (1 + target_margin / 100)
        * fit_multiplier
        * win_adjustment
    )
    return min(_round_to(raw), 1450)


def _round_to(value: float, step: int = 5) -> int:
    return int(round(value / step) * step)


def _rows(
    client: SupabaseBidDraftClient,
    table_name: str,
    filters: Mapping[str, object],
) -> list[Mapping[str, Any]]:
    query = client.table(table_name).select("*")
    for column, value in filters.items():
        query = query.eq(column, value)
    return _response_rows(query.execute())


def _first_row(
    client: SupabaseBidDraftClient,
    table_name: str,
    filters: Mapping[str, object],
) -> Mapping[str, Any] | None:
    rows = _rows(client, table_name, filters)
    return rows[0] if rows else None


def _require_single_row(
    client: SupabaseBidDraftClient,
    table_name: str,
    filters: Mapping[str, object],
    missing_message: str,
) -> Mapping[str, Any]:
    row = _first_row(client, table_name, filters)
    if row is None:
        raise BidResponseDraftError(missing_message)
    return row


def _response_rows(response: Any) -> list[Mapping[str, Any]]:
    data = getattr(response, "data", None)
    if not isinstance(data, list):
        raise BidResponseDraftError("Supabase query did not return a row list.")
    return [row for row in data if isinstance(row, Mapping)]


def _sequence(value: object) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, str) else ()


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _positive_int(value: object, *, fallback: int) -> int:
    try:
        parsed = int(float(str(value)))
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def _optional_int(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _normalize_uuid_string(value: UUID | str, field_name: str) -> str:
    try:
        return str(value if isinstance(value, UUID) else UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise BidResponseDraftError(f"{field_name} must be a UUID.") from exc


def _dedupe(items: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            deduped.append(text)
    return deduped


def _ascii_lower(value: str) -> str:
    return value.casefold().replace("å", "a").replace("ä", "a").replace("ö", "o")


def _safe_filename(value: str) -> str:
    path = Path(value)
    suffix = path.suffix or ".pdf"
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", path.stem).strip("-") or "attachment"
    return f"{stem}{suffix}"


__all__ = [
    "BidDraftAnswer",
    "BidDraftAttachment",
    "BidResponseDraft",
    "BidResponseDraftError",
    "PricingSnapshot",
    "bid_response_draft_to_payload",
    "fetch_latest_bid_response_draft",
    "generate_bid_response_draft",
]
