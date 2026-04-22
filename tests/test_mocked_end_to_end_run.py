from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest

from bidded.agents import AgentRole
from bidded.db.seed_demo_company import (
    build_demo_company_payload,
    seed_demo_company,
)
from bidded.documents.tender_registration import register_demo_tender_pdf
from bidded.evidence.company_profile import upsert_company_profile_evidence
from bidded.evidence.tender_document import (
    build_tender_evidence_candidates,
    upsert_tender_evidence_items,
)
from bidded.orchestration import (
    AgentRunStatus,
    BidRunState,
    EvidenceItemState,
    EvidenceSourceType,
    GraphNodeHandlers,
    GraphRouteNode,
    GraphRunResult,
    Verdict,
    build_judge_handler,
    build_round_1_specialist_handler,
    build_round_2_rebuttal_handler,
    create_pending_run_context,
    default_graph_node_handlers,
    run_bidded_graph_shell,
    run_worker_once,
)
from bidded.orchestration.evidence_scout import (
    EvidenceScoutRequest,
    build_evidence_scout_handler,
)
from bidded.orchestration.judge import JudgeDecisionRequest
from bidded.orchestration.specialist_motions import Round1SpecialistRequest
from bidded.orchestration.specialist_rebuttals import Round2RebuttalRequest
from bidded.retrieval import retrieve_document_chunks

_UUID_NAMESPACE = uuid5(NAMESPACE_URL, "https://bidded.test/mock-e2e")


@dataclass(frozen=True)
class EndToEndScenario:
    formal_compliance_blocker: bool
    potential_missing_company_evidence: bool
    judge_requested_verdict: str
    expected_verdict: Verdict


