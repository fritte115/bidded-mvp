from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import UUID

import pytest

from bidded.agents import AgentRole, VoteSummary
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
from bidded.orchestration.judge import (
    JudgeDecisionRequest,
    validate_judge_decision_output,
)
from bidded.requirements import RequirementType

RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
COMPANY_ID = UUID("22222222-2222-4222-8222-222222222222")
TENDER_ID = UUID("33333333-3333-4333-8333-333333333333")
DOCUMENT_ID = UUID("44444444-4444-4444-8444-444444444444")
CHUNK_ID = UUID("55555555-5555-4555-8555-555555555555")
TENDER_EVIDENCE_ID = UUID("66666666-6666-4666-8666-666666666666")
COMPANY_EVIDENCE_ID = UUID("77777777-7777-4777-8777-777777777777")
EXCLUSION_EVIDENCE_ID = UUID("78787878-7878-4787-8787-787878787878")
FINANCIAL_EVIDENCE_ID = UUID("88888888-8888-4888-8888-888888888888")
QUALITY_EVIDENCE_ID = UUID("99999999-9999-4999-8999-999999999999")
SUBMISSION_EVIDENCE_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


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
                _supported_claim(
                    "ISO certificate expiry remains unconfirmed.",
                    requirement_type=RequirementType.QUALITY_MANAGEMENT,
                )
            ]
            payload["missing_info"] = [
                "Current financial standing proof is missing.",
                "SOSFS/quality management proof is missing.",
            ]
            payload["missing_info_details"] = [
                {
                    "text": "Current financial standing proof is missing.",
                    "requirement_type": "financial_standing",
                    "evidence_refs": [_financial_ref()],
                },
                {
                    "text": "SOSFS/quality management proof is missing.",
                    "requirement_type": "quality_management",
                    "evidence_refs": [_quality_ref()],
                },
            ]
            payload["recommended_action_details"] = [
                {
                    "text": "Prepare a signed data processing agreement attachment.",
                    "requirement_type": "submission_document",
                    "evidence_refs": [_submission_ref()],
                }
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
                        "A confirmed bankruptcy exclusion ground blocks submission.",
                        requirement_type=RequirementType.EXCLUSION_GROUND,
                        evidence_refs=[_exclusion_ref()],
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
            "confidence": 0.64,
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
                requirement_type=RequirementType.QUALIFICATION_REQUIREMENT,
                confidence=0.94,
                source_metadata={
                    "source_label": "Tender page 1",
                    "regulatory_glossary_ids": ["quality_management_sosfs"],
                    "regulatory_glossary": [
                        {
                            "entry_id": "quality_management_sosfs",
                            "requirement_type": "quality_management",
                            "display_label": "Quality management / SOSFS",
                            "suggested_proof_action": (
                                "Prepare quality management certificates."
                            ),
                            "blocker_hint": (
                                "Missing mandatory quality-system proof can block "
                                "qualification."
                            ),
                        }
                    ],
                },
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
            EvidenceItemState(
                evidence_id=EXCLUSION_EVIDENCE_ID,
                evidence_key="TENDER-EXCLUSION-001",
                source_type=EvidenceSourceType.TENDER_DOCUMENT,
                excerpt="A bankrupt supplier is subject to mandatory exclusion.",
                normalized_meaning="Confirmed bankruptcy is an exclusion ground.",
                category="exclusion_ground",
                requirement_type=RequirementType.EXCLUSION_GROUND,
                confidence=0.93,
                source_metadata={
                    "source_label": "Tender page 2",
                    "regulatory_glossary_ids": ["exclusion_grounds"],
                    "regulatory_glossary": [
                        {
                            "entry_id": "exclusion_grounds",
                            "requirement_type": "exclusion_ground",
                            "display_label": "Exclusion grounds",
                            "suggested_proof_action": (
                                "Confirm no exclusion ground applies."
                            ),
                            "blocker_hint": (
                                "Confirmed exclusion grounds can block bid submission."
                            ),
                        }
                    ],
                },
                document_id=DOCUMENT_ID,
                chunk_id=CHUNK_ID,
                page_start=2,
                page_end=2,
            ),
            EvidenceItemState(
                evidence_id=FINANCIAL_EVIDENCE_ID,
                evidence_key="TENDER-FINANCIAL-001",
                source_type=EvidenceSourceType.TENDER_DOCUMENT,
                excerpt="Supplier must submit a current credit report.",
                normalized_meaning="Financial standing proof is required.",
                category="qualification_criterion",
                requirement_type=RequirementType.FINANCIAL_STANDING,
                confidence=0.9,
                source_metadata={
                    "source_label": "Tender page 3",
                    "regulatory_glossary_ids": ["financial_standing"],
                    "regulatory_glossary": [
                        {
                            "entry_id": "financial_standing",
                            "requirement_type": "financial_standing",
                            "display_label": "Financial standing",
                            "suggested_proof_action": (
                                "Prepare current credit report."
                            ),
                            "blocker_hint": (
                                "Missing financial standing proof can block "
                                "qualification."
                            ),
                        }
                    ],
                },
                document_id=DOCUMENT_ID,
                chunk_id=CHUNK_ID,
                page_start=3,
                page_end=3,
            ),
            EvidenceItemState(
                evidence_id=QUALITY_EVIDENCE_ID,
                evidence_key="TENDER-QUALITY-001",
                source_type=EvidenceSourceType.TENDER_DOCUMENT,
                excerpt="Supplier must maintain SOSFS 2011:9 quality management.",
                normalized_meaning="Quality management proof is required.",
                category="qualification_criterion",
                requirement_type=RequirementType.QUALITY_MANAGEMENT,
                confidence=0.9,
                source_metadata={
                    "source_label": "Tender page 4",
                    "regulatory_glossary_ids": ["quality_management_sosfs"],
                    "regulatory_glossary": [
                        {
                            "entry_id": "quality_management_sosfs",
                            "requirement_type": "quality_management",
                            "display_label": "Quality management / SOSFS",
                            "suggested_proof_action": (
                                "Prepare quality management certificates."
                            ),
                            "blocker_hint": (
                                "Missing mandatory quality-system proof can block "
                                "qualification."
                            ),
                        }
                    ],
                },
                document_id=DOCUMENT_ID,
                chunk_id=CHUNK_ID,
                page_start=4,
                page_end=4,
            ),
            EvidenceItemState(
                evidence_id=SUBMISSION_EVIDENCE_ID,
                evidence_key="TENDER-SUBMISSION-001",
                source_type=EvidenceSourceType.TENDER_DOCUMENT,
                excerpt="Submission must include a signed data processing agreement.",
                normalized_meaning="A signed DPA attachment is required.",
                category="required_submission_document",
                requirement_type=RequirementType.SUBMISSION_DOCUMENT,
                confidence=0.9,
                source_metadata={
                    "source_label": "Tender page 5",
                    "regulatory_glossary_ids": ["submission_documents"],
                    "regulatory_glossary": [
                        {
                            "entry_id": "submission_documents",
                            "requirement_type": "submission_document",
                            "display_label": "Submission documents",
                            "suggested_proof_action": (
                                "Create a submission checklist."
                            ),
                            "blocker_hint": (
                                "Missing required submission documents can make "
                                "the bid invalid."
                            ),
                        }
                    ],
                },
                document_id=DOCUMENT_ID,
                chunk_id=CHUNK_ID,
                page_start=5,
                page_end=5,
            ),
        ],
    )


