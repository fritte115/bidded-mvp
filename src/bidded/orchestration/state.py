from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any, ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, model_validator

from bidded.requirements import RequirementType


class StrictStateModel(BaseModel):
    """Base model for graph state artifacts with closed schemas."""

    model_config = ConfigDict(extra="forbid")


class StateOwnershipError(ValueError):
    """Raised when a graph node attempts an unauthorized state mutation."""


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


class GraphNodeName(StrEnum):
    """Known Bidded graph nodes with documented state ownership."""

    PREFLIGHT = "preflight"
    EVIDENCE_SCOUT = "evidence_scout"
    ROUND_1_SPECIALIST = "round_1_specialist"
    ROUND_2_REBUTTAL = "round_2_rebuttal"
    JUDGE = "judge"
    PERSIST_DECISION = "persist_decision"


class GraphNodeContract(StrictStateModel):
    """Documented read fields and owned write fields for one graph node."""

    node: GraphNodeName
    read_fields: frozenset[str] = Field(min_length=1)
    owned_write_fields: frozenset[str] = Field(min_length=1)


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
    requirement_type: RequirementType | None = None
    confidence: float = Field(ge=0, le=1)
    source_metadata: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)
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
    requirement_type: RequirementType | None = None
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
    confidence: float = Field(default=0.0, ge=0, le=1)
    summary: str = Field(min_length=1)
    challenged_claims: list[str] = Field(default_factory=list)
    accepted_claims: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class ValidationIssueState(StrictStateModel):
    source: str = Field(min_length=1)
    message: str = Field(min_length=1)
    field_path: str | None = None
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class AgentOutputState(StrictStateModel):
    agent_role: str = Field(min_length=1)
    round_name: str = Field(min_length=1)
    output_type: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    validation_errors: list[ValidationIssueState] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class FinalDecisionState(StrictStateModel):
    verdict: Verdict
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1)
    vote_summary: dict[str, int] = Field(default_factory=dict)
    disagreement_summary: str = Field(default="")
    compliance_matrix: list[dict[str, Any]] = Field(default_factory=list)
    compliance_blockers: list[str] = Field(default_factory=list)
    potential_blockers: list[str] = Field(default_factory=list)
    risk_register: list[str] = Field(default_factory=list)
    missing_info: list[str] = Field(default_factory=list)
    potential_evidence_gaps: list[str] = Field(default_factory=list)
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
            "agent_outputs",
            "final_decision",
        }
    )
    _APPEND_ONLY_LIST_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "evidence_board",
            "validation_errors",
            "agent_outputs",
        }
    )
    _WRITE_ONCE_ARTIFACT_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "scout_output",
            "final_decision",
        }
    )
    _ROLE_KEYED_REDUCER_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "motions",
            "rebuttals",
        }
    )
    _NODE_CONTRACTS: ClassVar[dict[GraphNodeName, GraphNodeContract]] = {
        GraphNodeName.PREFLIGHT: GraphNodeContract(
            node=GraphNodeName.PREFLIGHT,
            read_fields=frozenset(
                {
                    "run_id",
                    "company_id",
                    "tender_id",
                    "document_ids",
                    "run_context",
                    "chunks",
                    "evidence_board",
                }
            ),
            owned_write_fields=_RUNTIME_CONTROL_FIELDS
            | frozenset(
                {
                    "validation_errors",
                }
            ),
        ),
        GraphNodeName.EVIDENCE_SCOUT: GraphNodeContract(
            node=GraphNodeName.EVIDENCE_SCOUT,
            read_fields=frozenset(
                {
                    "run_id",
                    "company_id",
                    "tender_id",
                    "document_ids",
                    "run_context",
                    "chunks",
                    "evidence_board",
                }
            ),
            owned_write_fields=_RUNTIME_CONTROL_FIELDS
            | frozenset(
                {
                    "evidence_board",
                    "scout_output",
                    "validation_errors",
                    "agent_outputs",
                }
            ),
        ),
        GraphNodeName.ROUND_1_SPECIALIST: GraphNodeContract(
            node=GraphNodeName.ROUND_1_SPECIALIST,
            read_fields=frozenset(
                {
                    "run_context",
                    "evidence_board",
                    "scout_output",
                    "working_retrieval_results",
                }
            ),
            owned_write_fields=_RUNTIME_CONTROL_FIELDS
            | frozenset(
                {
                    "motions",
                    "validation_errors",
                    "agent_outputs",
                }
            ),
        ),
        GraphNodeName.ROUND_2_REBUTTAL: GraphNodeContract(
            node=GraphNodeName.ROUND_2_REBUTTAL,
            read_fields=frozenset(
                {
                    "run_context",
                    "evidence_board",
                    "scout_output",
                    "motions",
                    "working_retrieval_results",
                }
            ),
            owned_write_fields=_RUNTIME_CONTROL_FIELDS
            | frozenset(
                {
                    "rebuttals",
                    "validation_errors",
                    "agent_outputs",
                }
            ),
        ),
        GraphNodeName.JUDGE: GraphNodeContract(
            node=GraphNodeName.JUDGE,
            read_fields=frozenset(
                {
                    "run_context",
                    "evidence_board",
                    "scout_output",
                    "motions",
                    "rebuttals",
                    "validation_errors",
                }
            ),
            owned_write_fields=_RUNTIME_CONTROL_FIELDS
            | frozenset(
                {
                    "final_decision",
                    "validation_errors",
                    "agent_outputs",
                }
            ),
        ),
        GraphNodeName.PERSIST_DECISION: GraphNodeContract(
            node=GraphNodeName.PERSIST_DECISION,
            read_fields=frozenset(
                {
                    "run_id",
                    "company_id",
                    "tender_id",
                    "run_context",
                    "agent_outputs",
                    "final_decision",
                    "status",
                }
            ),
            owned_write_fields=_RUNTIME_CONTROL_FIELDS,
        ),
    }

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
    agent_outputs: list[AgentOutputState] = Field(default_factory=list)
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

    @classmethod
    def known_fields(cls) -> frozenset[str]:
        return frozenset(cls.model_fields)

    @classmethod
    def append_only_fields(cls) -> frozenset[str]:
        return cls._APPEND_ONLY_LIST_FIELDS | cls._WRITE_ONCE_ARTIFACT_FIELDS

    @classmethod
    def role_keyed_reducer_fields(cls) -> frozenset[str]:
        return cls._ROLE_KEYED_REDUCER_FIELDS

    @classmethod
    def node_contracts(cls) -> dict[GraphNodeName, GraphNodeContract]:
        return dict(cls._NODE_CONTRACTS)

    @classmethod
    def node_contract(cls, node: GraphNodeName | str) -> GraphNodeContract:
        try:
            node_name = GraphNodeName(node)
        except ValueError as exc:
            raise StateOwnershipError(f"Unknown graph node: {node!r}") from exc

        return cls._NODE_CONTRACTS[node_name]

    def apply_node_update(
        self,
        node: GraphNodeName | str,
        updates: Mapping[str, Any],
    ) -> BidRunState:
        """Return a validated state after applying one owned node update."""

        contract = self.node_contract(node)
        update_fields = frozenset(updates)
        unknown_fields = update_fields - self.known_fields()
        if unknown_fields:
            raise StateOwnershipError(
                f"{contract.node.value} attempted unknown fields: "
                f"{', '.join(sorted(unknown_fields))}"
            )

        unowned_fields = update_fields - contract.owned_write_fields
        if unowned_fields:
            raise StateOwnershipError(
                f"{contract.node.value} does not own: "
                f"{', '.join(sorted(unowned_fields))}"
            )

        merged_updates = {
            field: self._merge_owned_update(field, value)
            for field, value in updates.items()
        }
        payload = self.model_dump()
        payload.update(merged_updates)
        return type(self).model_validate(payload)

    def _merge_owned_update(self, field: str, value: Any) -> Any:
        if field in self._RUNTIME_CONTROL_FIELDS:
            return value

        if field in self._APPEND_ONLY_LIST_FIELDS:
            if not isinstance(value, list):
                raise StateOwnershipError(f"{field} updates must be a list")
            return [*getattr(self, field), *value]

        if field in self._WRITE_ONCE_ARTIFACT_FIELDS:
            if getattr(self, field) is not None:
                raise StateOwnershipError(f"{field} is write-once and already set")
            return value

        if field in self._ROLE_KEYED_REDUCER_FIELDS:
            return self._merge_role_keyed_artifacts(field, value)

        raise StateOwnershipError(f"{field} has no state reducer policy")

    def _merge_role_keyed_artifacts(self, field: str, value: Any) -> dict[Any, Any]:
        if not isinstance(value, Mapping):
            raise StateOwnershipError(f"{field} updates must be keyed by agent role")

        incoming = {SpecialistRole(role): artifact for role, artifact in value.items()}
        existing = getattr(self, field)
        duplicate_roles = frozenset(existing).intersection(incoming)
        if duplicate_roles:
            roles = ", ".join(sorted(role.value for role in duplicate_roles))
            raise StateOwnershipError(f"state already has {field} for: {roles}")

        return {**existing, **incoming}

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
    "AgentOutputState",
    "AgentRunStatus",
    "BidRunState",
    "DocumentChunkState",
    "EvidenceItemState",
    "EvidenceRef",
    "EvidenceSourceType",
    "FinalDecisionState",
    "GraphNodeContract",
    "GraphNodeName",
    "RequirementType",
    "RebuttalState",
    "RuntimeErrorState",
    "ScoutFindingState",
    "ScoutOutputState",
    "SpecialistMotionState",
    "SpecialistRole",
    "StateOwnershipError",
    "ValidationIssueState",
    "Verdict",
]
