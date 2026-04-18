from __future__ import annotations

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, model_validator


class StrictAgentOutputModel(BaseModel):
    """Base model for closed, audit-friendly agent output artifacts."""

    model_config = ConfigDict(extra="forbid")


class AgentRole(StrEnum):
    """Agent roles that can produce validated Bidded artifacts."""

    EVIDENCE_SCOUT = "evidence_scout"
    COMPLIANCE_OFFICER = "compliance_officer"
    WIN_STRATEGIST = "win_strategist"
    DELIVERY_CFO = "delivery_cfo"
    RED_TEAM = "red_team"
    JUDGE = "judge"


_SPECIALIST_ROLES = frozenset(
    {
        AgentRole.COMPLIANCE_OFFICER,
        AgentRole.WIN_STRATEGIST,
        AgentRole.DELIVERY_CFO,
        AgentRole.RED_TEAM,
    }
)


class BidVerdict(StrEnum):
    """Bid/no-bid vote values used by specialist motions."""

    BID = "bid"
    NO_BID = "no_bid"
    CONDITIONAL_BID = "conditional_bid"


class FinalVerdict(StrEnum):
    """Final Judge verdict values."""

    BID = "bid"
    NO_BID = "no_bid"
    CONDITIONAL_BID = "conditional_bid"
    NEEDS_HUMAN_REVIEW = "needs_human_review"


class SourceType(StrEnum):
    """Allowed v1 evidence source types."""

    TENDER_DOCUMENT = "tender_document"
    COMPANY_PROFILE = "company_profile"


class ScoutCategory(StrEnum):
    """Six-pack tender fact categories extracted by Evidence Scout."""

    DEADLINE = "deadline"
    SHALL_REQUIREMENT = "shall_requirement"
    QUALIFICATION_CRITERION = "qualification_criterion"
    EVALUATION_CRITERION = "evaluation_criterion"
    CONTRACT_RISK = "contract_risk"
    REQUIRED_SUBMISSION_DOCUMENT = "required_submission_document"


class EvidenceReference(StrictAgentOutputModel):
    evidence_key: str = Field(min_length=1)
    source_type: SourceType
    evidence_id: UUID | None = None


def _require_resolved_evidence_ids(
    evidence_refs: list[EvidenceReference],
    *,
    field_name: str,
) -> None:
    missing_ids = [
        evidence_ref.evidence_key
        for evidence_ref in evidence_refs
        if evidence_ref.evidence_id is None
    ]
    if missing_ids:
        joined_keys = ", ".join(missing_ids)
        raise ValueError(
            f"{field_name} evidence_refs require evidence_id: {joined_keys}"
        )


class AgentValidationError(StrictAgentOutputModel):
    code: str = Field(default="schema_validation", min_length=1)
    message: str = Field(min_length=1)
    field_path: str | None = None
    retryable: bool = True
    evidence_refs: list[EvidenceReference] = Field(default_factory=list)


class EvidenceScoutFinding(StrictAgentOutputModel):
    category: ScoutCategory
    claim: str = Field(min_length=1)
    evidence_refs: list[EvidenceReference] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_evidence_ids(self) -> EvidenceScoutFinding:
        _require_resolved_evidence_ids(
            self.evidence_refs,
            field_name="evidence scout finding",
        )
        return self


class SupportedClaim(StrictAgentOutputModel):
    claim: str = Field(min_length=1)
    evidence_refs: list[EvidenceReference] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_evidence_ids(self) -> SupportedClaim:
        _require_resolved_evidence_ids(
            self.evidence_refs,
            field_name="supported claim",
        )
        return self


class TargetedDisagreement(StrictAgentOutputModel):
    target_role: AgentRole
    disputed_claim: str = Field(min_length=1)
    rebuttal: str = Field(min_length=1)
    evidence_refs: list[EvidenceReference] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_evidence_ids(self) -> TargetedDisagreement:
        _require_resolved_evidence_ids(
            self.evidence_refs,
            field_name="targeted disagreement",
        )
        return self


class UnsupportedClaim(StrictAgentOutputModel):
    target_role: AgentRole
    claim: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class EvidenceScoutOutput(StrictAgentOutputModel):
    agent_role: Literal[AgentRole.EVIDENCE_SCOUT] = AgentRole.EVIDENCE_SCOUT
    findings: list[EvidenceScoutFinding] = Field(default_factory=list)
    missing_info: list[str] = Field(default_factory=list)
    potential_blockers: list[SupportedClaim] = Field(default_factory=list)
    validation_errors: list[AgentValidationError] = Field(default_factory=list)


class BlockerChallenge(StrictAgentOutputModel):
    blocker: str = Field(min_length=1)
    position: Literal["uphold", "downgrade", "reject"]
    rationale: str = Field(min_length=1)
    evidence_refs: list[EvidenceReference] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_evidence_ids(self) -> BlockerChallenge:
        _require_resolved_evidence_ids(
            self.evidence_refs,
            field_name="blocker challenge",
        )
        return self


