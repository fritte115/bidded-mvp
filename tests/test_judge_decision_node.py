from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import UUID

import pytest

from bidded.agents import AgentRole
from bidded.orchestration import (
    AgentRunStatus,
    BidRunState,
    DocumentChunkState,
    EvidenceItemState,
    EvidenceSourceType,
    GraphRouteNode,
    Verdict,
    build_decision_persistence_handler,
    build_judge_handler,
    build_round_1_specialist_handler,
    build_round_2_rebuttal_handler,
    default_graph_node_handlers,
    run_bidded_graph_shell,
)
from bidded.orchestration.judge import JudgeDecisionRequest

RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
COMPANY_ID = UUID("22222222-2222-4222-8222-222222222222")
TENDER_ID = UUID("33333333-3333-4333-8333-333333333333")
DOCUMENT_ID = UUID("44444444-4444-4444-8444-444444444444")
CHUNK_ID = UUID("55555555-5555-4555-8555-555555555555")
TENDER_EVIDENCE_ID = UUID("66666666-6666-4666-8666-666666666666")
COMPANY_EVIDENCE_ID = UUID("77777777-7777-4777-8777-777777777777")


class RecordingJudgeModel:
    def __init__(self, verdict: str) -> None:
        self.verdict = verdict
        self.requests: list[JudgeDecisionRequest] = []

    def decide(self, request: JudgeDecisionRequest) -> dict[str, Any]:
        self.requests.append(request)
        payload = _judge_payload(
            verdict=self.verdict,
            vote_summary=request.vote_summary.model_dump(mode="json"),
        )
        if self.verdict == "needs_human_review":
            payload["missing_info"] = [
                "Conflicting staffing and compliance evidence needs review."
            ]
            payload["potential_evidence_gaps"] = [
                "The evidence board cannot resolve the staffing conflict."
            ]
            payload["cited_memo"] = (
                "Critical conflicting evidence prevents a defensible final verdict."
            )
        if self.verdict == "conditional_bid":
            payload["recommended_actions"] = [
                "Confirm ISO certificate validity before final bid approval."
            ]
            payload["potential_blockers"] = [
                _supported_claim("ISO certificate expiry remains unconfirmed.")
            ]
        if self.verdict == "bid":
            payload["cited_memo"] = (
                "The Judge overrides the no_bid majority because company evidence "
                "covers the material tender requirement."
            )
        return payload


class ScenarioRound1Model:
    def __init__(
        self,
        *,
        votes: dict[AgentRole, str],
        formal_compliance_blocker: bool = False,
        potential_compliance_blocker: bool = False,
    ) -> None:
        self.votes = votes
        self.formal_compliance_blocker = formal_compliance_blocker
        self.potential_compliance_blocker = potential_compliance_blocker

    def draft_motion(self, request: Any) -> dict[str, Any]:
        formal_blockers = []
        potential_blockers = []
        if request.agent_role is AgentRole.COMPLIANCE_OFFICER:
            if self.formal_compliance_blocker:
                formal_blockers = [
                    _supported_claim(
                        "The tender requires a valid ISO certificate before submission."
                    )
                ]
            if self.potential_compliance_blocker:
                potential_blockers = [
                    _supported_claim("ISO certificate expiry remains unconfirmed.")
                ]

        return {
            "agent_role": request.agent_role.value,
            "vote": self.votes[request.agent_role],
            "confidence": 0.78,
            "top_findings": [
                _supported_claim(
                    "The tender requirement and company profile evidence are available."
                )
            ],
            "role_specific_risks": [
                _supported_claim(
                    f"{request.agent_role.value} sees execution evidence risk."
                )
            ],
            "formal_blockers": formal_blockers,
            "potential_blockers": potential_blockers,
            "assumptions": ["The evidence board is complete for this mocked run."],
            "missing_info": ["Named consultant availability."],
            "recommended_actions": ["Confirm named staff before submission."],
        }


