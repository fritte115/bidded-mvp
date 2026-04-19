from __future__ import annotations

from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field, model_validator

from bidded.orchestration.state import (
    EvidenceItemState,
    EvidenceRef,
    EvidenceSourceType,
    StrictStateModel,
    Verdict,
)
from bidded.requirements import RequirementType

DecisionRule = Literal[
    "evidence_by_default",
    "formal_blocker_gates_no_bid",
    "conditional_bid_requires_next_actions",
    "conflicting_evidence_routes_human_review",
    "missing_company_evidence_is_not_auto_no_bid",
    "unsupported_claims_are_rejected",
]

_FIXTURE_NAMESPACE = uuid5(
    NAMESPACE_URL,
    "https://bidded.local/fixtures/golden-demo-cases/v1",
)


class GoldenExpectedOutcome(StrictStateModel):
    """Expected decision artifact summary for one golden demo case."""

    verdict: Verdict
    blockers: tuple[str, ...] = ()
    missing_info: tuple[str, ...] = ()
    recommended_actions: tuple[str, ...] = ()
    required_evidence_refs: tuple[EvidenceRef, ...] = Field(min_length=1)
    unsupported_claims_rejected: tuple[str, ...] = ()
    validation_errors: tuple[str, ...] = ()
    decision_rules: tuple[DecisionRule, ...] = Field(min_length=1)
    rationale: str = Field(min_length=1)


class GoldenDemoCase(StrictStateModel):
    """Typed, evidence-backed regression fixture for a core decision behavior."""

    case_id: str = Field(min_length=1, pattern=r"^[a-z0-9_]+$")
    title: str = Field(min_length=1)
    tender_evidence: tuple[EvidenceItemState, ...] = Field(min_length=1)
    company_evidence: tuple[EvidenceItemState, ...] = ()
    expected: GoldenExpectedOutcome

    @property
    def evidence_board(self) -> tuple[EvidenceItemState, ...]:
        return (*self.tender_evidence, *self.company_evidence)

    @model_validator(mode="after")
    def validate_case_contract(self) -> GoldenDemoCase:
        evidence_by_key = {item.evidence_key: item for item in self.evidence_board}
        if len(evidence_by_key) != len(self.evidence_board):
            raise ValueError(f"{self.case_id} contains duplicate evidence keys")

        for evidence_ref in self.expected.required_evidence_refs:
            item = evidence_by_key.get(evidence_ref.evidence_key)
            if item is None:
                raise ValueError(
                    f"{self.case_id} cites missing evidence "
                    f"{evidence_ref.evidence_key}"
                )
            if item.source_type is not evidence_ref.source_type:
                raise ValueError(
                    f"{self.case_id} cites {evidence_ref.evidence_key} "
                    "with the wrong source type"
                )
            if item.evidence_id != evidence_ref.evidence_id:
                raise ValueError(
                    f"{self.case_id} cites {evidence_ref.evidence_key} "
                    "with the wrong evidence_id"
                )

        return self


def golden_demo_cases() -> tuple[GoldenDemoCase, ...]:
    """Return the deterministic golden case set for bid/no-bid regression tests."""

    return _GOLDEN_DEMO_CASES


def _obvious_bid_case() -> GoldenDemoCase:
    tender_iso = _tender_evidence(
        case_id="obvious_bid",
        key="TENDER-ISO-27001",
        excerpt=(
            "Supplier must hold active ISO 27001 certification for managed "
            "service delivery."
        ),
        normalized_meaning=(
            "The tender requires active ISO 27001 certification for delivery."
        ),
        category="qualification_requirement",
        requirement_type=RequirementType.QUALITY_MANAGEMENT,
    )
    tender_quality = _tender_evidence(
        case_id="obvious_bid",
        key="TENDER-QUALITY-WEIGHT",
        excerpt=(
            "Award evaluation gives 70 percent to quality and relevant "
            "public-sector references."
        ),
        normalized_meaning=(
            "The tender strongly weights quality and public-sector references."
        ),
        category="award_criterion",
        requirement_type=None,
    )
    company_iso = _company_evidence(
        case_id="obvious_bid",
        key="COMPANY-ISO-27001",
        excerpt=(
            "ISO 27001: information security management for managed delivery; "
            "status active."
        ),
        normalized_meaning=(
            "The company has active ISO 27001 certification for managed delivery."
        ),
        category="certification",
        field_path="certifications[iso_27001]",
    )
    company_reference = _company_evidence(
        case_id="obvious_bid",
        key="COMPANY-PUBLIC-REFERENCE",
        excerpt=(
            "National agency reference, 2023-2025: secure case-management "
            "modernization for public-sector users."
        ),
        normalized_meaning=(
            "The company has a recent public-sector delivery reference."
        ),
        category="reference",
        field_path="reference_projects[0]",
    )

    return GoldenDemoCase(
        case_id="obvious_bid",
        title="Obvious bid from matched proof",
        tender_evidence=(tender_iso, tender_quality),
        company_evidence=(company_iso, company_reference),
        expected=GoldenExpectedOutcome(
            verdict=Verdict.BID,
            required_evidence_refs=(
                _ref(tender_iso),
                _ref(tender_quality),
                _ref(company_iso),
                _ref(company_reference),
            ),
            decision_rules=("evidence_by_default",),
            rationale=(
                "BID because GOLDEN-OBVIOUS-BID-TENDER-ISO-27001 is matched by "
                "GOLDEN-OBVIOUS-BID-COMPANY-ISO-27001, and "
                "GOLDEN-OBVIOUS-BID-TENDER-QUALITY-WEIGHT is matched by "
                "GOLDEN-OBVIOUS-BID-COMPANY-PUBLIC-REFERENCE."
            ),
        ),
    )