def _run_judge_scenario(
    *,
    judge_verdict: str,
    votes: dict[AgentRole, str],
    formal_compliance_blocker: bool = False,
    potential_compliance_blocker: bool = False,
    state: BidRunState | None = None,
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

    result = run_bidded_graph_shell(state or _ready_state(), handlers=handlers)
    return result, judge, client


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
        "A confirmed bankruptcy exclusion ground blocks submission."
    ]
    assert judge.requests[0].formal_compliance_blockers[0].claim == (
        "A confirmed bankruptcy exclusion ground blocks submission."
    )
    assert judge.requests[0].requirement_context[0].model_dump(mode="json") == {
        "evidence_key": "TENDER-SHALL-001",
        "source_type": "tender_document",
        "evidence_id": str(TENDER_EVIDENCE_ID),
        "source_label": "Tender page 1",
        "requirement_type": "qualification_requirement",
        "regulatory_glossary_ids": ["quality_management_sosfs"],
        "regulatory_glossary": [
            {
                "entry_id": "quality_management_sosfs",
                "requirement_type": "quality_management",
                "display_label": "Quality management / SOSFS",
                "suggested_proof_action": ("Prepare quality management certificates."),
                "blocker_hint": (
                    "Missing mandatory quality-system proof can block qualification."
                ),
            }
        ],
    }
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
        str(EXCLUSION_EVIDENCE_ID),
    ]

    persisted = client.inserts["bid_decisions"][0]
    assert persisted["agent_run_id"] == str(RUN_ID)
    assert persisted["verdict"] == "no_bid"
    assert persisted["confidence"] == 0.82
    assert persisted["evidence_ids"] == [
        str(TENDER_EVIDENCE_ID),
        str(COMPANY_EVIDENCE_ID),
        str(EXCLUSION_EVIDENCE_ID),
    ]
    assert persisted["final_decision"]["verdict"] == "no_bid"
    assert {
        "agent_role": "judge",
        "round_name": "final_decision",
        "output_type": "decision",
    } in persisted["metadata"]["source_agent_outputs"]
    audit = persisted["metadata"]["decision_evidence_audit"]
    assert audit["schema_version"] == "2026-04-23.decision-evidence-audit.v1"
    assert audit["gate_verdict"] in {"confirmed", "flagged"}
    assert audit["graph"]["claims"]
    assert audit["graph"]["evidence"]
    assert audit["graph"]["edges"]


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
    persisted_decision = client.inserts["bid_decisions"][0]
    assert persisted_decision["verdict"] == "conditional_bid"
    final_payload = persisted_decision["final_decision"]
    assert final_payload["compliance_matrix"][0]["requirement_type"] == (
        "qualification_requirement"
    )
    assert final_payload["potential_blockers"][0]["requirement_type"] == (
        "quality_management"
    )
    assert final_payload["risk_register"][0]["requirement_type"] == (
        "quality_management"
    )
    assert final_payload["missing_info_details"] == [
        {
            "text": "Current financial standing proof is missing.",
            "requirement_type": "financial_standing",
            "evidence_refs": [_financial_ref()],
        },
        {
            "text": "SOSFS/quality management proof is missing.",
            "requirement_type": "quality_management",
            "evidence_refs": [_quality_ref()],
        },
    ]
    assert final_payload["recommended_action_details"] == [
        {
            "text": "Prepare a signed data processing agreement attachment.",
            "requirement_type": "submission_document",
            "evidence_refs": [_submission_ref()],
        }
    ]


