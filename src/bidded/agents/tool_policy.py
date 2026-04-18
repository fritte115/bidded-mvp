from __future__ import annotations

from enum import StrEnum
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictAgentPolicyModel(BaseModel):
    """Base model for closed agent policy contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class AgentPolicySubject(StrEnum):
    """Actors with explicit Bidded v1 tool policies."""

    EVIDENCE_SCOUT = "evidence_scout"
    ROUND_1_SPECIALIST = "round_1_specialist"
    ROUND_2_REBUTTAL = "round_2_rebuttal"
    JUDGE = "judge"
    ORCHESTRATOR = "orchestrator"


class ToolCapability(StrEnum):
    """High-level capabilities an actor may be granted."""

    BOUNDED_RETRIEVAL = "bounded_retrieval"
    PROPOSE_EVIDENCE_CANDIDATES = "propose_evidence_candidates"
    SUPABASE_WRITES = "supabase_writes"
    STATUS_TRANSITIONS = "status_transitions"
    VALIDATION = "validation"
    PERSIST_EVIDENCE_ITEMS = "persist_evidence_items"
    PERSIST_AGENT_OUTPUTS = "persist_agent_outputs"
    PERSIST_BID_DECISIONS = "persist_bid_decisions"


class ForbiddenAgentTool(StrEnum):
    """Tool classes LLM agents must not receive in Bidded v1."""

    ARBITRARY_WEB_SEARCH = "arbitrary_web_search"
    FILESYSTEM_ACCESS = "filesystem_access"
    CODE_EXECUTION = "code_execution"
    DIRECT_DATABASE_MUTATION = "direct_database_mutation"
    NEW_EXTERNAL_SOURCES = "new_external_sources"


class PolicyArtifact(StrEnum):
    """Shared artifacts that tool policies may allow reading or writing."""

    EVIDENCE_BOARD = "evidence_board"
    EVIDENCE_CANDIDATES = "evidence_candidates"
    EVIDENCE_ITEMS = "evidence_items"
    AGENT_OUTPUTS = "agent_outputs"
    BID_DECISIONS = "bid_decisions"
    FINAL_DECISION = "final_decision"
    MISSING_INFO = "missing_info"
    OWN_MOTION = "own_motion"
    OWN_REBUTTAL = "own_rebuttal"
    POTENTIAL_EVIDENCE_GAPS = "potential_evidence_gaps"
    RUN_STATUS = "run_status"
    VALIDATION_ERRORS = "validation_errors"
    VALIDATED_MOTIONS = "validated_motions"
    VALIDATED_REBUTTALS = "validated_rebuttals"


class AgentToolPolicy(StrictAgentPolicyModel):
    """Allowed capabilities and artifacts for one actor."""

    _LLM_FORBIDDEN_TOOLS: ClassVar[frozenset[ForbiddenAgentTool]] = frozenset(
        ForbiddenAgentTool
    )
    _LLM_FORBIDDEN_CAPABILITIES: ClassVar[frozenset[ToolCapability]] = frozenset(
        {
            ToolCapability.SUPABASE_WRITES,
            ToolCapability.STATUS_TRANSITIONS,
            ToolCapability.VALIDATION,
            ToolCapability.PERSIST_EVIDENCE_ITEMS,
            ToolCapability.PERSIST_AGENT_OUTPUTS,
            ToolCapability.PERSIST_BID_DECISIONS,
        }
    )

    subject: AgentPolicySubject
    llm_agent: bool = True
    allowed_capabilities: frozenset[ToolCapability] = Field(default_factory=frozenset)
    readable_artifacts: frozenset[PolicyArtifact] = Field(default_factory=frozenset)
    writable_artifacts: frozenset[PolicyArtifact] = Field(default_factory=frozenset)
    retrieval_scope_fields: frozenset[str] = Field(default_factory=frozenset)
    denied_tools: frozenset[ForbiddenAgentTool] = Field(
        default_factory=lambda: frozenset(ForbiddenAgentTool)
    )

    def allows(self, capability: ToolCapability | str) -> bool:
        return ToolCapability(capability) in self.allowed_capabilities

    @model_validator(mode="after")
    def validate_llm_policy(self) -> AgentToolPolicy:
        if not self.llm_agent:
            return self

        if not self._LLM_FORBIDDEN_TOOLS <= self.denied_tools:
            raise ValueError("LLM agent policies must deny all forbidden v1 tools")

        forbidden_capabilities = self.allowed_capabilities.intersection(
            self._LLM_FORBIDDEN_CAPABILITIES
        )
        if forbidden_capabilities:
            names = ", ".join(
                sorted(capability.value for capability in forbidden_capabilities)
            )
            raise ValueError(f"LLM agent policy cannot allow: {names}")

        return self


_AGENT_TOOL_POLICIES: dict[AgentPolicySubject, AgentToolPolicy] = {
    AgentPolicySubject.EVIDENCE_SCOUT: AgentToolPolicy(
        subject=AgentPolicySubject.EVIDENCE_SCOUT,
        allowed_capabilities=frozenset(
            {
                ToolCapability.BOUNDED_RETRIEVAL,
                ToolCapability.PROPOSE_EVIDENCE_CANDIDATES,
            }
        ),
        writable_artifacts=frozenset({PolicyArtifact.EVIDENCE_CANDIDATES}),
        retrieval_scope_fields=frozenset({"run_id", "tender_id", "company_id"}),
    ),
    AgentPolicySubject.ROUND_1_SPECIALIST: AgentToolPolicy(
        subject=AgentPolicySubject.ROUND_1_SPECIALIST,
        readable_artifacts=frozenset({PolicyArtifact.EVIDENCE_BOARD}),
        writable_artifacts=frozenset(
            {
                PolicyArtifact.OWN_MOTION,
                PolicyArtifact.MISSING_INFO,
                PolicyArtifact.POTENTIAL_EVIDENCE_GAPS,
            }
        ),
    ),
    AgentPolicySubject.ROUND_2_REBUTTAL: AgentToolPolicy(
        subject=AgentPolicySubject.ROUND_2_REBUTTAL,
        readable_artifacts=frozenset(
            {
                PolicyArtifact.EVIDENCE_BOARD,
                PolicyArtifact.VALIDATED_MOTIONS,
            }
        ),
        writable_artifacts=frozenset(
            {
                PolicyArtifact.OWN_REBUTTAL,
                PolicyArtifact.MISSING_INFO,
                PolicyArtifact.POTENTIAL_EVIDENCE_GAPS,
            }
        ),
    ),
    AgentPolicySubject.JUDGE: AgentToolPolicy(
        subject=AgentPolicySubject.JUDGE,
        readable_artifacts=frozenset(
            {
                PolicyArtifact.EVIDENCE_BOARD,
                PolicyArtifact.VALIDATED_MOTIONS,
                PolicyArtifact.VALIDATED_REBUTTALS,
            }
        ),
        writable_artifacts=frozenset({PolicyArtifact.FINAL_DECISION}),
    ),
    AgentPolicySubject.ORCHESTRATOR: AgentToolPolicy(
        subject=AgentPolicySubject.ORCHESTRATOR,
        llm_agent=False,
        allowed_capabilities=frozenset(
            {
                ToolCapability.SUPABASE_WRITES,
                ToolCapability.STATUS_TRANSITIONS,
                ToolCapability.VALIDATION,
                ToolCapability.PERSIST_EVIDENCE_ITEMS,
                ToolCapability.PERSIST_AGENT_OUTPUTS,
                ToolCapability.PERSIST_BID_DECISIONS,
            }
        ),
        writable_artifacts=frozenset(
            {
                PolicyArtifact.EVIDENCE_ITEMS,
                PolicyArtifact.AGENT_OUTPUTS,
                PolicyArtifact.BID_DECISIONS,
                PolicyArtifact.RUN_STATUS,
                PolicyArtifact.VALIDATION_ERRORS,
            }
        ),
        denied_tools=frozenset(),
    ),
}


def agent_tool_policy(subject: AgentPolicySubject | str) -> AgentToolPolicy:
    """Return the immutable v1 tool policy for one Bidded actor."""

    return _AGENT_TOOL_POLICIES[AgentPolicySubject(subject)]


def all_agent_tool_policies() -> dict[AgentPolicySubject, AgentToolPolicy]:
    """Return all immutable v1 tool policies keyed by actor."""

    return dict(_AGENT_TOOL_POLICIES)


__all__ = [
    "AgentPolicySubject",
    "AgentToolPolicy",
    "ForbiddenAgentTool",
    "PolicyArtifact",
    "ToolCapability",
    "agent_tool_policy",
    "all_agent_tool_policies",
]