def _hard_compliance_no_bid_case() -> GoldenDemoCase:
    tender_exclusion = _tender_evidence(
        case_id="hard_compliance_no_bid",
        key="TENDER-INSOLVENCY-EXCLUSION",
        excerpt=(
            "Supplier must not be bankrupt or subject to insolvency exclusion "
            "grounds."
        ),
        normalized_meaning=(
            "The tender makes bankruptcy or insolvency a formal exclusion ground."
        ),
        category="exclusion_ground",
        requirement_type=RequirementType.EXCLUSION_GROUND,
    )
    company_insolvency = _company_evidence(
        case_id="hard_compliance_no_bid",
        key="COMPANY-ACTIVE-INSOLVENCY",
        excerpt=(
            "Legal status note: active insolvency proceeding recorded for the "
            "supplier."
        ),
        normalized_meaning=(
            "The company profile records an active insolvency proceeding."
        ),
        category="legal_status",
        field_path="legal_status.insolvency",
    )

    return GoldenDemoCase(
        case_id="hard_compliance_no_bid",
        title="Hard compliance no-bid",
        tender_evidence=(tender_exclusion,),
        company_evidence=(company_insolvency,),
        expected=GoldenExpectedOutcome(
            verdict=Verdict.NO_BID,
            blockers=("Confirmed insolvency exclusion ground blocks submission.",),
            required_evidence_refs=(_ref(tender_exclusion), _ref(company_insolvency)),
            decision_rules=("formal_blocker_gates_no_bid",),
            rationale=(
                "NO_BID because GOLDEN-HARD-COMPLIANCE-NO-BID-"
                "TENDER-INSOLVENCY-EXCLUSION defines the formal gate and "
                "GOLDEN-HARD-COMPLIANCE-NO-BID-COMPANY-ACTIVE-INSOLVENCY "
                "confirms the blocking fact."
            ),
        ),
    )


def _conditional_bid_next_actions_case() -> GoldenDemoCase:
    tender_named_lead = _tender_evidence(
        case_id="conditional_bid_next_actions",
        key="TENDER-NAMED-LEAD",
        excerpt=(
            "Submission must name one security-cleared delivery lead and include "
            "that person's CV."
        ),
        normalized_meaning=(
            "The tender requires a named security-cleared delivery lead CV."
        ),
        category="qualification_requirement",
        requirement_type=RequirementType.QUALIFICATION_REQUIREMENT,
    )
    tender_dpa = _tender_evidence(
        case_id="conditional_bid_next_actions",
        key="TENDER-SIGNED-DPA",
        excerpt="Submission must include a signed data processing agreement.",
        normalized_meaning=(
            "The tender requires a signed data processing agreement in the bid."
        ),
        category="required_submission_document",
        requirement_type=RequirementType.SUBMISSION_DOCUMENT,
    )
    company_cleared_leads = _company_evidence(
        case_id="conditional_bid_next_actions",
        key="COMPANY-CLEARED-LEADS",
        excerpt="12 security-cleared delivery leads available within 30 days.",
        normalized_meaning=(
            "The company has security-cleared lead capacity, but the fixture "
            "does not name the bid lead."
        ),
        category="capacity",
        field_path="capabilities.delivery_capacity.security_cleared_leads",
    )

    return GoldenDemoCase(
        case_id="conditional_bid_next_actions",
        title="Conditional bid with next actions",
        tender_evidence=(tender_named_lead, tender_dpa),
        company_evidence=(company_cleared_leads,),
        expected=GoldenExpectedOutcome(
            verdict=Verdict.CONDITIONAL_BID,
            missing_info=(
                "Named security-cleared delivery lead CV is not present.",
                "Signed data processing agreement attachment is not present.",
            ),
            recommended_actions=(
                "Name the delivery lead and attach that person's CV.",
                "Prepare and sign the data processing agreement attachment.",
            ),
            required_evidence_refs=(
                _ref(tender_named_lead),
                _ref(tender_dpa),
                _ref(company_cleared_leads),
            ),
            decision_rules=("conditional_bid_requires_next_actions",),
            rationale=(
                "CONDITIONAL_BID because "
                "GOLDEN-CONDITIONAL-BID-NEXT-ACTIONS-COMPANY-CLEARED-LEADS "
                "supports delivery capacity, while "
                "GOLDEN-CONDITIONAL-BID-NEXT-ACTIONS-TENDER-NAMED-LEAD and "
                "GOLDEN-CONDITIONAL-BID-NEXT-ACTIONS-TENDER-SIGNED-DPA require "
                "explicit submission actions before bid approval."
            ),
        ),
    )