def test_judge_coerces_missing_cited_memo_and_evidence_ids() -> None:
    raw = _judge_payload(
        verdict="bid",
        vote_summary={"bid": 1, "no_bid": 0, "conditional_bid": 0},
    )
    raw.pop("cited_memo")
    raw.pop("evidence_ids")
    raw["rationale"] = "Judge rationale supplied under a Claude-friendly alias."

    output = validate_judge_decision_output(
        raw,
        evidence_board=_ready_state().evidence_board,
        expected_vote_summary=VoteSummary.model_validate(raw["vote_summary"]),
    )

    assert output.cited_memo == (
        "Judge rationale supplied under a Claude-friendly alias."
    )
    assert output.evidence_ids == [
        TENDER_EVIDENCE_ID,
        COMPANY_EVIDENCE_ID,
    ]


def test_judge_coerces_conditional_bid_actions_from_details() -> None:
    raw = _judge_payload(
        verdict="conditional_bid",
        vote_summary={"bid": 0, "no_bid": 0, "conditional_bid": 1},
    )
    raw["recommended_actions"] = []
    raw["recommended_action_details"] = [
        {
            "text": "Confirm ISO certificate validity before bid approval.",
            "requirement_type": "quality_management",
            "evidence_refs": [_quality_ref()],
        }
    ]

    output = validate_judge_decision_output(
        raw,
        evidence_board=_ready_state().evidence_board,
        expected_vote_summary=VoteSummary.model_validate(raw["vote_summary"]),
    )

    assert output.recommended_actions == [
        "Confirm ISO certificate validity before bid approval."
    ]