class Round1Motion(StrictAgentOutputModel):
    agent_role: AgentRole
    vote: BidVerdict
    confidence: float = Field(ge=0, le=1)
    top_findings: list[SupportedClaim] = Field(default_factory=list)
    role_specific_risks: list[SupportedClaim] = Field(default_factory=list)
    formal_blockers: list[SupportedClaim] = Field(default_factory=list)
    potential_blockers: list[SupportedClaim] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    missing_info: list[str] = Field(default_factory=list)
    potential_evidence_gaps: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    validation_errors: list[AgentValidationError] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_specialist_motion(self) -> Round1Motion:
        if self.agent_role not in _SPECIALIST_ROLES:
            raise ValueError("round 1 motion agent_role must be a specialist")

        if (
            self.formal_blockers
            and self.agent_role is not AgentRole.COMPLIANCE_OFFICER
        ):
            raise ValueError(
                "formal_blockers are only valid for compliance_officer motions"
            )

        return self


class Round2Rebuttal(StrictAgentOutputModel):
    agent_role: AgentRole
    target_roles: list[AgentRole] = Field(min_length=1)
    targeted_disagreements: list[TargetedDisagreement] = Field(default_factory=list)
    unsupported_claims: list[UnsupportedClaim] = Field(default_factory=list)
    blocker_challenges: list[BlockerChallenge] = Field(default_factory=list)
    revised_stance: BidVerdict | None = None
    confidence: float = Field(ge=0, le=1)
    evidence_refs: list[EvidenceReference] = Field(default_factory=list)
    missing_info: list[str] = Field(default_factory=list)
    potential_evidence_gaps: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    validation_errors: list[AgentValidationError] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_specialist_rebuttal(self) -> Round2Rebuttal:
        if self.agent_role not in _SPECIALIST_ROLES:
            raise ValueError("round 2 rebuttal agent_role must be a specialist")

        if any(role not in _SPECIALIST_ROLES for role in self.target_roles):
            raise ValueError("round 2 rebuttal target_roles must be specialists")

        return self


class VoteSummary(StrictAgentOutputModel):
    bid: NonNegativeInt = 0
    no_bid: NonNegativeInt = 0
    conditional_bid: NonNegativeInt = 0


class ComplianceMatrixItem(StrictAgentOutputModel):
    requirement: str = Field(min_length=1)
    status: Literal["met", "unmet", "unknown"]
    assessment: str = Field(min_length=1)
    evidence_refs: list[EvidenceReference] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_evidence_ids(self) -> ComplianceMatrixItem:
        _require_resolved_evidence_ids(
            self.evidence_refs,
            field_name="compliance matrix item",
        )
        return self


class RiskRegisterItem(StrictAgentOutputModel):
    risk: str = Field(min_length=1)
    severity: Literal["low", "medium", "high"]
    mitigation: str = Field(min_length=1)
    evidence_refs: list[EvidenceReference] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_evidence_ids(self) -> RiskRegisterItem:
        _require_resolved_evidence_ids(
            self.evidence_refs,
            field_name="risk register item",
        )
        return self


class JudgeDecision(StrictAgentOutputModel):
    agent_role: Literal[AgentRole.JUDGE] = AgentRole.JUDGE
    verdict: FinalVerdict
    confidence: float = Field(ge=0, le=1)
    vote_summary: VoteSummary
    disagreement_summary: str = Field(min_length=1)
    compliance_matrix: list[ComplianceMatrixItem] = Field(default_factory=list)
    compliance_blockers: list[SupportedClaim] = Field(default_factory=list)
    potential_blockers: list[SupportedClaim] = Field(default_factory=list)
    risk_register: list[RiskRegisterItem] = Field(default_factory=list)
    missing_info: list[str] = Field(default_factory=list)
    potential_evidence_gaps: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    cited_memo: str = Field(min_length=1)
    evidence_ids: list[UUID] = Field(min_length=1)
    evidence_refs: list[EvidenceReference] = Field(default_factory=list)
    validation_errors: list[AgentValidationError] = Field(default_factory=list)


__all__ = [
    "AgentRole",
    "AgentValidationError",
    "BidVerdict",
    "BlockerChallenge",
    "ComplianceMatrixItem",
    "EvidenceScoutFinding",
    "EvidenceScoutOutput",
    "EvidenceReference",
    "FinalVerdict",
    "JudgeDecision",
    "Round1Motion",
    "Round2Rebuttal",
    "RiskRegisterItem",
    "ScoutCategory",
    "SourceType",
    "StrictAgentOutputModel",
    "SupportedClaim",
    "TargetedDisagreement",
    "UnsupportedClaim",
    "VoteSummary",
]
