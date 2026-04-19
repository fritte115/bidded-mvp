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
    "near_miss_certification_requires_exact_match",
    "hidden_shall_requirements_are_material",
    "stale_company_evidence_requires_refresh",
    "conflicting_deadlines_routes_human_review",
    "weak_margin_requires_commercial_action",
    "red_team_blockers_require_formal_evidence",
]
GoldenFixtureGroup = Literal["core", "adversarial"]
GoldenFixtureSelection = Literal["core", "adversarial", "all"]
AdversarialCategory = Literal[
    "near_miss_certification",
    "hidden_shall_requirement",
    "stale_company_evidence",
    "conflicting_deadlines",
    "weak_margin",
    "red_team_blocker_challenge",
]

_FIXTURE_NAMESPACE = uuid5(
    NAMESPACE_URL,
    "https://bidded.local/fixtures/golden-demo-cases/v1",
)


class GoldenExpectedOutcome(StrictStateModel):
    """Expected decision artifact summary for one golden demo case."""

    verdict: Verdict
    allowed_verdicts: tuple[Verdict, ...] = ()
    blockers: tuple[str, ...] = ()
    missing_info: tuple[str, ...] = ()
    recommended_actions: tuple[str, ...] = ()
    required_evidence_refs: tuple[EvidenceRef, ...] = Field(min_length=1)
    unsupported_claims_rejected: tuple[str, ...] = ()
    validation_errors: tuple[str, ...] = ()
    decision_rules: tuple[DecisionRule, ...] = Field(min_length=1)
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_allowed_verdicts(self) -> GoldenExpectedOutcome:
        if not self.allowed_verdicts:
            self.allowed_verdicts = (self.verdict,)
        if self.verdict not in self.allowed_verdicts:
            raise ValueError("primary expected verdict must be allowed")
        return self


class GoldenDemoCase(StrictStateModel):
    """Typed, evidence-backed regression fixture for a decision behavior."""

    case_id: str = Field(min_length=1, pattern=r"^[a-z0-9_]+$")
    title: str = Field(min_length=1)
    fixture_group: GoldenFixtureGroup = "core"
    adversarial_category: AdversarialCategory | None = None
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

        if self.fixture_group == "adversarial" and self.adversarial_category is None:
            raise ValueError(f"{self.case_id} must define an adversarial category")
        if self.fixture_group == "core" and self.adversarial_category is not None:
            raise ValueError(f"{self.case_id} core cases cannot set a category")

        return self


def golden_demo_cases(
    fixture_group: GoldenFixtureSelection = "core",
) -> tuple[GoldenDemoCase, ...]:
    """Return the deterministic golden case set for bid/no-bid regression tests."""

    if fixture_group == "core":
        return _GOLDEN_CORE_CASES
    if fixture_group == "adversarial":
        return _GOLDEN_ADVERSARIAL_CASES
    if fixture_group == "all":
        return (*_GOLDEN_CORE_CASES, *_GOLDEN_ADVERSARIAL_CASES)
    raise ValueError(f"Unknown golden fixture group: {fixture_group}")


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
            allowed_verdicts=(
                Verdict.CONDITIONAL_BID,
                Verdict.NEEDS_HUMAN_REVIEW,
            ),
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