class ScenarioRound2Model:
    def draft_rebuttal(self, request: Any) -> dict[str, Any]:
        if request.agent_role is AgentRole.RED_TEAM:
            target_roles = [AgentRole.WIN_STRATEGIST, AgentRole.DELIVERY_CFO]
            target_role = AgentRole.WIN_STRATEGIST
        else:
            target_roles = [AgentRole.RED_TEAM]
            target_role = AgentRole.RED_TEAM

        return {
            "agent_role": request.agent_role.value,
            "target_roles": [role.value for role in target_roles],
            "targeted_disagreements": [
                {
                    "target_role": target_role.value,
                    "disputed_claim": request.motions[target_role].summary,
                    "rebuttal": "The vote disagreement turns on cited evidence.",
                    "evidence_refs": [_tender_ref()],
                }
            ],
            "unsupported_claims": [],
            "blocker_challenges": [],
            "revised_stance": "conditional_bid",
            "evidence_refs": [_tender_ref()],
            "missing_info": ["Staffing confidence remains incomplete."],
            "recommended_actions": ["Resolve the staffing gap before bid approval."],
        }


class RecordingDecisionQuery:
    def __init__(self, client: RecordingDecisionClient, table_name: str) -> None:
        self.client = client
        self.table_name = table_name
        self.insert_payload: dict[str, Any] | None = None

    def insert(self, payload: dict[str, Any]) -> RecordingDecisionQuery:
        self.insert_payload = payload
        return self

    def execute(self) -> Any:
        if self.insert_payload is not None:
            self.client.inserts.setdefault(self.table_name, []).append(
                self.insert_payload
            )
            data = [{**self.insert_payload, "id": "1"}]
            return type("Response", (), {"data": data})()
        return type("Response", (), {"data": []})()


class RecordingDecisionClient:
    def __init__(self) -> None:
        self.inserts: dict[str, list[dict[str, Any]]] = {}

    def table(self, table_name: str) -> RecordingDecisionQuery:
        return RecordingDecisionQuery(self, table_name)


def _ready_state() -> BidRunState:
    return BidRunState(
        run_id=RUN_ID,
        company_id=COMPANY_ID,
        tender_id=TENDER_ID,
        document_ids=[DOCUMENT_ID],
        run_context={
            "tenant_key": "demo",
            "private_context": "must not reach Judge",
            "document_parse_statuses": {str(DOCUMENT_ID): "parsed"},
        },
        chunks=[
            DocumentChunkState(
                chunk_id=CHUNK_ID,
                document_id=DOCUMENT_ID,
                chunk_index=0,
                page_start=1,
                page_end=1,
                text="The supplier shall provide ISO 27001 certification.",
            )
        ],
        evidence_board=[
            EvidenceItemState(
                evidence_id=TENDER_EVIDENCE_ID,
                evidence_key="TENDER-SHALL-001",
                source_type=EvidenceSourceType.TENDER_DOCUMENT,
                excerpt="The supplier shall provide ISO 27001 certification.",
                normalized_meaning="ISO 27001 certification is mandatory.",
                category="shall_requirement",
                confidence=0.94,
                source_metadata={"source_label": "Tender page 1"},
                document_id=DOCUMENT_ID,
                chunk_id=CHUNK_ID,
                page_start=1,
                page_end=1,
            ),
            EvidenceItemState(
                evidence_id=COMPANY_EVIDENCE_ID,
                evidence_key="COMPANY-CERT-001",
                source_type=EvidenceSourceType.COMPANY_PROFILE,
                excerpt="The company maintains ISO 27001 certification.",
                normalized_meaning="The company profile cites ISO 27001.",
                category="certification",
                confidence=0.91,
                source_metadata={"source_label": "Company profile"},
                company_id=COMPANY_ID,
                field_path="certifications.iso_27001",
            ),
        ],
    )


def _run_judge_scenario(
    *,
    judge_verdict: str,
    votes: dict[AgentRole, str],
    formal_compliance_blocker: bool = False,
    potential_compliance_blocker: bool = False,
) -> tuple[Any, RecordingJudgeModel, RecordingDecisionClient]:
    judge = RecordingJudgeModel(judge_verdict)
    client = RecordingDecisionClient()
    handlers = replace(
        default_graph_node_handlers(),
        round_1_specialist=build_round_1_specialist_handler(
            ScenarioRound1Model(
                votes=votes,
                formal_compliance_blocker=formal_compliance_blocker,
                potential_compliance_blocker=potential_compliance_blocker,
            )
        ),
        round_2_rebuttal=build_round_2_rebuttal_handler(ScenarioRound2Model()),
        judge=build_judge_handler(judge),
        persist_decision=build_decision_persistence_handler(client),
    )

    return run_bidded_graph_shell(_ready_state(), handlers=handlers), judge, client