@pytest.mark.parametrize(
    "scenario",
    [
        pytest.param(
            EndToEndScenario(
                formal_compliance_blocker=True,
                potential_missing_company_evidence=False,
                judge_requested_verdict="bid",
                expected_verdict=Verdict.NO_BID,
            ),
            id="formal-blocker-gates-no-bid",
        ),
        pytest.param(
            EndToEndScenario(
                formal_compliance_blocker=False,
                potential_missing_company_evidence=True,
                judge_requested_verdict="conditional_bid",
                expected_verdict=Verdict.CONDITIONAL_BID,
            ),
            id="potential-company-gap-stays-conditional",
        ),
    ],
)
def test_mocked_end_to_end_run_persists_evidence_locked_swarm(
    tmp_path: Path,
    scenario: EndToEndScenario,
) -> None:
    client = InMemorySupabaseClient()
    pending_run = _prepare_pending_evidence_locked_run(client, tmp_path)

    round_1_model = MockedRound1Model(scenario)
    judge_model = MockedJudgeModel(scenario)
    handlers = _mocked_graph_handlers(
        round_1_model=round_1_model,
        round_2_model=MockedRound2Model(),
        judge_model=judge_model,
    )
    graph_results: list[GraphRunResult] = []

    def graph_runner(state: BidRunState) -> GraphRunResult:
        graph_result = run_bidded_graph_shell(state, handlers=handlers)
        graph_results.append(graph_result)
        return graph_result

    result = run_worker_once(
        client,
        run_id=pending_run.run_id,
        graph_runner=graph_runner,
        now_factory=lambda: datetime(2026, 4, 18, 18, 30, tzinfo=UTC),
    )

    assert result.terminal_status is AgentRunStatus.SUCCEEDED
    assert result.decision_verdict is scenario.expected_verdict
    assert result.agent_output_count == 10
    assert graph_results
    terminal_state = graph_results[0].state
    assert terminal_state.status is AgentRunStatus.SUCCEEDED
    assert terminal_state.retry_counts[GraphRouteNode.ROUND_1_COMPLIANCE.value] == 1
    # Attempt 1 emitted a finding with empty evidence_refs. The pre-validate
    # coercer drops claims with zero resolvable refs, so the payload now
    # fails the "at least one evidence-backed finding" check on
    # ``top_findings`` instead of the per-claim ``min_length=1`` check on
    # ``evidence_refs``. Both indicate the same underlying problem
    # (an unverifiable claim) and both trigger a retry.
    assert any(
        error.field_path == "top_findings"
        and "Unverified subcontractor" not in error.message
        for error in terminal_state.validation_errors
    )

    agent_outputs = client.rows["agent_outputs"]
    assert len(agent_outputs) == 10
    assert {output["agent_run_id"] for output in agent_outputs} == {
        str(pending_run.run_id)
    }
    assert _round_roles(agent_outputs, "evidence") == {"evidence_scout"}
    assert _round_roles(agent_outputs, "round_1_motion") == {
        "compliance_officer",
        "delivery_cfo",
        "red_team",
        "win_strategist",
    }
    assert _round_roles(agent_outputs, "round_2_rebuttal") == {
        "compliance_officer",
        "delivery_cfo",
        "red_team",
        "win_strategist",
    }
    assert _round_roles(agent_outputs, "final_decision") == {"judge"}

    compliance_payload = _agent_payload(
        agent_outputs,
        agent_role="compliance_officer",
        round_name="round_1_motion",
    )
    assert round_1_model.attempts[AgentRole.COMPLIANCE_OFFICER] == 2
    assert "unverified subcontractor capacity" in " ".join(
        compliance_payload["assumptions"]
    )
    assert "Named security-cleared lead CV" in " ".join(
        compliance_payload["missing_info"]
    )
    assert "subcontractor surge capacity" in " ".join(
        compliance_payload["potential_evidence_gaps"]
    )
    assert compliance_payload["validation_errors"][0]["code"] == "unsupported_claim"
    assert all(
        "subcontractor" not in finding["claim"].lower()
        for finding in compliance_payload["top_findings"]
    )

    bid_decisions = client.rows["bid_decisions"]
    assert len(bid_decisions) == 1
    persisted_decision = bid_decisions[0]
    assert persisted_decision["agent_run_id"] == str(pending_run.run_id)
    assert persisted_decision["verdict"] == scenario.expected_verdict.value
    assert persisted_decision["final_decision"]["verdict"] == (
        scenario.expected_verdict.value
    )
    assert len(persisted_decision["metadata"]["source_agent_outputs"]) == 10
    assert all(
        source["agent_role"] != "evidence_scout" or source["round_name"] == "evidence"
        for source in persisted_decision["metadata"]["source_agent_outputs"]
    )

    if scenario.formal_compliance_blocker:
        assert judge_model.requested_verdicts == ["bid"]
        assert persisted_decision["verdict"] == "no_bid"
        assert "bankruptcy exclusion ground" in " ".join(
            _claim_texts(persisted_decision["final_decision"]["compliance_blockers"])
        )
        assert (
            "Formal compliance blockers require no_bid"
            in (persisted_decision["final_decision"]["cited_memo"])
        )
    else:
        assert persisted_decision["verdict"] == "conditional_bid"
        assert persisted_decision["final_decision"]["compliance_blockers"] == []
        assert "named security-cleared lead" in " ".join(
            _claim_texts(persisted_decision["final_decision"]["potential_blockers"])
        )
        assert "Named security-cleared lead CV" in " ".join(
            persisted_decision["final_decision"]["missing_info"]
        )


def _mocked_graph_handlers(
    *,
    round_1_model: MockedRound1Model,
    round_2_model: MockedRound2Model,
    judge_model: MockedJudgeModel,
) -> GraphNodeHandlers:
    return replace(
        default_graph_node_handlers(),
        evidence_scout=build_evidence_scout_handler(MockedEvidenceScoutModel()),
        round_1_specialist=build_round_1_specialist_handler(round_1_model),
        round_2_rebuttal=build_round_2_rebuttal_handler(round_2_model),
        judge=build_judge_handler(judge_model),
    )


