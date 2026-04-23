from __future__ import annotations

from uuid import UUID

import pytest

from bidded.agents.schemas import AgentRole, VoteSummary
from bidded.llm import anthropic_swarm
from bidded.llm.anthropic_swarm import (
    AnthropicEvidenceScoutModel,
    AnthropicJudgeModel,
    AnthropicRound1Model,
    AnthropicRound2Model,
)
from bidded.orchestration.evidence_scout import EvidenceScoutRequest
from bidded.orchestration.judge import JudgeDecisionRequest
from bidded.orchestration.specialist_motions import Round1SpecialistRequest
from bidded.orchestration.specialist_rebuttals import Round2RebuttalRequest
from bidded.orchestration.state import (
    EvidenceItemState,
    EvidenceSourceType,
    RebuttalState,
    ScoutOutputState,
    SpecialistMotionState,
    SpecialistRole,
    Verdict,
)
from bidded.requirements import RequirementType

RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
COMPANY_ID = UUID("22222222-2222-4222-8222-222222222222")
TENDER_ID = UUID("33333333-3333-4333-8333-333333333333")
DOCUMENT_ID = UUID("44444444-4444-4444-8444-444444444444")
CHUNK_ID = UUID("55555555-5555-4555-8555-555555555555")
EVIDENCE_ID = UUID("66666666-6666-4666-8666-666666666666")


