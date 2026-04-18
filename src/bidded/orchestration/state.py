from __future__ import annotations

from enum import StrEnum
from typing import Any, ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, model_validator


class StrictStateModel(BaseModel):
    """Base model for graph state artifacts with closed schemas."""

    model_config = ConfigDict(extra="forbid")


class AgentRunStatus(StrEnum):
    """Lifecycle states mirrored from the agent_runs table."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    NEEDS_HUMAN_REVIEW = "needs_human_review"


class EvidenceSourceType(StrEnum):
    """Allowed v1 evidence source types."""

    TENDER_DOCUMENT = "tender_document"
    COMPANY_PROFILE = "company_profile"


class Verdict(StrEnum):
    """Supported bid decision verdicts."""

    BID = "bid"
    NO_BID = "no_bid"
    CONDITIONAL_BID = "conditional_bid"
    NEEDS_HUMAN_REVIEW = "needs_human_review"


class SpecialistRole(StrEnum):
    """Round 1 and Round 2 specialist roles keyed in shared state."""

    COMPLIANCE = "compliance_officer"
    WIN_STRATEGIST = "win_strategist"
    DELIVERY_CFO = "delivery_cfo"
    RED_TEAM = "red_team"


class RuntimeErrorState(StrictStateModel):
    source: str = Field(min_length=1)
    message: str = Field(min_length=1)
    retryable: bool = False


class EvidenceRef(StrictStateModel):
    evidence_key: str = Field(min_length=1)
    source_type: EvidenceSourceType
    evidence_id: UUID | None = None


class DocumentChunkState(StrictStateModel):
    chunk_id: UUID
    document_id: UUID
    chunk_index: NonNegativeInt
    page_start: int = Field(gt=0)
    page_end: int = Field(gt=0)
    text: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_page_range(self) -> DocumentChunkState:
        if self.page_end < self.page_start:
            raise ValueError("page_end must be greater than or equal to page_start")
        return self


class EvidenceItemState(StrictStateModel):
    evidence_key: str = Field(min_length=1)
    source_type: EvidenceSourceType
    excerpt: str = Field(min_length=1)
    normalized_meaning: str = Field(min_length=1)
    category: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    source_metadata: dict[str, Any]
    evidence_id: UUID | None = None
    document_id: UUID | None = None
    chunk_id: UUID | None = None
    page_start: int | None = Field(default=None, gt=0)
    page_end: int | None = Field(default=None, gt=0)
    company_id: UUID | None = None
    field_path: str | None = None

    @model_validator(mode="after")
    def validate_source_provenance(self) -> EvidenceItemState:
        if "source_label" not in self.source_metadata:
            raise ValueError("source_metadata must include source_label")

        if self.source_type is EvidenceSourceType.TENDER_DOCUMENT:
            required_tender_fields = [
                self.document_id,
                self.chunk_id,
                self.page_start,
                self.page_end,
            ]
            if any(value is None for value in required_tender_fields):
                raise ValueError(
                    "tender_document evidence requires document provenance"
                )

        if self.source_type is EvidenceSourceType.COMPANY_PROFILE:
            if self.company_id is None or self.field_path is None:
                raise ValueError("company_profile evidence requires company provenance")

        if (
            self.page_start is not None
            and self.page_end is not None
            and self.page_end < self.page_start
        ):
            raise ValueError("page_end must be greater than or equal to page_start")

        return self


class ScoutFindingState(StrictStateModel):
    category: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class ScoutOutputState(StrictStateModel):
    findings: list[ScoutFindingState] = Field(default_factory=list)
    missing_info: list[str] = Field(default_factory=list)
    potential_blockers: list[str] = Field(default_factory=list)


class SpecialistMotionState(StrictStateModel):
    agent_role: SpecialistRole
    verdict: Verdict
    confidence: float = Field(ge=0, le=1)
    summary: str = Field(min_length=1)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    missing_info: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)


class RebuttalState(StrictStateModel):
    agent_role: SpecialistRole
    target_motion_role: SpecialistRole
    summary: str = Field(min_length=1)
    challenged_claims: list[str] = Field(default_factory=list)
    accepted_claims: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class ValidationIssueState(StrictStateModel):
    source: str = Field(min_length=1)
    message: str = Field(min_length=1)
    field_path: str | None = None
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class FinalDecisionState(StrictStateModel):
    verdict: Verdict
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1)
    vote_summary: dict[str, int] = Field(default_factory=dict)
    compliance_blockers: list[str] = Field(default_factory=list)
    potential_blockers: list[str] = Field(default_factory=list)
    risk_register: list[str] = Field(default_factory=list)
    missing_info: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    cited_memo: str = Field(min_length=1)
    evidence_ids: list[UUID] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class BidRunState(StrictStateModel):
    """Typed source of truth for one Bidded LangGraph run."""

    _RUNTIME_CONTROL_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "status",
            "current_step",
            "retry_counts",
            "last_error",
            "working_retrieval_results",
        }
    )
    _PERSISTED_AUDIT_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "evidence_board",
            "scout_output",
            "motions",
            "rebuttals",
            "validation_errors",
            "final_decision",
        }
    )

    run_id: UUID
    company_id: UUID
    tender_id: UUID
    document_ids: list[UUID]
    run_context: dict[str, Any] = Field(default_factory=dict)
    chunks: list[DocumentChunkState] = Field(default_factory=list)
    evidence_board: list[EvidenceItemState] = Field(default_factory=list)
    scout_output: ScoutOutputState | None = None
    motions: dict[SpecialistRole, SpecialistMotionState] = Field(default_factory=dict)
    rebuttals: dict[SpecialistRole, RebuttalState] = Field(default_factory=dict)
    validation_errors: list[ValidationIssueState] = Field(default_factory=list)
    retry_counts: dict[str, NonNegativeInt] = Field(default_factory=dict)
    final_decision: FinalDecisionState | None = None
    status: AgentRunStatus = AgentRunStatus.PENDING
    current_step: str | None = None
    last_error: RuntimeErrorState | None = None
    working_retrieval_results: list[EvidenceRef] = Field(default_factory=list)

    @classmethod
    def runtime_control_fields(cls) -> frozenset[str]:
        return cls._RUNTIME_CONTROL_FIELDS

    @classmethod
    def persisted_audit_fields(cls) -> frozenset[str]:
        return cls._PERSISTED_AUDIT_FIELDS

    @model_validator(mode="after")
    def validate_role_keyed_artifacts(self) -> BidRunState:
        for role, motion in self.motions.items():
            if motion.agent_role is not role:
                raise ValueError("motion key must match motion agent_role")

        for role, rebuttal in self.rebuttals.items():
            if rebuttal.agent_role is not role:
                raise ValueError("rebuttal key must match rebuttal agent_role")

        return self


__all__ = [
    "AgentRunStatus",
    "BidRunState",
    "DocumentChunkState",
    "EvidenceItemState",
    "EvidenceRef",
    "EvidenceSourceType",
    "FinalDecisionState",
    "RebuttalState",
    "RuntimeErrorState",
    "ScoutFindingState",
    "ScoutOutputState",
    "SpecialistMotionState",
    "SpecialistRole",
    "ValidationIssueState",
    "Verdict",
]