def _prepare_pending_evidence_locked_run(
    client: InMemorySupabaseClient,
    tmp_path: Path,
) -> Any:
    seed_result = seed_demo_company(client)
    assert seed_result.rows_returned == 1

    fixture_pdf = tmp_path / "fixture-tender.pdf"
    fixture_pdf.write_bytes(b"%PDF-1.4\n% deterministic text-pdf fixture\n")
    registration = register_demo_tender_pdf(
        client,
        pdf_path=fixture_pdf,
        bucket_name="tender-fixtures",
        tender_title="Mocked E2E Procurement",
        issuing_authority="City of Example",
        procurement_reference="E2E-2026",
        procurement_metadata={"procedure": "open"},
    )

    document = _single_row(client.rows["documents"], registration.document_id)
    document["parse_status"] = "parsed"
    document["metadata"]["parser"] = {
        "status": "parsed",
        "mode": "fixture_chunks",
    }

    chunk = {
        "id": str(_stable_uuid("document_chunks", registration.document_id, "0")),
        "tenant_key": "demo",
        "document_id": registration.document_id,
        "page_start": 1,
        "page_end": 1,
        "chunk_index": 0,
        "text": (
            "Supplier must hold active ISO 27001 certification at submission. "
            "Supplier must name a security-cleared delivery lead in the submission. "
            "Submission deadline is 2026-05-05 at 12:00 CET. "
            "Award evaluation weights quality at 60 percent and price at 40 percent. "
            "The contract includes liability penalties for material delivery delay. "
            "Submission must include a signed data processing agreement. "
            "Supplier must not be bankrupt or subject to insolvency exclusion grounds."
        ),
        "metadata": {"source_label": "Fixture Tender page 1"},
    }
    client.rows["document_chunks"].append(chunk)

    retrieved_chunks = retrieve_document_chunks(
        client,
        query=(
            "ISO 27001 security-cleared lead deadline award quality price "
            "liability signed data processing agreement bankrupt insolvency"
        ),
        document_id=registration.document_id,
        top_k=3,
    )
    tender_candidates = build_tender_evidence_candidates(retrieved_chunks)
    tender_result = upsert_tender_evidence_items(client, tender_candidates)
    assert tender_result.evidence_count >= 5

    company_profile = build_demo_company_payload()
    company_result = upsert_company_profile_evidence(
        client,
        company_id=UUID(registration.company_id),
        company_profile=company_profile,
    )
    assert company_result.evidence_count > 10

    return create_pending_run_context(
        client,
        tender_id=registration.tender_id,
        company_id=registration.company_id,
        document_ids=[registration.document_id],
        created_via="mocked_e2e_test",
    )


class MockedEvidenceScoutModel:
    def extract(self, request: EvidenceScoutRequest) -> dict[str, Any]:
        tender_iso = _ref_by(
            request.evidence_board,
            source_type=EvidenceSourceType.TENDER_DOCUMENT,
            excerpt_contains="ISO 27001",
        )
        deadline = _ref_by(
            request.evidence_board,
            source_type=EvidenceSourceType.TENDER_DOCUMENT,
            excerpt_contains="deadline",
        )
        submission_document = _ref_by(
            request.evidence_board,
            source_type=EvidenceSourceType.TENDER_DOCUMENT,
            excerpt_contains="signed data processing agreement",
        )

        return {
            "agent_role": "evidence_scout",
            "findings": [
                {
                    "category": "shall_requirement",
                    "claim": "The tender requires active ISO 27001 certification.",
                    "evidence_refs": [tender_iso],
                },
                {
                    "category": "deadline",
                    "claim": "The tender has a fixed submission deadline.",
                    "evidence_refs": [deadline],
                },
                {
                    "category": "required_submission_document",
                    "claim": (
                        "The tender requires a signed data processing agreement."
                    ),
                    "evidence_refs": [submission_document],
                },
            ],
            "missing_info": ["Named consultant CVs are not in the tender evidence."],
            "potential_blockers": [],
            "validation_errors": [],
        }


