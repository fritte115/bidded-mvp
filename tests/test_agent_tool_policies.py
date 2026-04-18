from __future__ import annotations

from bidded.agents import (
    AgentPolicySubject,
    ForbiddenAgentTool,
    PolicyArtifact,
    ToolCapability,
    agent_tool_policy,
    all_agent_tool_policies,
)


def test_evidence_scout_policy_limits_retrieval_scope_and_persistence() -> None:
    policy = agent_tool_policy(AgentPolicySubject.EVIDENCE_SCOUT)

    assert policy.allows(ToolCapability.BOUNDED_RETRIEVAL)
    assert policy.allows(ToolCapability.PROPOSE_EVIDENCE_CANDIDATES)
    assert policy.retrieval_scope_fields == frozenset(
        {"run_id", "tender_id", "company_id"}
    )
    assert PolicyArtifact.EVIDENCE_CANDIDATES in policy.writable_artifacts
    assert PolicyArtifact.EVIDENCE_ITEMS not in policy.writable_artifacts
    assert not policy.allows(ToolCapability.PERSIST_EVIDENCE_ITEMS)


def test_specialist_policies_read_board_and_write_only_owned_artifacts() -> None:
    allowed_writes = frozenset(
        {
            PolicyArtifact.OWN_MOTION,
            PolicyArtifact.OWN_REBUTTAL,
            PolicyArtifact.MISSING_INFO,
            PolicyArtifact.POTENTIAL_EVIDENCE_GAPS,
        }
    )

    round_1 = agent_tool_policy(AgentPolicySubject.ROUND_1_SPECIALIST)
    round_2 = agent_tool_policy(AgentPolicySubject.ROUND_2_REBUTTAL)

    assert PolicyArtifact.EVIDENCE_BOARD in round_1.readable_artifacts
    assert PolicyArtifact.OWN_MOTION in round_1.writable_artifacts
    assert PolicyArtifact.MISSING_INFO in round_1.writable_artifacts
    assert PolicyArtifact.POTENTIAL_EVIDENCE_GAPS in round_1.writable_artifacts
    assert round_1.writable_artifacts <= allowed_writes
    assert PolicyArtifact.EVIDENCE_BOARD not in round_1.writable_artifacts
    assert PolicyArtifact.VALIDATED_MOTIONS not in round_1.readable_artifacts

    assert PolicyArtifact.EVIDENCE_BOARD in round_2.readable_artifacts
    assert PolicyArtifact.VALIDATED_MOTIONS in round_2.readable_artifacts
    assert PolicyArtifact.OWN_REBUTTAL in round_2.writable_artifacts
    assert PolicyArtifact.MISSING_INFO in round_2.writable_artifacts
    assert PolicyArtifact.POTENTIAL_EVIDENCE_GAPS in round_2.writable_artifacts
    assert round_2.writable_artifacts <= allowed_writes
    assert PolicyArtifact.EVIDENCE_BOARD not in round_2.writable_artifacts
    assert not round_1.allows(ToolCapability.SUPABASE_WRITES)
    assert not round_2.allows(ToolCapability.SUPABASE_WRITES)


def test_judge_policy_reads_validated_inputs_and_writes_only_final_decision() -> None:
    policy = agent_tool_policy(AgentPolicySubject.JUDGE)

    assert policy.readable_artifacts == frozenset(
        {
            PolicyArtifact.EVIDENCE_BOARD,
            PolicyArtifact.VALIDATED_MOTIONS,
            PolicyArtifact.VALIDATED_REBUTTALS,
        }
    )
    assert policy.writable_artifacts == frozenset({PolicyArtifact.FINAL_DECISION})
    assert not policy.allows(ToolCapability.SUPABASE_WRITES)
    assert not policy.allows(ToolCapability.PERSIST_BID_DECISIONS)


def test_orchestrator_policy_owns_persistence_validation_and_status() -> None:
    policy = agent_tool_policy(AgentPolicySubject.ORCHESTRATOR)

    assert policy.llm_agent is False
    assert {
        ToolCapability.SUPABASE_WRITES,
        ToolCapability.STATUS_TRANSITIONS,
        ToolCapability.VALIDATION,
        ToolCapability.PERSIST_EVIDENCE_ITEMS,
        ToolCapability.PERSIST_AGENT_OUTPUTS,
        ToolCapability.PERSIST_BID_DECISIONS,
    } <= policy.allowed_capabilities
    assert {
        PolicyArtifact.EVIDENCE_ITEMS,
        PolicyArtifact.AGENT_OUTPUTS,
        PolicyArtifact.BID_DECISIONS,
        PolicyArtifact.RUN_STATUS,
        PolicyArtifact.VALIDATION_ERRORS,
    } <= policy.writable_artifacts


def test_llm_agent_policies_deny_unsafe_tools_and_external_sources() -> None:
    llm_policies = [
        policy for policy in all_agent_tool_policies().values() if policy.llm_agent
    ]

    assert {policy.subject for policy in llm_policies} == {
        AgentPolicySubject.EVIDENCE_SCOUT,
        AgentPolicySubject.ROUND_1_SPECIALIST,
        AgentPolicySubject.ROUND_2_REBUTTAL,
        AgentPolicySubject.JUDGE,
    }
    for policy in llm_policies:
        assert set(ForbiddenAgentTool) <= policy.denied_tools
        assert not policy.allows(ToolCapability.SUPABASE_WRITES)
        assert not policy.allows(ToolCapability.PERSIST_AGENT_OUTPUTS)
        assert not policy.allows(ToolCapability.PERSIST_BID_DECISIONS)
        assert PolicyArtifact.BID_DECISIONS not in policy.writable_artifacts