def _conflicting_evidence_needs_review_case() -> GoldenDemoCase:
    tender_named_lead = _tender_evidence(
        case_id="conflicting_evidence_needs_review",
        key="TENDER-NAMED-LEAD",
        excerpt="Supplier must provide a named lead available from contract start.",
        normalized_meaning=(
            "The tender requires a named lead available at contract start."
        ),
        category="qualification_requirement",
        requirement_type=RequirementType.QUALIFICATION_REQUIREMENT,
    )
    company_lead_available = _company_evidence(
        case_id="conflicting_evidence_needs_review",
        key="COMPANY-LEAD-AVAILABLE",
        excerpt="Named lead A is available for the tender from 2026-06-01.",
        normalized_meaning=(
            "One company profile field says the named lead is available on time."
        ),
        category="staffing",
        field_path="staffing.named_lead.availability",
    )
    company_lead_allocated = _company_evidence(
        case_id="conflicting_evidence_needs_review",
        key="COMPANY-LEAD-ALLOCATED",
        excerpt=(
            "Named lead A is allocated full-time to another customer until "
            "2026-07-15."
        ),
        normalized_meaning=(
            "Another company profile field says the same lead is not available."
        ),
        category="staffing",
        field_path="staffing.named_lead.current_allocation",
    )

    return GoldenDemoCase(
        case_id="conflicting_evidence_needs_review",
        title="Needs review from conflicting evidence",
        tender_evidence=(tender_named_lead,),
        company_evidence=(company_lead_available, company_lead_allocated),
        expected=GoldenExpectedOutcome(
            verdict=Verdict.NEEDS_HUMAN_REVIEW,
            missing_info=("Resolve conflicting named-lead availability records.",),
            recommended_actions=(
                "Have an operator confirm whether the named lead is actually "
                "available at contract start.",
            ),
            required_evidence_refs=(
                _ref(tender_named_lead),
                _ref(company_lead_available),
                _ref(company_lead_allocated),
            ),
            decision_rules=("conflicting_evidence_routes_human_review",),
            rationale=(
                "NEEDS_HUMAN_REVIEW because "
                "GOLDEN-CONFLICTING-EVIDENCE-NEEDS-REVIEW-TENDER-NAMED-LEAD "
                "requires availability, while "
                "GOLDEN-CONFLICTING-EVIDENCE-NEEDS-REVIEW-COMPANY-LEAD-AVAILABLE "
                "and GOLDEN-CONFLICTING-EVIDENCE-NEEDS-REVIEW-"
                "COMPANY-LEAD-ALLOCATED conflict on the same named person."
            ),
        ),
    )


def _missing_company_evidence_case() -> GoldenDemoCase:
    tender_financial = _tender_evidence(
        case_id="missing_company_evidence",
        key="TENDER-FINANCIAL-STANDING",
        excerpt=(
            "Supplier must submit audited annual turnover above SEK 50 million "
            "for the latest fiscal year."
        ),
        normalized_meaning=(
            "The tender requires current audited turnover proof above SEK 50m."
        ),
        category="financial_standing",
        requirement_type=RequirementType.FINANCIAL_STANDING,
    )

    return GoldenDemoCase(
        case_id="missing_company_evidence",
        title="Missing company proof is non-gating",
        tender_evidence=(tender_financial,),
        company_evidence=(),
        expected=GoldenExpectedOutcome(
            verdict=Verdict.CONDITIONAL_BID,
            missing_info=(
                "Current audited turnover evidence is missing from company profile.",
            ),
            recommended_actions=(
                "Attach audited turnover proof before final submission approval.",
            ),
            required_evidence_refs=(_ref(tender_financial),),
            decision_rules=("missing_company_evidence_is_not_auto_no_bid",),
            rationale=(
                "CONDITIONAL_BID because "
                "GOLDEN-MISSING-COMPANY-EVIDENCE-TENDER-FINANCIAL-STANDING "
                "establishes a financial proof requirement, but no company "
                "evidence confirms or disproves it, so the gap becomes "
                "missing_info and an action rather than an automatic no_bid."
            ),
        ),
    )