class MockedRound1Model:
    def __init__(self, scenario: EndToEndScenario) -> None:
        self.scenario = scenario
        self.attempts: dict[AgentRole, int] = {}

    def draft_motion(self, request: Round1SpecialistRequest) -> dict[str, Any]:
        attempt = self.attempts.get(request.agent_role, 0) + 1
        self.attempts[request.agent_role] = attempt
        if request.agent_role is AgentRole.COMPLIANCE_OFFICER and attempt == 1:
            invalid_payload = self._valid_payload(request)
            invalid_payload["top_findings"] = [
                {
                    "claim": (
                        "Unverified subcontractor capacity can add 40 architects."
                    ),
                    "evidence_refs": [],
                }
            ]
            return invalid_payload

        return self._valid_payload(request)

    def _valid_payload(self, request: Round1SpecialistRequest) -> dict[str, Any]:
        tender_iso = _ref_by(
            request.evidence_board,
            source_type=EvidenceSourceType.TENDER_DOCUMENT,
            excerpt_contains="ISO 27001",
        )
        company_iso = _ref_by(
            request.evidence_board,
            source_type=EvidenceSourceType.COMPANY_PROFILE,
            field_path="certifications[2]",
        )
        named_lead = _ref_by(
            request.evidence_board,
            source_type=EvidenceSourceType.TENDER_DOCUMENT,
            excerpt_contains="security-cleared delivery lead",
        )
        company_capacity = _ref_by(
            request.evidence_board,
            source_type=EvidenceSourceType.COMPANY_PROFILE,
            field_path=("capabilities.delivery_capacity.security_cleared_consultants"),
        )
        exclusion_ground = _ref_by(
            request.evidence_board,
            source_type=EvidenceSourceType.TENDER_DOCUMENT,
            excerpt_contains="bankrupt",
        )

        formal_blockers: list[dict[str, Any]] = []
        potential_blockers: list[dict[str, Any]] = []
        if request.agent_role is AgentRole.COMPLIANCE_OFFICER:
            if self.scenario.formal_compliance_blocker:
                formal_blockers.append(
                    {
                        "claim": (
                            "A confirmed bankruptcy exclusion ground blocks submission."
                        ),
                        "evidence_refs": [exclusion_ground],
                    }
                )
            if self.scenario.potential_missing_company_evidence:
                potential_blockers.append(
                    {
                        "claim": (
                            "The tender asks for a named security-cleared lead, "
                            "while company evidence only gives aggregate capacity."
                        ),
                        "evidence_refs": [named_lead, company_capacity],
                    }
                )

        return {
            "agent_role": request.agent_role.value,
            "vote": _round_1_vote(request.agent_role, self.scenario),
            "confidence": 0.78,
            "top_findings": [
                {
                    "claim": (
                        "The tender requires ISO 27001 and the seeded company "
                        "profile includes active ISO 27001 evidence."
                    ),
                    "evidence_refs": [tender_iso, company_iso],
                }
            ],
            "role_specific_risks": [
                {
                    "claim": (
                        f"{request.agent_role.value} treats named staffing proof "
                        "as the main execution risk."
                    ),
                    "evidence_refs": [named_lead],
                }
            ],
            "formal_blockers": formal_blockers,
            "potential_blockers": potential_blockers,
            "assumptions": [
                (
                    "The unverified subcontractor capacity claim is treated as an "
                    "assumption, not a supported finding."
                )
            ],
            "missing_info": [
                "Named security-cleared lead CV is missing from company evidence."
            ],
            "potential_evidence_gaps": [
                "No evidence item supports subcontractor surge capacity."
            ],
            "recommended_actions": [
                "Collect named CV evidence before final bid approval."
            ],
            "validation_errors": [
                {
                    "code": "unsupported_claim",
                    "message": (
                        "Unverified subcontractor capacity was excluded from "
                        "material findings."
                    ),
                    "field_path": "top_findings[unverified_subcontractor]",
                    "retryable": False,
                    "evidence_refs": [],
                }
            ],
        }


class MockedRound2Model:
    def draft_rebuttal(self, request: Round2RebuttalRequest) -> dict[str, Any]:
        if request.agent_role is AgentRole.RED_TEAM:
            target_roles = [AgentRole.WIN_STRATEGIST, AgentRole.DELIVERY_CFO]
            target_role = AgentRole.WIN_STRATEGIST
        else:
            target_roles = [AgentRole.RED_TEAM]
            target_role = AgentRole.RED_TEAM

        named_lead = _ref_by(
            request.evidence_board,
            source_type=EvidenceSourceType.TENDER_DOCUMENT,
            excerpt_contains="security-cleared delivery lead",
        )
        company_capacity = _ref_by(
            request.evidence_board,
            source_type=EvidenceSourceType.COMPANY_PROFILE,
            field_path=("capabilities.delivery_capacity.security_cleared_consultants"),
        )

        return {
            "agent_role": request.agent_role.value,
            "target_roles": [role.value for role in target_roles],
            "targeted_disagreements": [
                {
                    "target_role": target_role.value,
                    "disputed_claim": request.motions[target_role].summary,
                    "rebuttal": (
                        "The disagreement should turn on cited staffing and "
                        "certification evidence, not unsupported capacity claims."
                    ),
                    "evidence_refs": [named_lead, company_capacity],
                }
            ],
            "unsupported_claims": [
                {
                    "target_role": target_role.value,
                    "claim": "Unverified subcontractor capacity can add 40 architects.",
                    "reason": "No evidence_board item supports this claim.",
                }
            ],
            "blocker_challenges": [],
            "revised_stance": "conditional_bid",
            "confidence": 0.66,
            "evidence_refs": [named_lead, company_capacity],
            "missing_info": ["Named security-cleared lead CV remains missing."],
            "potential_evidence_gaps": [
                "Subcontractor surge capacity has no resolved evidence item."
            ],
            "recommended_actions": [
                "Keep the unsupported claim out of the Judge rationale."
            ],
            "validation_errors": [
                {
                    "code": "unsupported_claim",
                    "message": (
                        "Unverified subcontractor capacity was isolated as unsupported."
                    ),
                    "field_path": "unsupported_claims[0]",
                    "retryable": False,
                    "evidence_refs": [],
                }
            ],
        }