def test_judge_coerces_conditional_bid_actions_from_missing_info() -> None:
    raw = _judge_payload(
        verdict="conditional_bid",
        vote_summary={"bid": 0, "no_bid": 0, "conditional_bid": 1},
    )
    raw["recommended_actions"] = []
    raw["recommended_action_details"] = []
    raw["missing_info"] = ["Named consultant availability is not confirmed."]
    raw["potential_evidence_gaps"] = ["Current certificate expiry evidence is absent."]

    output = validate_judge_decision_output(
        raw,
        evidence_board=_ready_state().evidence_board,
        expected_vote_summary=VoteSummary.model_validate(raw["vote_summary"]),
    )

    assert output.recommended_actions == [
        "Resolve missing information: Named consultant availability is not confirmed.",
        "Resolve evidence gap: Current certificate expiry evidence is absent.",
    ]


def test_judge_request_includes_recall_warnings_without_hard_gate() -> None:
    base_state = _ready_state()
    state = base_state.model_copy(
        update={
            "chunks": [
                DocumentChunkState(
                    chunk_id=UUID("55555555-5555-4555-8555-555555555556"),
                    document_id=DOCUMENT_ID,
                    chunk_index=1,
                    page_start=3,
                    page_end=3,
                    text="Bidders must submit a current credit report.",
                    metadata={"source_label": "Tender page 3"},
                )
            ],
            "evidence_board": [
                evidence
                for evidence in base_state.evidence_board
                if evidence.requirement_type is not RequirementType.FINANCIAL_STANDING
            ],
        }
    )

    result, judge, _ = _run_judge_scenario(
        judge_verdict="bid",
        votes={
            AgentRole.COMPLIANCE_OFFICER: "bid",
            AgentRole.WIN_STRATEGIST: "bid",
            AgentRole.DELIVERY_CFO: "bid",
            AgentRole.RED_TEAM: "bid",
        },
        state=state,
    )

    assert result.state.status is AgentRunStatus.SUCCEEDED
    assert result.state.final_decision is not None
    assert result.state.final_decision.verdict is Verdict.BID
    assert result.state.final_decision.compliance_blockers == []
    recalled_types = [
        warning.requirement_type
        for warning in judge.requests[0].evidence_recall_warnings
    ]
    assert recalled_types == [RequirementType.FINANCIAL_STANDING]
    assert judge.requests[0].evidence_recall_warnings[0].severity == "warning"
    assert judge.requests[0].formal_compliance_blockers == ()


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
                "requirement_type": "qualification_requirement",
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
                "requirement_type": "quality_management",
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


def _supported_claim(
    claim: str,
    *,
    requirement_type: RequirementType | None = None,
    evidence_refs: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "claim": claim,
        "requirement_type": (
            requirement_type.value if requirement_type is not None else None
        ),
        "evidence_refs": evidence_refs or [_tender_ref()],
    }


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


def _exclusion_ref() -> dict[str, str]:
    return {
        "evidence_key": "TENDER-EXCLUSION-001",
        "source_type": "tender_document",
        "evidence_id": str(EXCLUSION_EVIDENCE_ID),
    }


def _financial_ref() -> dict[str, str]:
    return {
        "evidence_key": "TENDER-FINANCIAL-001",
        "source_type": "tender_document",
        "evidence_id": str(FINANCIAL_EVIDENCE_ID),
    }


def _quality_ref() -> dict[str, str]:
    return {
        "evidence_key": "TENDER-QUALITY-001",
        "source_type": "tender_document",
        "evidence_id": str(QUALITY_EVIDENCE_ID),
    }


def _submission_ref() -> dict[str, str]:
    return {
        "evidence_key": "TENDER-SUBMISSION-001",
        "source_type": "tender_document",
        "evidence_id": str(SUBMISSION_EVIDENCE_ID),
    }