def _unsupported_agent_claim_rejection_case() -> GoldenDemoCase:
    tender_staffing = _tender_evidence(
        case_id="unsupported_agent_claim_rejection",
        key="TENDER-THIRTY-DAY-STAFFING",
        excerpt="Supplier must provide eight developers within 30 days of award.",
        normalized_meaning=(
            "The tender requires eight developers available within 30 days."
        ),
        category="qualification_requirement",
        requirement_type=RequirementType.QUALIFICATION_REQUIREMENT,
    )
    company_capacity = _company_evidence(
        case_id="unsupported_agent_claim_rejection",
        key="COMPANY-NINETY-DAY-CAPACITY",
        excerpt="18 consultants available within 90 days.",
        normalized_meaning=(
            "The company has consultant capacity within 90 days, not explicit "
            "30-day proof."
        ),
        category="capacity",
        field_path="capabilities.delivery_capacity.available_consultants_90_days",
    )

    return GoldenDemoCase(
        case_id="unsupported_agent_claim_rejection",
        title="Unsupported claim rejection",
        tender_evidence=(tender_staffing,),
        company_evidence=(company_capacity,),
        expected=GoldenExpectedOutcome(
            verdict=Verdict.CONDITIONAL_BID,
            missing_info=("Explicit 30-day staffing proof is missing.",),
            recommended_actions=(
                "Confirm named eight-person staffing availability within 30 days.",
            ),
            required_evidence_refs=(_ref(tender_staffing), _ref(company_capacity)),
            unsupported_claims_rejected=(
                "Unverified subcontractor bench can cover delivery surge.",
            ),
            validation_errors=("unsupported_claim",),
            decision_rules=(
                "unsupported_claims_are_rejected",
                "conditional_bid_requires_next_actions",
            ),
            rationale=(
                "CONDITIONAL_BID because "
                "GOLDEN-UNSUPPORTED-AGENT-CLAIM-REJECTION-"
                "TENDER-THIRTY-DAY-STAFFING requires faster staffing than "
                "GOLDEN-UNSUPPORTED-AGENT-CLAIM-REJECTION-"
                "COMPANY-NINETY-DAY-CAPACITY proves. The subcontractor bench "
                "claim is rejected because it has no evidence item."
            ),
        ),
    )


def _tender_evidence(
    *,
    case_id: str,
    key: str,
    excerpt: str,
    normalized_meaning: str,
    category: str,
    requirement_type: RequirementType | None,
) -> EvidenceItemState:
    return EvidenceItemState(
        evidence_id=_fixture_uuid(case_id, "evidence", key),
        evidence_key=_evidence_key(case_id, key),
        source_type=EvidenceSourceType.TENDER_DOCUMENT,
        excerpt=excerpt,
        normalized_meaning=normalized_meaning,
        category=category,
        requirement_type=requirement_type,
        confidence=0.94,
        source_metadata={
            "source_label": f"Golden case {case_id} synthetic tender page 1"
        },
        document_id=_fixture_uuid(case_id, "document"),
        chunk_id=_fixture_uuid(case_id, "chunk", "0"),
        page_start=1,
        page_end=1,
    )


def _company_evidence(
    *,
    case_id: str,
    key: str,
    excerpt: str,
    normalized_meaning: str,
    category: str,
    field_path: str,
) -> EvidenceItemState:
    return EvidenceItemState(
        evidence_id=_fixture_uuid(case_id, "evidence", key),
        evidence_key=_evidence_key(case_id, key),
        source_type=EvidenceSourceType.COMPANY_PROFILE,
        excerpt=excerpt,
        normalized_meaning=normalized_meaning,
        category=category,
        requirement_type=None,
        confidence=0.9,
        source_metadata={"source_label": f"Golden case {case_id} company profile"},
        company_id=_fixture_uuid(case_id, "company"),
        field_path=field_path,
    )


def _ref(item: EvidenceItemState) -> EvidenceRef:
    return EvidenceRef(
        evidence_key=item.evidence_key,
        source_type=item.source_type,
        evidence_id=item.evidence_id,
    )


def _evidence_key(case_id: str, key: str) -> str:
    return f"GOLDEN-{case_id.replace('_', '-').upper()}-{key}"


def _fixture_uuid(case_id: str, *parts: object) -> UUID:
    joined = ":".join([case_id, *(str(part) for part in parts)])
    return uuid5(_FIXTURE_NAMESPACE, joined)


_GOLDEN_DEMO_CASES = (
    _obvious_bid_case(),
    _hard_compliance_no_bid_case(),
    _conditional_bid_next_actions_case(),
    _conflicting_evidence_needs_review_case(),
    _missing_company_evidence_case(),
    _unsupported_agent_claim_rejection_case(),
)