class MockedJudgeModel:
    def __init__(self, scenario: EndToEndScenario) -> None:
        self.scenario = scenario
        self.requests: list[JudgeDecisionRequest] = []
        self.requested_verdicts: list[str] = []

    def decide(self, request: JudgeDecisionRequest) -> dict[str, Any]:
        self.requests.append(request)
        self.requested_verdicts.append(self.scenario.judge_requested_verdict)
        tender_iso = _ref_by(
            request.evidence_board,
            source_type=EvidenceSourceType.TENDER_DOCUMENT,
            excerpt_contains="ISO 27001",
        )
        company_iso = _ref_by(
            request.evidence_board,
            source_type=EvidenceSourceType.COMPANY_PROFILE,
            field_path="certifications[2]",
        )
        named_lead = _ref_by(
            request.evidence_board,
            source_type=EvidenceSourceType.TENDER_DOCUMENT,
            excerpt_contains="security-cleared delivery lead",
        )
        company_capacity = _ref_by(
            request.evidence_board,
            source_type=EvidenceSourceType.COMPANY_PROFILE,
            field_path=("capabilities.delivery_capacity.security_cleared_consultants"),
        )
        potential_blockers = [
            claim.model_dump(mode="json") for claim in request.potential_blockers
        ]
        missing_info = []
        if self.scenario.potential_missing_company_evidence:
            missing_info.append(
                "Named security-cleared lead CV is missing from company evidence."
            )

        return {
            "agent_role": "judge",
            "verdict": self.scenario.judge_requested_verdict,
            "confidence": 0.84,
            "vote_summary": request.vote_summary.model_dump(mode="json"),
            "disagreement_summary": (
                "Specialists disagree mainly on staffing proof and compliance "
                "blocker severity."
            ),
            "compliance_matrix": [
                {
                    "requirement": "Active ISO 27001 certification",
                    "status": "met",
                    "assessment": ("Tender and company evidence both cite ISO 27001."),
                    "evidence_refs": [tender_iso, company_iso],
                },
                {
                    "requirement": "Named security-cleared delivery lead",
                    "status": (
                        "unknown"
                        if self.scenario.potential_missing_company_evidence
                        else "met"
                    ),
                    "assessment": (
                        "The tender asks for a named lead; company evidence "
                        "supports capacity but not a named CV."
                    ),
                    "evidence_refs": [named_lead, company_capacity],
                },
            ],
            "compliance_blockers": [],
            "potential_blockers": potential_blockers,
            "risk_register": [
                {
                    "risk": "Named staffing evidence may be incomplete.",
                    "severity": "medium",
                    "mitigation": "Confirm the named CV before submission.",
                    "evidence_refs": [named_lead],
                }
            ],
            "missing_info": missing_info,
            "potential_evidence_gaps": [
                "No evidence item supports the subcontractor surge claim."
            ],
            "recommended_actions": [
                "Confirm named staffing and remove unsupported subcontractor claims."
            ],
            "cited_memo": (
                "The Judge relies only on cited tender and company evidence; "
                "unsupported subcontractor claims stay out of the rationale."
            ),
            "evidence_ids": [
                tender_iso["evidence_id"],
                company_iso["evidence_id"],
                named_lead["evidence_id"],
                company_capacity["evidence_id"],
            ],
            "evidence_refs": [
                tender_iso,
                company_iso,
                named_lead,
                company_capacity,
            ],
            "validation_errors": [
                {
                    "code": "unsupported_claim",
                    "message": "Subcontractor surge claim excluded from the verdict.",
                    "field_path": "cited_memo",
                    "retryable": False,
                    "evidence_refs": [],
                }
            ],
        }