def _near_miss_certification_case() -> GoldenDemoCase:
    tender_iso = _tender_evidence(
        case_id="near_miss_certification",
        key="TENDER-ACTIVE-ISO-27001",
        excerpt=(
            "Supplier shall hold an active ISO 27001 certificate covering "
            "managed hosting operations at submission."
        ),
        normalized_meaning=(
            "The tender requires active ISO 27001 certification for managed "
            "hosting at submission time."
        ),
        category="qualification_requirement",
        requirement_type=RequirementType.QUALITY_MANAGEMENT,
    )
    company_iso_9001 = _company_evidence(
        case_id="near_miss_certification",
        key="COMPANY-ISO-9001-ONLY",
        excerpt=(
            "ISO 9001 quality management certificate active; ISO 27001 audit "
            "is scheduled for Q4 2026."
        ),
        normalized_meaning=(
            "The company has active ISO 9001 and only a future ISO 27001 audit."
        ),
        category="certification",
        field_path="certifications.iso_9001",
    )

    return GoldenDemoCase(
        case_id="near_miss_certification",
        title="Adversarial near-miss certification",
        fixture_group="adversarial",
        adversarial_category="near_miss_certification",
        tender_evidence=(tender_iso,),
        company_evidence=(company_iso_9001,),
        expected=GoldenExpectedOutcome(
            verdict=Verdict.CONDITIONAL_BID,
            missing_info=(
                "Active ISO 27001 certificate covering managed hosting is missing.",
            ),
            recommended_actions=(
                "Obtain or attach active ISO 27001 proof before treating the "
                "qualification as satisfied.",
            ),
            required_evidence_refs=(_ref(tender_iso), _ref(company_iso_9001)),
            decision_rules=(
                "near_miss_certification_requires_exact_match",
                "conditional_bid_requires_next_actions",
            ),
            rationale=(
                "CONDITIONAL_BID because "
                "GOLDEN-NEAR-MISS-CERTIFICATION-TENDER-ACTIVE-ISO-27001 "
                "requires active ISO 27001, while "
                "GOLDEN-NEAR-MISS-CERTIFICATION-COMPANY-ISO-9001-ONLY proves "
                "ISO 9001 and a future ISO 27001 audit, not the required "
                "active certificate."
            ),
        ),
    )


def _hidden_shall_requirement_case() -> GoldenDemoCase:
    tender_service_desk = _tender_evidence(
        case_id="hidden_shall_requirement",
        key="TENDER-HIDDEN-HOLIDAY-SHALL",
        excerpt=(
            "Operational appendix 2.4: the supplier shall staff the service "
            "desk 08:00-18:00 CET, including Swedish public holidays."
        ),
        normalized_meaning=(
            "A shall requirement in the appendix mandates service desk staffing "
            "through Swedish public holidays."
        ),
        category="shall_requirement",
        requirement_type=RequirementType.SHALL_REQUIREMENT,
    )
    company_service_desk = _company_evidence(
        case_id="hidden_shall_requirement",
        key="COMPANY-WEEKDAY-SERVICE-DESK",
        excerpt="Service desk is staffed 08:00-17:00 CET on business weekdays.",
        normalized_meaning=(
            "The company profile proves weekday staffing but not the required "
            "holiday and extended-hour coverage."
        ),
        category="support_model",
        field_path="delivery_model.service_desk.hours",
    )

    return GoldenDemoCase(
        case_id="hidden_shall_requirement",
        title="Adversarial hidden shall requirement",
        fixture_group="adversarial",
        adversarial_category="hidden_shall_requirement",
        tender_evidence=(tender_service_desk,),
        company_evidence=(company_service_desk,),
        expected=GoldenExpectedOutcome(
            verdict=Verdict.CONDITIONAL_BID,
            missing_info=(
                "Holiday and 17:00-18:00 service desk coverage proof is missing.",
            ),
            recommended_actions=(
                "Confirm staffed coverage for Swedish public holidays and "
                "08:00-18:00 CET before submission.",
            ),
            required_evidence_refs=(
                _ref(tender_service_desk),
                _ref(company_service_desk),
            ),
            decision_rules=(
                "hidden_shall_requirements_are_material",
                "conditional_bid_requires_next_actions",
            ),
            rationale=(
                "CONDITIONAL_BID because "
                "GOLDEN-HIDDEN-SHALL-REQUIREMENT-TENDER-HIDDEN-HOLIDAY-SHALL "
                "is a material shall requirement, while "
                "GOLDEN-HIDDEN-SHALL-REQUIREMENT-COMPANY-WEEKDAY-SERVICE-DESK "
                "does not prove holiday or extended-hour coverage."
            ),
        ),
    )