def test_judge_gates_formal_compliance_blockers_to_no_bid_and_persists() -> None:
    result, judge, client = _run_judge_scenario(
        judge_verdict="bid",
        formal_compliance_blocker=True,
        votes={
            AgentRole.COMPLIANCE_OFFICER: "no_bid",
            AgentRole.WIN_STRATEGIST: "bid",
            AgentRole.DELIVERY_CFO: "bid",
            AgentRole.RED_TEAM: "bid",
        },
    )

    assert result.state.status is AgentRunStatus.SUCCEEDED
    assert result.state.final_decision is not None
    assert result.state.final_decision.verdict is Verdict.NO_BID
    assert result.state.final_decision.compliance_blockers == [
        "The tender requires a valid ISO certificate before submission."
    ]
    assert judge.requests[0].formal_compliance_blockers[0].claim == (
        "The tender requires a valid ISO certificate before submission."
    )
    assert "run_context" not in JudgeDecisionRequest.model_fields
    assert "private_context" not in JudgeDecisionRequest.model_fields

    judge_rows = [
        output
        for output in result.state.agent_outputs
        if output.agent_role == AgentRole.JUDGE.value
    ]
    assert len(judge_rows) == 1
    judge_payload = judge_rows[0].payload
    assert judge_rows[0].round_name == "final_decision"
    assert judge_rows[0].output_type == "decision"
    assert judge_payload["verdict"] == "no_bid"
    assert judge_payload["compliance_blockers"][0]["evidence_refs"]
    assert judge_payload["compliance_matrix"]
    assert judge_payload["risk_register"]
    assert judge_payload["evidence_ids"] == [
        str(TENDER_EVIDENCE_ID),
        str(COMPANY_EVIDENCE_ID),
    ]

    persisted = client.inserts["bid_decisions"][0]
    assert persisted["agent_run_id"] == str(RUN_ID)
    assert persisted["verdict"] == "no_bid"
    assert persisted["confidence"] == 0.82
    assert persisted["evidence_ids"] == [
        str(TENDER_EVIDENCE_ID),
        str(COMPANY_EVIDENCE_ID),
    ]
    assert persisted["final_decision"]["verdict"] == "no_bid"
    assert {
        "agent_role": "judge",
        "round_name": "final_decision",
        "output_type": "decision",
    } in persisted["metadata"]["source_agent_outputs"]


def test_judge_may_override_majority_without_hard_blocker() -> None:
    result, _, _ = _run_judge_scenario(
        judge_verdict="bid",
        votes={
            AgentRole.COMPLIANCE_OFFICER: "no_bid",
            AgentRole.WIN_STRATEGIST: "bid",
            AgentRole.DELIVERY_CFO: "no_bid",
            AgentRole.RED_TEAM: "no_bid",
        },
    )

    assert result.state.status is AgentRunStatus.SUCCEEDED
    assert result.state.final_decision is not None
    assert result.state.final_decision.verdict is Verdict.BID
    assert result.state.final_decision.vote_summary == {
        "bid": 1,
        "no_bid": 3,
        "conditional_bid": 0,
    }
    assert "overrides the no_bid majority" in result.state.final_decision.cited_memo
    assert result.state.final_decision.compliance_blockers == []