class InMemorySupabaseClient:
    def __init__(self) -> None:
        self.rows: dict[str, list[dict[str, Any]]] = {
            "companies": [],
            "tenders": [],
            "documents": [],
            "document_chunks": [],
            "evidence_items": [],
            "agent_runs": [],
            "agent_outputs": [],
            "bid_decisions": [],
        }
        self.inserts: dict[str, list[Any]] = {}
        self.upserts: dict[str, list[Any]] = {}
        self.updates: dict[str, list[tuple[dict[str, Any], list[tuple[str, str]]]]] = {}
        self.storage = InMemoryStorage()

    def table(self, table_name: str) -> InMemorySupabaseQuery:
        self.rows.setdefault(table_name, [])
        return InMemorySupabaseQuery(self, table_name)

    def assign_id(
        self,
        table_name: str,
        row: dict[str, Any],
        *,
        index: int = 0,
    ) -> dict[str, Any]:
        if row.get("id"):
            return row
        row["id"] = str(_stable_uuid(table_name, _row_identity(row, index=index)))
        return row


class InMemorySupabaseQuery:
    def __init__(self, client: InMemorySupabaseClient, table_name: str) -> None:
        self.client = client
        self.table_name = table_name
        self.filters: list[tuple[str, str]] = []
        self.order_column: str | None = None
        self.descending = False
        self.row_limit: int | None = None
        self.insert_payload: Any | None = None
        self.upsert_payload: Any | None = None
        self.update_payload: dict[str, Any] | None = None
        self.on_conflict: str | None = None

    def select(self, _columns: str) -> InMemorySupabaseQuery:
        return self

    def eq(self, column: str, value: object) -> InMemorySupabaseQuery:
        self.filters.append((column, str(value)))
        return self

    def order(self, column: str, *, desc: bool = False) -> InMemorySupabaseQuery:
        self.order_column = column
        self.descending = desc
        return self

    def limit(self, row_limit: int) -> InMemorySupabaseQuery:
        self.row_limit = row_limit
        return self

    def insert(self, payload: Any) -> InMemorySupabaseQuery:
        self.insert_payload = payload
        return self

    def upsert(
        self,
        payload: Any,
        *,
        on_conflict: str | None = None,
    ) -> InMemorySupabaseQuery:
        self.upsert_payload = payload
        self.on_conflict = on_conflict
        return self

    def update(self, payload: dict[str, Any]) -> InMemorySupabaseQuery:
        self.update_payload = payload
        return self

    def execute(self) -> object:
        if self.update_payload is not None:
            rows = self._filtered_rows()
            for row in rows:
                row.update(self.update_payload)
            self.client.updates.setdefault(self.table_name, []).append(
                (dict(self.update_payload), list(self.filters))
            )
            return _response(rows)

        if self.insert_payload is not None:
            payload_rows = _payload_rows(self.insert_payload)
            inserted_rows = []
            for index, payload in enumerate(payload_rows):
                row = self.client.assign_id(
                    self.table_name,
                    dict(payload),
                    index=len(self.client.rows[self.table_name]) + index,
                )
                self.client.rows[self.table_name].append(row)
                inserted_rows.append(row)
            self.client.inserts.setdefault(self.table_name, []).append(
                self.insert_payload
            )
            return _response(inserted_rows)

        if self.upsert_payload is not None:
            payload_rows = _payload_rows(self.upsert_payload)
            upserted_rows = [
                self._upsert_one(dict(payload), index=index)
                for index, payload in enumerate(payload_rows)
            ]
            self.client.upserts.setdefault(self.table_name, []).append(
                (self.upsert_payload, self.on_conflict)
            )
            return _response(upserted_rows)

        return _response(self._filtered_rows())

    def _filtered_rows(self) -> list[dict[str, Any]]:
        rows = [
            row
            for row in self.client.rows.get(self.table_name, [])
            if all(str(row.get(column)) == value for column, value in self.filters)
        ]
        if self.order_column is not None:
            rows = sorted(
                rows,
                key=lambda row: str(row.get(self.order_column) or ""),
                reverse=self.descending,
            )
        if self.row_limit is not None:
            rows = rows[: self.row_limit]
        return rows

    def _upsert_one(self, payload: dict[str, Any], *, index: int) -> dict[str, Any]:
        conflict_columns = _conflict_columns(self.on_conflict)
        existing = None
        if conflict_columns:
            existing = next(
                (
                    row
                    for row in self.client.rows[self.table_name]
                    if all(
                        str(row.get(column)) == str(payload.get(column))
                        for column in conflict_columns
                    )
                ),
                None,
            )

        if existing is not None:
            row_id = existing.get("id")
            existing.update(payload)
            if row_id is not None:
                existing["id"] = row_id
            return existing

        row = self.client.assign_id(self.table_name, payload, index=index)
        self.client.rows[self.table_name].append(row)
        return row