def _stale_company_evidence_case() -> GoldenDemoCase:
    tender_recent_reference = _tender_evidence(
        case_id="stale_company_evidence",
        key="TENDER-RECENT-REFERENCE",
        excerpt=(
            "Supplier shall include one comparable public-sector reference "
            "completed during the last three years."
        ),
        normalized_meaning=(
            "The tender requires a comparable reference completed within the "
            "last three years."
        ),
        category="qualification_requirement",
        requirement_type=RequirementType.QUALIFICATION_REQUIREMENT,
    )
    company_old_reference = _company_evidence(
        case_id="stale_company_evidence",
        key="COMPANY-OLD-REFERENCE",
        excerpt=(
            "Municipality case-management delivery completed in 2021 with "
            "positive customer feedback."
        ),
        normalized_meaning=(
            "The company has a comparable reference, but it is older than the "
            "tender's three-year window."
        ),
        category="reference",
        field_path="reference_projects[stale_municipality_case]",
    )

    return GoldenDemoCase(
        case_id="stale_company_evidence",
        title="Adversarial stale company evidence",
        fixture_group="adversarial",
        adversarial_category="stale_company_evidence",
        tender_evidence=(tender_recent_reference,),
        company_evidence=(company_old_reference,),
        expected=GoldenExpectedOutcome(
            verdict=Verdict.CONDITIONAL_BID,
            missing_info=(
                "Comparable public-sector reference inside the three-year window "
                "is missing.",
            ),
            recommended_actions=(
                "Replace the 2021 reference with a qualifying recent reference "
                "or route for human review.",
            ),
            required_evidence_refs=(
                _ref(tender_recent_reference),
                _ref(company_old_reference),
            ),
            decision_rules=(
                "stale_company_evidence_requires_refresh",
                "conditional_bid_requires_next_actions",
            ),
            rationale=(
                "CONDITIONAL_BID because "
                "GOLDEN-STALE-COMPANY-EVIDENCE-TENDER-RECENT-REFERENCE "
                "requires recent proof, while "
                "GOLDEN-STALE-COMPANY-EVIDENCE-COMPANY-OLD-REFERENCE is "
                "comparable but stale."
            ),
        ),
    )


def _conflicting_deadlines_case() -> GoldenDemoCase:
    tender_portal_deadline = _tender_evidence(
        case_id="conflicting_deadlines",
        key="TENDER-PORTAL-DEADLINE",
        excerpt="Notice section IV: tenders must be submitted by 2026-05-01 12:00.",
        normalized_meaning=(
            "The procurement notice states a 2026-05-01 12:00 submission deadline."
        ),
        category="submission_deadline",
        requirement_type=RequirementType.SUBMISSION_DOCUMENT,
    )
    tender_appendix_deadline = _tender_evidence(
        case_id="conflicting_deadlines",
        key="TENDER-APPENDIX-DEADLINE",
        excerpt=(
            "Appendix timetable: final tenders are due in the portal by "
            "2026-05-03 16:00."
        ),
        normalized_meaning=(
            "An appendix states a later 2026-05-03 16:00 submission deadline."
        ),
        category="submission_deadline",
        requirement_type=RequirementType.SUBMISSION_DOCUMENT,
    )

    return GoldenDemoCase(
        case_id="conflicting_deadlines",
        title="Adversarial conflicting deadlines",
        fixture_group="adversarial",
        adversarial_category="conflicting_deadlines",
        tender_evidence=(tender_portal_deadline, tender_appendix_deadline),
        expected=GoldenExpectedOutcome(
            verdict=Verdict.NEEDS_HUMAN_REVIEW,
            missing_info=(
                "Tender submission deadline conflicts between notice and appendix.",
            ),
            recommended_actions=(
                "Ask an operator to confirm the controlling submission deadline "
                "before proceeding.",
            ),
            required_evidence_refs=(
                _ref(tender_portal_deadline),
                _ref(tender_appendix_deadline),
            ),
            decision_rules=("conflicting_deadlines_routes_human_review",),
            rationale=(
                "NEEDS_HUMAN_REVIEW because "
                "GOLDEN-CONFLICTING-DEADLINES-TENDER-PORTAL-DEADLINE and "
                "GOLDEN-CONFLICTING-DEADLINES-TENDER-APPENDIX-DEADLINE give "
                "different final tender deadlines."
            ),
        ),
    )