def test_potential_blocker_does_not_auto_gate_conditional_bid() -> None:
    result, _, client = _run_judge_scenario(
        judge_verdict="conditional_bid",
        potential_compliance_blocker=True,
        votes={
            AgentRole.COMPLIANCE_OFFICER: "conditional_bid",
            AgentRole.WIN_STRATEGIST: "conditional_bid",
            AgentRole.DELIVERY_CFO: "bid",
            AgentRole.RED_TEAM: "conditional_bid",
        },
    )

    assert result.state.status is AgentRunStatus.SUCCEEDED
    assert result.state.final_decision is not None
    assert result.state.final_decision.verdict is Verdict.CONDITIONAL_BID
    assert result.state.final_decision.compliance_blockers == []
    assert result.state.final_decision.potential_blockers == [
        "ISO certificate expiry remains unconfirmed."
    ]
    assert result.state.final_decision.recommended_actions == [
        "Confirm ISO certificate validity before final bid approval."
    ]
    assert client.inserts["bid_decisions"][0]["verdict"] == "conditional_bid"


@pytest.mark.parametrize(
    ("judge_verdict", "expected_status"),
    [
        ("bid", AgentRunStatus.SUCCEEDED),
        ("conditional_bid", AgentRunStatus.SUCCEEDED),
        ("needs_human_review", AgentRunStatus.NEEDS_HUMAN_REVIEW),
    ],
)
def test_judge_supports_mocked_final_verdict_scenarios(
    judge_verdict: str,
    expected_status: AgentRunStatus,
) -> None:
    result, _, client = _run_judge_scenario(
        judge_verdict=judge_verdict,
        votes={
            AgentRole.COMPLIANCE_OFFICER: "conditional_bid",
            AgentRole.WIN_STRATEGIST: "bid",
            AgentRole.DELIVERY_CFO: "conditional_bid",
            AgentRole.RED_TEAM: "no_bid",
        },
    )

    assert result.state.status is expected_status
    assert result.state.final_decision is not None
    assert result.state.final_decision.verdict is Verdict(judge_verdict)
    assert result.state.final_decision.disagreement_summary
    assert result.state.final_decision.compliance_matrix
    assert result.state.final_decision.evidence_ids == [
        TENDER_EVIDENCE_ID,
        COMPANY_EVIDENCE_ID,
    ]
    assert client.inserts["bid_decisions"][0]["verdict"] == judge_verdict
    if judge_verdict == "needs_human_review":
        assert result.visited_nodes[-3:] == (
            GraphRouteNode.PERSIST_DECISION,
            GraphRouteNode.NEEDS_HUMAN_REVIEW,
            GraphRouteNode.END,
        )
        assert result.state.final_decision.missing_info == [
            "Conflicting staffing and compliance evidence needs review."
        ]


def _judge_payload(*, verdict: str, vote_summary: dict[str, int]) -> dict[str, Any]:
    return {
        "verdict": verdict,
        "confidence": 0.82,
        "vote_summary": vote_summary,
        "disagreement_summary": (
            "The Judge compares the specialist majority with cited tender and "
            "company evidence."
        ),
        "compliance_matrix": [
            {
                "requirement": "ISO 27001 certificate",
                "status": "met",
                "assessment": "Tender and company evidence both cite ISO 27001.",
                "evidence_refs": [_tender_ref(), _company_ref()],
            }
        ],
        "compliance_blockers": [],
        "potential_blockers": [],
        "risk_register": [
            {
                "risk": "Submission could fail if certificate evidence is stale.",
                "severity": "medium",
                "mitigation": "Confirm certificate validity before final approval.",
                "evidence_refs": [_tender_ref()],
            }
        ],
        "missing_info": [],
        "potential_evidence_gaps": [],
        "recommended_actions": ["Keep the evidence package with the bid file."],
        "cited_memo": "The cited evidence supports this final Judge verdict.",
        "evidence_ids": [str(TENDER_EVIDENCE_ID), str(COMPANY_EVIDENCE_ID)],
        "evidence_refs": [_tender_ref(), _company_ref()],
        "validation_errors": [],
    }


def _supported_claim(claim: str) -> dict[str, Any]:
    return {"claim": claim, "evidence_refs": [_tender_ref()]}


def _tender_ref() -> dict[str, str]:
    return {
        "evidence_key": "TENDER-SHALL-001",
        "source_type": "tender_document",
        "evidence_id": str(TENDER_EVIDENCE_ID),
    }


def _company_ref() -> dict[str, str]:
    return {
        "evidence_key": "COMPANY-CERT-001",
        "source_type": "company_profile",
        "evidence_id": str(COMPANY_EVIDENCE_ID),
    }