@pytest.fixture
def anthropic_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []

    def fake_complete_json(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        return {}

    monkeypatch.setattr(anthropic_swarm, "anthropic_complete_json", fake_complete_json)
    return calls


def test_evidence_scout_uses_fast_model(
    anthropic_calls: list[dict[str, object]],
) -> None:
    model = AnthropicEvidenceScoutModel(api_key="sk-ant-test", model="claude-haiku")

    model.extract(_scout_request())

    assert anthropic_calls[0]["model"] == "claude-haiku"


def test_round_1_routes_win_and_delivery_to_fast_model(
    anthropic_calls: list[dict[str, object]],
) -> None:
    model = AnthropicRound1Model(
        api_key="sk-ant-test",
        fast_model="claude-haiku",
        reasoning_model="claude-sonnet",
    )

    model.draft_motion(_round_1_request(AgentRole.WIN_STRATEGIST))
    model.draft_motion(_round_1_request(AgentRole.DELIVERY_CFO))

    assert [call["model"] for call in anthropic_calls] == [
        "claude-haiku",
        "claude-haiku",
    ]


def test_round_1_compliance_escalates_for_formal_blocker_evidence(
    anthropic_calls: list[dict[str, object]],
) -> None:
    model = AnthropicRound1Model(
        api_key="sk-ant-test",
        fast_model="claude-haiku",
        reasoning_model="claude-sonnet",
    )

    model.draft_motion(
        _round_1_request(
            AgentRole.COMPLIANCE_OFFICER,
            evidence_board=(
                _evidence_item(
                    requirement_type=RequirementType.QUALIFICATION_REQUIREMENT,
                ),
            ),
        )
    )

    assert anthropic_calls[0]["model"] == "claude-sonnet"


def test_round_1_red_team_uses_reasoning_model(
    anthropic_calls: list[dict[str, object]],
) -> None:
    model = AnthropicRound1Model(
        api_key="sk-ant-test",
        fast_model="claude-haiku",
        reasoning_model="claude-sonnet",
    )

    model.draft_motion(_round_1_request(AgentRole.RED_TEAM))

    assert anthropic_calls[0]["model"] == "claude-sonnet"


def test_round_2_non_red_team_uses_fast_model(
    anthropic_calls: list[dict[str, object]],
) -> None:
    model = AnthropicRound2Model(
        api_key="sk-ant-test",
        fast_model="claude-haiku",
        reasoning_model="claude-sonnet",
    )

    model.draft_rebuttal(_round_2_request(AgentRole.WIN_STRATEGIST))

    assert anthropic_calls[0]["model"] == "claude-haiku"


def test_round_2_red_team_escalates_for_positive_peer_vote(
    anthropic_calls: list[dict[str, object]],
) -> None:
    model = AnthropicRound2Model(
        api_key="sk-ant-test",
        fast_model="claude-haiku",
        reasoning_model="claude-sonnet",
    )

    model.draft_rebuttal(_round_2_request(AgentRole.RED_TEAM))

    assert anthropic_calls[0]["model"] == "claude-sonnet"


def test_judge_always_uses_reasoning_model(
    anthropic_calls: list[dict[str, object]],
) -> None:
    model = AnthropicJudgeModel(api_key="sk-ant-test", model="claude-sonnet")

    model.decide(_judge_request())

    assert anthropic_calls[0]["model"] == "claude-sonnet"


def test_single_routing_uses_legacy_model_for_dynamic_roles(
    anthropic_calls: list[dict[str, object]],
) -> None:
    round_1 = AnthropicRound1Model(
        api_key="sk-ant-test",
        model="claude-legacy",
        fast_model="claude-haiku",
        reasoning_model="claude-sonnet",
        model_routing="single",
    )
    round_2 = AnthropicRound2Model(
        api_key="sk-ant-test",
        model="claude-legacy",
        fast_model="claude-haiku",
        reasoning_model="claude-sonnet",
        model_routing="single",
    )

    round_1.draft_motion(_round_1_request(AgentRole.RED_TEAM))
    round_2.draft_rebuttal(_round_2_request(AgentRole.RED_TEAM))

    assert [call["model"] for call in anthropic_calls] == [
        "claude-legacy",
        "claude-legacy",
    ]


def _scout_request(
    *,
    evidence_board: tuple[EvidenceItemState, ...] | None = None,
) -> EvidenceScoutRequest:
    return EvidenceScoutRequest(
        run_id=RUN_ID,
        company_id=COMPANY_ID,
        tender_id=TENDER_ID,
        document_ids=(DOCUMENT_ID,),
        categories=("shall_requirement",),
        retrieved_chunks=(),
        evidence_board=evidence_board or (_evidence_item(),),
    )


def _round_1_request(
    role: AgentRole,
    *,
    evidence_board: tuple[EvidenceItemState, ...] | None = None,
) -> Round1SpecialistRequest:
    return Round1SpecialistRequest(
        run_id=RUN_ID,
        company_id=COMPANY_ID,
        tender_id=TENDER_ID,
        document_ids=(DOCUMENT_ID,),
        agent_role=role,
        evidence_board=evidence_board or (_evidence_item(),),
        scout_output=ScoutOutputState(),
    )


def _round_2_request(role: AgentRole) -> Round2RebuttalRequest:
    return Round2RebuttalRequest(
        run_id=RUN_ID,
        company_id=COMPANY_ID,
        tender_id=TENDER_ID,
        document_ids=(DOCUMENT_ID,),
        agent_role=role,
        evidence_board=(_evidence_item(),),
        scout_output=ScoutOutputState(),
        motions={
            AgentRole.COMPLIANCE_OFFICER: _motion(SpecialistRole.COMPLIANCE),
            AgentRole.WIN_STRATEGIST: _motion(SpecialistRole.WIN_STRATEGIST),
            AgentRole.DELIVERY_CFO: _motion(SpecialistRole.DELIVERY_CFO),
            AgentRole.RED_TEAM: _motion(
                SpecialistRole.RED_TEAM,
                verdict=Verdict.NO_BID,
            ),
        },
        focus_points=(),
    )


def _judge_request() -> JudgeDecisionRequest:
    return JudgeDecisionRequest(
        run_id=RUN_ID,
        company_id=COMPANY_ID,
        tender_id=TENDER_ID,
        document_ids=(DOCUMENT_ID,),
        evidence_board=(_evidence_item(),),
        scout_output=ScoutOutputState(),
        motions={
            AgentRole.COMPLIANCE_OFFICER: _motion(SpecialistRole.COMPLIANCE),
            AgentRole.WIN_STRATEGIST: _motion(SpecialistRole.WIN_STRATEGIST),
            AgentRole.DELIVERY_CFO: _motion(SpecialistRole.DELIVERY_CFO),
            AgentRole.RED_TEAM: _motion(SpecialistRole.RED_TEAM),
        },
        rebuttals={
            AgentRole.COMPLIANCE_OFFICER: _rebuttal(SpecialistRole.COMPLIANCE),
            AgentRole.WIN_STRATEGIST: _rebuttal(SpecialistRole.WIN_STRATEGIST),
            AgentRole.DELIVERY_CFO: _rebuttal(SpecialistRole.DELIVERY_CFO),
            AgentRole.RED_TEAM: _rebuttal(SpecialistRole.RED_TEAM),
        },
        vote_summary=VoteSummary(conditional_bid=4),
    )


def _motion(
    role: SpecialistRole,
    *,
    verdict: Verdict = Verdict.CONDITIONAL_BID,
) -> SpecialistMotionState:
    return SpecialistMotionState(
        agent_role=role,
        verdict=verdict,
        confidence=0.72,
        summary=f"{role.value} summary.",
    )


def _rebuttal(role: SpecialistRole) -> RebuttalState:
    return RebuttalState(
        agent_role=role,
        target_motion_role=SpecialistRole.WIN_STRATEGIST,
        confidence=0.6,
        summary=f"{role.value} rebuttal.",
    )


def _evidence_item(
    *,
    requirement_type: RequirementType | None = RequirementType.SHALL_REQUIREMENT,
) -> EvidenceItemState:
    return EvidenceItemState(
        evidence_id=EVIDENCE_ID,
        evidence_key="TENDER-REQ-001",
        source_type=EvidenceSourceType.TENDER_DOCUMENT,
        excerpt="The supplier must provide ISO 27001 certification.",
        normalized_meaning="ISO 27001 certification is mandatory.",
        category="shall_requirement",
        requirement_type=requirement_type,
        confidence=0.94,
        source_metadata={"source_label": "Tender page 1"},
        document_id=DOCUMENT_ID,
        chunk_id=CHUNK_ID,
        page_start=1,
        page_end=1,
    )