def _weak_margin_case() -> GoldenDemoCase:
    tender_rate_cap = _tender_evidence(
        case_id="weak_margin",
        key="TENDER-RATE-CAP",
        excerpt=(
            "Framework consultants may be invoiced at a maximum of SEK 8,000 "
            "per day including all delivery management overhead."
        ),
        normalized_meaning=(
            "The tender caps daily consultant revenue at SEK 8,000 including "
            "delivery overhead."
        ),
        category="commercial_term",
        requirement_type=RequirementType.CONTRACT_OBLIGATION,
    )
    company_cost = _company_evidence(
        case_id="weak_margin",
        key="COMPANY-COST-BASELINE",
        excerpt=(
            "Senior consultant delivery cost baseline is SEK 7,850 per day "
            "before delivery-management overhead."
        ),
        normalized_meaning=(
            "The company cost baseline leaves little margin before the tender's "
            "required overhead."
        ),
        category="commercial_profile",
        field_path="commercial.rate_cards.senior_consultant.cost_baseline",
    )

    return GoldenDemoCase(
        case_id="weak_margin",
        title="Adversarial weak margin",
        fixture_group="adversarial",
        adversarial_category="weak_margin",
        tender_evidence=(tender_rate_cap,),
        company_evidence=(company_cost,),
        expected=GoldenExpectedOutcome(
            verdict=Verdict.CONDITIONAL_BID,
            missing_info=("Commercial approval for weak delivery margin is missing.",),
            recommended_actions=(
                "Have Delivery/CFO approve the margin or identify lower-cost "
                "staffing before bid submission.",
            ),
            required_evidence_refs=(_ref(tender_rate_cap), _ref(company_cost)),
            decision_rules=(
                "weak_margin_requires_commercial_action",
                "conditional_bid_requires_next_actions",
            ),
            rationale=(
                "CONDITIONAL_BID because "
                "GOLDEN-WEAK-MARGIN-TENDER-RATE-CAP caps revenue, while "
                "GOLDEN-WEAK-MARGIN-COMPANY-COST-BASELINE shows the delivery "
                "cost baseline leaves weak margin before overhead."
            ),
        ),
    )


def _red_team_blocker_challenge_case() -> GoldenDemoCase:
    tender_environment = _tender_evidence(
        case_id="red_team_blocker_challenge",
        key="TENDER-ENVIRONMENT-SHOULD",
        excerpt=(
            "Suppliers should describe environmental routines. Strong routines "
            "may improve quality scoring."
        ),
        normalized_meaning=(
            "The tender treats environmental routines as quality-scored material, "
            "not as a formal exclusion or qualification blocker."
        ),
        category="award_criterion",
        requirement_type=None,
    )
    company_environment = _company_evidence(
        case_id="red_team_blocker_challenge",
        key="COMPANY-NO-ISO-14001",
        excerpt=(
            "Environmental routines exist in the company handbook; ISO 14001 is "
            "not listed as a current certification."
        ),
        normalized_meaning=(
            "The company has environmental routines but not ISO 14001 evidence."
        ),
        category="quality_profile",
        field_path="quality.environmental_routines",
    )

    return GoldenDemoCase(
        case_id="red_team_blocker_challenge",
        title="Adversarial Red Team blocker challenge",
        fixture_group="adversarial",
        adversarial_category="red_team_blocker_challenge",
        tender_evidence=(tender_environment,),
        company_evidence=(company_environment,),
        expected=GoldenExpectedOutcome(
            verdict=Verdict.CONDITIONAL_BID,
            blockers=(),
            missing_info=(
                "ISO 14001 certification is not evidenced, but not required.",
            ),
            recommended_actions=(
                "Prepare an environmental routines description for quality scoring.",
            ),
            required_evidence_refs=(
                _ref(tender_environment),
                _ref(company_environment),
            ),
            unsupported_claims_rejected=(
                "Missing ISO 14001 is a formal exclusion blocker.",
            ),
            validation_errors=("unsupported_blocker",),
            decision_rules=(
                "red_team_blockers_require_formal_evidence",
                "conditional_bid_requires_next_actions",
            ),
            rationale=(
                "CONDITIONAL_BID because "
                "GOLDEN-RED-TEAM-BLOCKER-CHALLENGE-TENDER-ENVIRONMENT-SHOULD "
                "is quality-scored, not a formal blocker, and "
                "GOLDEN-RED-TEAM-BLOCKER-CHALLENGE-COMPANY-NO-ISO-14001 "
                "shows only that ISO 14001 is not evidenced."
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


_GOLDEN_CORE_CASES = (
    _obvious_bid_case(),
    _hard_compliance_no_bid_case(),
    _conditional_bid_next_actions_case(),
    _conflicting_evidence_needs_review_case(),
    _missing_company_evidence_case(),
    _unsupported_agent_claim_rejection_case(),
)

_GOLDEN_ADVERSARIAL_CASES = (
    _near_miss_certification_case(),
    _hidden_shall_requirement_case(),
    _stale_company_evidence_case(),
    _conflicting_deadlines_case(),
    _weak_margin_case(),
    _red_team_blocker_challenge_case(),
)