class InMemoryStorage:
    def __init__(self) -> None:
        self.buckets: dict[str, InMemoryStorageBucket] = {}

    def from_(self, bucket_name: str) -> InMemoryStorageBucket:
        bucket = self.buckets.setdefault(bucket_name, InMemoryStorageBucket())
        return bucket


class InMemoryStorageBucket:
    def __init__(self) -> None:
        self.uploads: list[tuple[str, bytes, dict[str, str] | None]] = []

    def upload(
        self,
        path: str,
        file: bytes,
        *,
        file_options: dict[str, str] | None = None,
    ) -> object:
        self.uploads.append((path, file, file_options))
        return _response([{"path": path}])


def _round_1_vote(agent_role: AgentRole, scenario: EndToEndScenario) -> str:
    if agent_role is AgentRole.COMPLIANCE_OFFICER:
        return "no_bid" if scenario.formal_compliance_blocker else "conditional_bid"
    if agent_role is AgentRole.WIN_STRATEGIST:
        return "bid"
    if agent_role is AgentRole.DELIVERY_CFO:
        return "conditional_bid"
    return "no_bid"


def _round_roles(
    agent_outputs: list[dict[str, Any]],
    round_name: str,
) -> set[str]:
    return {
        output["agent_role"]
        for output in agent_outputs
        if output["round_name"] == round_name
    }


def _agent_payload(
    agent_outputs: list[dict[str, Any]],
    *,
    agent_role: str,
    round_name: str,
) -> dict[str, Any]:
    return next(
        output["validated_payload"]
        for output in agent_outputs
        if output["agent_role"] == agent_role and output["round_name"] == round_name
    )


def _claim_texts(claims: list[dict[str, Any]]) -> list[str]:
    return [str(claim["claim"]) for claim in claims]


def _ref_by(
    evidence_board: tuple[EvidenceItemState, ...],
    *,
    source_type: EvidenceSourceType,
    excerpt_contains: str | None = None,
    field_path: str | None = None,
) -> dict[str, str]:
    lowered_excerpt = excerpt_contains.lower() if excerpt_contains else None
    for item in evidence_board:
        if item.source_type is not source_type:
            continue
        if field_path is not None and item.field_path != field_path:
            continue
        if lowered_excerpt is not None and lowered_excerpt not in item.excerpt.lower():
            continue
        if item.evidence_id is None:
            raise AssertionError(f"Evidence item has no evidence_id: {item}")
        return {
            "evidence_key": item.evidence_key,
            "source_type": item.source_type.value,
            "evidence_id": str(item.evidence_id),
        }
    raise AssertionError(
        f"Missing evidence ref for {source_type.value} {excerpt_contains or field_path}"
    )


def _single_row(rows: list[dict[str, Any]], row_id: str | UUID) -> dict[str, Any]:
    return next(row for row in rows if str(row.get("id")) == str(row_id))


def _payload_rows(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, Mapping)]
    if isinstance(payload, Mapping):
        return [payload]
    raise TypeError("Supabase payload must be a mapping or list of mappings.")


def _conflict_columns(on_conflict: str | None) -> list[str]:
    if on_conflict is None:
        return []
    return [column.strip() for column in on_conflict.split(",") if column.strip()]


def _row_identity(row: Mapping[str, Any], *, index: int) -> str:
    for columns in (
        ("tenant_key", "name"),
        ("tenant_key", "title", "issuing_authority"),
        ("storage_path",),
        ("tenant_key", "evidence_key"),
        ("tenant_key", "agent_run_id", "agent_role", "round_name", "output_type"),
        ("agent_run_id", "verdict"),
        ("tenant_key", "company_id", "tender_id", "status"),
    ):
        if all(column in row for column in columns):
            return "|".join(str(row[column]) for column in columns) + f"|{index}"
    return "|".join(f"{key}={row[key]}" for key in sorted(row)) + f"|{index}"


def _stable_uuid(*parts: object) -> UUID:
    return uuid5(_UUID_NAMESPACE, "|".join(str(part) for part in parts))


def _response(data: Any) -> object:
    return type("Response", (), {"data": data})()
