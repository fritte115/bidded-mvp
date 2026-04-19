from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from bidded.agents.schemas import (
    AgentRole,
    BidVerdict,
    EvidenceReference,
    EvidenceScoutFinding,
    EvidenceScoutOutput,
    FinalVerdict,
    JudgeDecision,
    Round1Motion,
    Round2Rebuttal,
    ScoutCategory,
    SourceType,
    SupportedClaim,
    TargetedDisagreement,
    VoteSummary,
)
from bidded.db.seed_demo_company import (
    DEMO_COMPANY_NAME,
    seed_demo_company,
)
from bidded.orchestration.evidence_scout import validate_evidence_scout_output
from bidded.orchestration.judge import (
    judge_decision_result_from_agent_output,
    validate_judge_decision_output,
)
from bidded.orchestration.pending_run import DEMO_TENANT_KEY, build_pending_run_config
from bidded.orchestration.specialist_motions import (
    round_1_motion_result_from_agent_output,
    validate_round_1_motion_output,
)
from bidded.orchestration.specialist_rebuttals import (
    round_2_rebuttal_result_from_agent_output,
    validate_round_2_rebuttal_output,
)
from bidded.orchestration.state import (
    AgentOutputState,
    AgentRunStatus,
    EvidenceItemState,
    EvidenceRef,
    EvidenceSourceType,
    SpecialistMotionState,
    SpecialistRole,
)
from bidded.requirements import RequirementType

DEMO_STATES_FIXTURE_KEY = "replayable_demo_states"
DEMO_STATES_FIXTURE_VERSION = "2026-04-19.v1"
DEMO_STATES_SOURCE = "bidded_seed_demo_states"

_FIXTURE_NAMESPACE = uuid5(
    NAMESPACE_URL,
    "https://bidded.local/fixtures/replayable-demo-states/v1",
)
_FIXTURE_TENDER_TEXT = (
    "Supplier must hold active ISO 27001 certification at submission. "
    "Supplier must name a security-cleared delivery lead in the submission. "
    "Submission deadline is 2026-05-05 at 12:00 CET. "
    "Award evaluation weights quality at 60 percent and price at 40 percent. "
    "The contract includes liability penalties for material delivery delay. "
    "Submission must include a signed data processing agreement. "
    "Supplier must not be bankrupt or subject to insolvency exclusion grounds."
)


class DemoStatesSeedError(RuntimeError):
    """Raised when replayable demo fixtures cannot be safely seeded."""


class SupabaseDemoStateQuery(Protocol):
    def select(self, columns: str) -> SupabaseDemoStateQuery: ...

    def eq(self, column: str, value: object) -> SupabaseDemoStateQuery: ...

    def limit(self, row_limit: int) -> SupabaseDemoStateQuery: ...

    def insert(
        self,
        payload: dict[str, Any] | list[dict[str, Any]],
    ) -> SupabaseDemoStateQuery: ...

    def upsert(
        self,
        payload: dict[str, Any] | list[dict[str, Any]],
        *,
        on_conflict: str | None = None,
    ) -> SupabaseDemoStateQuery: ...

    def execute(self) -> Any: ...


class SupabaseDemoStateClient(Protocol):
    def table(self, table_name: str) -> SupabaseDemoStateQuery: ...


@dataclass(frozen=True)
class DemoStatesSeedResult:
    tenant_key: str
    company_id: str
    tender_id: str
    document_id: str
    run_ids_by_state: dict[str, str]
    evidence_items_seeded: int
    agent_outputs_seeded: int
    bid_decisions_seeded: int


def seed_demo_states(client: SupabaseDemoStateClient) -> DemoStatesSeedResult:
    """Seed replayable demo rows for pending and terminal run states."""

    seed_demo_company(client)
    company_row = _require_demo_company(client)
    company_id = _uuid_from_row(company_row, "companies.id")

    _upsert_owned_fixture_row(
        client,
        "tenders",
        _demo_tender_payload(),
    )
    _upsert_owned_fixture_row(
        client,
        "documents",
        _demo_document_payload(),
    )
    _upsert_owned_fixture_rows(
        client,
        "document_chunks",
        _demo_chunk_payloads(),
    )
    evidence_rows = _upsert_owned_fixture_rows(
        client,
        "evidence_items",
        _demo_evidence_payloads(company_id=company_id),
    )
    evidence_by_key = {str(row["evidence_key"]): dict(row) for row in evidence_rows}
    evidence_board = [_evidence_state_from_row(row) for row in evidence_rows]

    runs = _upsert_owned_fixture_rows(
        client,
        "agent_runs",
        _demo_run_payloads(company_id=company_id),
    )
    runs_by_state = {
        str(row["metadata"]["fixture"]["state"]): dict(row) for row in runs
    }

    output_rows: list[dict[str, Any]] = []
    decision_rows: list[dict[str, Any]] = []
    for state_name, verdict in [
        ("succeeded", FinalVerdict.CONDITIONAL_BID),
        ("needs_human_review", FinalVerdict.NEEDS_HUMAN_REVIEW),
    ]:
        run_id = _uuid_from_row(runs_by_state[state_name], "agent_runs.id")
        agent_outputs, judge_payload = _validated_agent_outputs(
            state_name=state_name,
            run_id=run_id,
            evidence_by_key=evidence_by_key,
            evidence_board=evidence_board,
            verdict=verdict,
        )
        output_rows.extend(
            _insert_missing_fixture_row(
                client,
                "agent_outputs",
                _agent_output_payload(
                    state_name=state_name,
                    run_id=run_id,
                    output=agent_output,
                ),
                identity_filters={
                    "agent_run_id": str(run_id),
                    "agent_role": agent_output.agent_role,
                    "round_name": agent_output.round_name,
                    "output_type": agent_output.output_type,
                },
            )
            for agent_output in agent_outputs
        )
        decision_rows.append(
            _insert_missing_fixture_row(
                client,
                "bid_decisions",
                _bid_decision_payload(
                    state_name=state_name,
                    run_id=run_id,
                    judge_payload=judge_payload,
                    agent_outputs=agent_outputs,
                ),
                identity_filters={"agent_run_id": str(run_id)},
            )
        )

    return DemoStatesSeedResult(
        tenant_key=DEMO_TENANT_KEY,
        company_id=str(company_id),
        tender_id=str(_fixture_uuid("tender")),
        document_id=str(_fixture_uuid("document")),
        run_ids_by_state={
            state: str(row["id"])
            for state, row in sorted(runs_by_state.items(), key=lambda item: item[0])
        },
        evidence_items_seeded=len(evidence_rows),
        agent_outputs_seeded=len(output_rows),
        bid_decisions_seeded=len(decision_rows),
    )


def _require_demo_company(client: SupabaseDemoStateClient) -> Mapping[str, Any]:
    row = _select_one(
        client,
        "companies",
        {
            "tenant_key": DEMO_TENANT_KEY,
            "name": DEMO_COMPANY_NAME,
        },
    )
    if row is None:
        raise DemoStatesSeedError("Demo company seed did not return a readable row.")
    return row


def _demo_tender_payload() -> dict[str, Any]:
    return {
        "id": str(_fixture_uuid("tender")),
        "tenant_key": DEMO_TENANT_KEY,
        "title": "Bidded Replayable Demo Procurement",
        "issuing_authority": "Example Municipality",
        "procurement_reference": "BIDDED-DEMO-REPLAY-2026",
        "procurement_context": {
            "jurisdiction": "SE",
            "market": "Swedish public procurement",
            "procedure_family": "public_procurement",
        },
        "language_policy": {
            "input_language": "en",
            "output_language": "en",
        },
        "metadata": _fixture_metadata("tenders"),
    }


def _demo_document_payload() -> dict[str, Any]:
    return {
        "id": str(_fixture_uuid("document")),
        "tenant_key": DEMO_TENANT_KEY,
        "tender_id": str(_fixture_uuid("tender")),
        "storage_path": "demo/fixtures/replayable-demo-states/tender.pdf",
        "checksum_sha256": sha256(_FIXTURE_TENDER_TEXT.encode("utf-8")).hexdigest(),
        "content_type": "application/pdf",
        "document_role": EvidenceSourceType.TENDER_DOCUMENT.value,
        "parse_status": "parsed",
        "original_filename": "replayable-demo-tender.pdf",
        "metadata": _fixture_metadata(
            "documents",
            details={
                "parser": {
                    "status": "parsed",
                    "mode": "deterministic_fixture_text",
                }
            },
        ),
    }


def _demo_chunk_payloads() -> list[dict[str, Any]]:
    return [
        {
            "id": str(_fixture_uuid("document_chunks", 0)),
            "tenant_key": DEMO_TENANT_KEY,
            "document_id": str(_fixture_uuid("document")),
            "page_start": 1,
            "page_end": 1,
            "chunk_index": 0,
            "text": _FIXTURE_TENDER_TEXT,
            "metadata": _fixture_metadata(
                "document_chunks",
                details={"source_label": "Replayable demo tender page 1"},
            ),
        }
    ]


def _demo_evidence_payloads(*, company_id: UUID) -> list[dict[str, Any]]:
    document_id = _fixture_uuid("document")
    chunk_id = _fixture_uuid("document_chunks", 0)
    tender_source = "Replayable demo tender page 1"
    company_source = "seeded company profile"
    tender_items = [
        _tender_evidence_payload(
            evidence_id=_fixture_uuid("evidence", "tender-iso-27001"),
            evidence_key="DEMO-REPLAY-TENDER-ISO-27001",
            excerpt="Supplier must hold active ISO 27001 certification at submission.",
            normalized_meaning=(
                "The tender requires active ISO 27001 certification at submission."
            ),
            category="mandatory_requirement",
            requirement_type=RequirementType.QUALITY_MANAGEMENT,
            source_label=tender_source,
            document_id=document_id,
            chunk_id=chunk_id,
        ),
        _tender_evidence_payload(
            evidence_id=_fixture_uuid("evidence", "tender-named-lead"),
            evidence_key="DEMO-REPLAY-TENDER-NAMED-LEAD",
            excerpt=(
                "Supplier must name a security-cleared delivery lead in the "
                "submission."
            ),
            normalized_meaning=(
                "The tender requires a named security-cleared delivery lead."
            ),
            category="qualification_criterion",
            requirement_type=RequirementType.QUALIFICATION_REQUIREMENT,
            source_label=tender_source,
            document_id=document_id,
            chunk_id=chunk_id,
        ),
        _tender_evidence_payload(
            evidence_id=_fixture_uuid("evidence", "tender-deadline"),
            evidence_key="DEMO-REPLAY-TENDER-DEADLINE",
            excerpt="Submission deadline is 2026-05-05 at 12:00 CET.",
            normalized_meaning=(
                "The tender response deadline is 2026-05-05 at 12:00 CET."
            ),
            category="submission_deadline",
            requirement_type=None,
            source_label=tender_source,
            document_id=document_id,
            chunk_id=chunk_id,
        ),
        _tender_evidence_payload(
            evidence_id=_fixture_uuid("evidence", "tender-evaluation"),
            evidence_key="DEMO-REPLAY-TENDER-EVALUATION",
            excerpt=(
                "Award evaluation weights quality at 60 percent and price at "
                "40 percent."
            ),
            normalized_meaning=(
                "The award model weights quality at 60 percent and price at "
                "40 percent."
            ),
            category="award_criterion",
            requirement_type=None,
            source_label=tender_source,
            document_id=document_id,
            chunk_id=chunk_id,
        ),
        _tender_evidence_payload(
            evidence_id=_fixture_uuid("evidence", "tender-liability"),
            evidence_key="DEMO-REPLAY-TENDER-LIABILITY",
            excerpt=(
                "The contract includes liability penalties for material delivery "
                "delay."
            ),
            normalized_meaning=(
                "The contract contains liability penalties for material delivery "
                "delay."
            ),
            category="contract_risk",
            requirement_type=RequirementType.CONTRACT_OBLIGATION,
            source_label=tender_source,
            document_id=document_id,
            chunk_id=chunk_id,
        ),
        _tender_evidence_payload(
            evidence_id=_fixture_uuid("evidence", "tender-dpa"),
            evidence_key="DEMO-REPLAY-TENDER-DPA",
            excerpt="Submission must include a signed data processing agreement.",
            normalized_meaning=(
                "The tender requires a signed data processing agreement in the "
                "submission."
            ),
            category="required_submission_document",
            requirement_type=RequirementType.SUBMISSION_DOCUMENT,
            source_label=tender_source,
            document_id=document_id,
            chunk_id=chunk_id,
        ),
        _tender_evidence_payload(
            evidence_id=_fixture_uuid("evidence", "tender-exclusion"),
            evidence_key="DEMO-REPLAY-TENDER-EXCLUSION",
            excerpt=(
                "Supplier must not be bankrupt or subject to insolvency exclusion "
                "grounds."
            ),
            normalized_meaning=(
                "The tender contains bankruptcy and insolvency exclusion grounds."
            ),
            category="exclusion_ground",
            requirement_type=RequirementType.EXCLUSION_GROUND,
            source_label=tender_source,
            document_id=document_id,
            chunk_id=chunk_id,
        ),
    ]
    company_items = [
        _company_evidence_payload(
            evidence_id=_fixture_uuid("evidence", "company-iso-27001"),
            evidence_key="DEMO-REPLAY-COMPANY-ISO-27001",
            excerpt=(
                "ISO 27001: information security management for managed delivery; "
                "status active."
            ),
            normalized_meaning=(
                "The company has active ISO 27001 certification for managed "
                "delivery."
            ),
            category="certification",
            source_label=company_source,
            company_id=company_id,
            field_path="certifications[2]",
        ),
        _company_evidence_payload(
            evidence_id=_fixture_uuid("evidence", "company-capacity"),
            evidence_key="DEMO-REPLAY-COMPANY-CAPACITY",
            excerpt="260 consultants available within 90 days.",
            normalized_meaning=(
                "The company has 260 consultants available within 90 days."
            ),
            category="capacity",
            source_label=company_source,
            company_id=company_id,
            field_path="capabilities.delivery_capacity.available_consultants_90_days",
        ),
        _company_evidence_payload(
            evidence_id=_fixture_uuid("evidence", "company-reference"),
            evidence_key="DEMO-REPLAY-COMPANY-REFERENCE",
            excerpt=(
                "National agency reference (public_sector, 2023-2025, 120m-180m): "
                "Modernized citizen-facing case management services using Azure, "
                "API integration, accessibility testing, and secure DevOps."
            ),
            normalized_meaning=(
                "The company has a public-sector national agency modernization "
                "reference from 2023-2025."
            ),
            category="reference",
            source_label=company_source,
            company_id=company_id,
            field_path="reference_projects[0]",
        ),
        _company_evidence_payload(
            evidence_id=_fixture_uuid("evidence", "company-rate-card"),
            evidence_key="DEMO-REPLAY-COMPANY-RATE-CARD",
            excerpt=(
                "Rate card: senior_consultant: 1350 SEK/hour; "
                "delivery_manager: 1450 SEK/hour."
            ),
            normalized_meaning=(
                "The company has seeded hourly SEK rates for senior consultants "
                "and delivery managers."
            ),
            category="economics",
            source_label=company_source,
            company_id=company_id,
            field_path="financial_assumptions.rate_card_sek_per_hour",
        ),
    ]
    return [*tender_items, *company_items]


def _tender_evidence_payload(
    *,
    evidence_id: UUID,
    evidence_key: str,
    excerpt: str,
    normalized_meaning: str,
    category: str,
    requirement_type: RequirementType | None,
    source_label: str,
    document_id: UUID,
    chunk_id: UUID,
) -> dict[str, Any]:
    return {
        "id": str(evidence_id),
        "tenant_key": DEMO_TENANT_KEY,
        "evidence_key": evidence_key,
        "source_type": EvidenceSourceType.TENDER_DOCUMENT.value,
        "excerpt": excerpt,
        "normalized_meaning": normalized_meaning,
        "category": category,
        "requirement_type": (
            requirement_type.value if requirement_type is not None else None
        ),
        "confidence": 0.92,
        "source_metadata": {"source_label": source_label},
        "document_id": str(document_id),
        "chunk_id": str(chunk_id),
        "page_start": 1,
        "page_end": 1,
        "metadata": _fixture_metadata("evidence_items"),
    }


def _company_evidence_payload(
    *,
    evidence_id: UUID,
    evidence_key: str,
    excerpt: str,
    normalized_meaning: str,
    category: str,
    source_label: str,
    company_id: UUID,
    field_path: str,
) -> dict[str, Any]:
    return {
        "id": str(evidence_id),
        "tenant_key": DEMO_TENANT_KEY,
        "evidence_key": evidence_key,
        "source_type": EvidenceSourceType.COMPANY_PROFILE.value,
        "excerpt": excerpt,
        "normalized_meaning": normalized_meaning,
        "category": category,
        "requirement_type": None,
        "confidence": 0.9,
        "source_metadata": {"source_label": source_label},
        "company_id": str(company_id),
        "field_path": field_path,
        "metadata": _fixture_metadata("evidence_items"),
    }


def _demo_run_payloads(*, company_id: UUID) -> list[dict[str, Any]]:
    document_id = _fixture_uuid("document")
    run_config = build_pending_run_config(document_ids=[document_id])
    base = {
        "tenant_key": DEMO_TENANT_KEY,
        "tender_id": str(_fixture_uuid("tender")),
        "company_id": str(company_id),
        "run_config": {
            **run_config,
            "demo_fixture": {
                "seed_key": DEMO_STATES_FIXTURE_KEY,
                "version": DEMO_STATES_FIXTURE_VERSION,
            },
        },
    }
    return [
        {
            **base,
            "id": str(_fixture_uuid("agent_runs", "pending")),
            "created_at": "2026-04-19T08:00:00+00:00",
            "status": AgentRunStatus.PENDING.value,
            "error_details": None,
            "started_at": None,
            "completed_at": None,
            "metadata": _fixture_metadata("agent_runs", state="pending"),
        },
        {
            **base,
            "id": str(_fixture_uuid("agent_runs", "succeeded")),
            "created_at": "2026-04-19T08:05:00+00:00",
            "status": AgentRunStatus.SUCCEEDED.value,
            "error_details": None,
            "started_at": "2026-04-19T08:05:30+00:00",
            "completed_at": "2026-04-19T08:07:00+00:00",
            "metadata": _fixture_metadata("agent_runs", state="succeeded"),
        },
        {
            **base,
            "id": str(_fixture_uuid("agent_runs", "failed")),
            "created_at": "2026-04-19T08:10:00+00:00",
            "status": AgentRunStatus.FAILED.value,
            "error_details": {
                "code": "demo_fixture_failed_run",
                "message": "Replayable fixture run failed before agent execution.",
                "source": DEMO_STATES_SOURCE,
                "retryable": False,
            },
            "started_at": "2026-04-19T08:10:30+00:00",
            "completed_at": "2026-04-19T08:11:00+00:00",
            "metadata": _fixture_metadata("agent_runs", state="failed"),
        },
        {
            **base,
            "id": str(_fixture_uuid("agent_runs", "needs_human_review")),
            "created_at": "2026-04-19T08:15:00+00:00",
            "status": AgentRunStatus.NEEDS_HUMAN_REVIEW.value,
            "error_details": None,
            "started_at": "2026-04-19T08:15:30+00:00",
            "completed_at": "2026-04-19T08:17:00+00:00",
            "metadata": _fixture_metadata(
                "agent_runs",
                state="needs_human_review",
            ),
        },
    ]


def _validated_agent_outputs(
    *,
    state_name: str,
    run_id: UUID,
    evidence_by_key: Mapping[str, Mapping[str, Any]],
    evidence_board: Sequence[EvidenceItemState],
    verdict: FinalVerdict,
) -> tuple[list[AgentOutputState], dict[str, Any]]:
    refs = _evidence_refs(evidence_by_key)
    scout = _build_scout_output(refs)
    validate_evidence_scout_output(scout, evidence_board=evidence_board)
    scout_output = AgentOutputState(
        agent_role=AgentRole.EVIDENCE_SCOUT.value,
        round_name="evidence",
        output_type="scout_output",
        payload=scout.model_dump(mode="json"),
        evidence_refs=_state_refs(
            finding_ref
            for finding in scout.findings
            for finding_ref in finding.evidence_refs
        ),
    )

    motions: dict[SpecialistRole, SpecialistMotionState] = {}
    outputs = [scout_output]
    for role, motion in _build_round_1_motions(refs):
        validated = validate_round_1_motion_output(
            motion,
            evidence_board=evidence_board,
            expected_role=role,
        )
        result = round_1_motion_result_from_agent_output(validated)
        motions[role] = result.motion
        outputs.append(result.agent_output)

    rebuttals = {}
    for role, rebuttal in _build_round_2_rebuttals(refs):
        validated = validate_round_2_rebuttal_output(
            rebuttal,
            evidence_board=evidence_board,
            motions=motions,
            expected_role=role,
        )
        result = round_2_rebuttal_result_from_agent_output(validated)
        rebuttals[role] = result.rebuttal
        outputs.append(result.agent_output)

    vote_summary = VoteSummary(bid=1, no_bid=1, conditional_bid=2)
    judge = _build_judge_decision(
        refs,
        verdict=verdict,
        vote_summary=vote_summary,
    )
    validated_judge = validate_judge_decision_output(
        judge,
        evidence_board=evidence_board,
        expected_vote_summary=vote_summary,
    )
    judge_result = judge_decision_result_from_agent_output(validated_judge)
    outputs.append(judge_result.agent_output)

    return outputs, validated_judge.model_dump(mode="json")


def _build_scout_output(refs: Mapping[str, EvidenceReference]) -> EvidenceScoutOutput:
    return EvidenceScoutOutput(
        findings=[
            EvidenceScoutFinding(
                category=ScoutCategory.SHALL_REQUIREMENT,
                requirement_type=RequirementType.QUALITY_MANAGEMENT,
                claim="The tender requires active ISO 27001 certification.",
                evidence_refs=[refs["tender_iso"]],
            ),
            EvidenceScoutFinding(
                category=ScoutCategory.QUALIFICATION_CRITERION,
                requirement_type=RequirementType.QUALIFICATION_REQUIREMENT,
                claim="The tender requires a named security-cleared delivery lead.",
                evidence_refs=[refs["named_lead"]],
            ),
            EvidenceScoutFinding(
                category=ScoutCategory.DEADLINE,
                claim="The tender has a fixed submission deadline.",
                evidence_refs=[refs["deadline"]],
            ),
            EvidenceScoutFinding(
                category=ScoutCategory.EVALUATION_CRITERION,
                claim="The tender weights quality higher than price.",
                evidence_refs=[refs["evaluation"]],
            ),
            EvidenceScoutFinding(
                category=ScoutCategory.CONTRACT_RISK,
                requirement_type=RequirementType.CONTRACT_OBLIGATION,
                claim="The tender includes liability penalties for delivery delay.",
                evidence_refs=[refs["liability"]],
            ),
            EvidenceScoutFinding(
                category=ScoutCategory.REQUIRED_SUBMISSION_DOCUMENT,
                requirement_type=RequirementType.SUBMISSION_DOCUMENT,
                claim="The tender requires a signed data processing agreement.",
                evidence_refs=[refs["dpa"]],
            ),
        ],
        missing_info=["Named consultant CVs are not present in fixture evidence."],
        potential_blockers=[],
    )


def _build_round_1_motions(
    refs: Mapping[str, EvidenceReference],
) -> list[tuple[SpecialistRole, Round1Motion]]:
    return [
        (
            SpecialistRole.COMPLIANCE,
            Round1Motion(
                agent_role=AgentRole.COMPLIANCE_OFFICER,
                vote=BidVerdict.CONDITIONAL_BID,
                confidence=0.76,
                top_findings=[
                    _claim(
                        "ISO 27001 is required and the seeded company has "
                        "active ISO 27001.",
                        refs["tender_iso"],
                        refs["company_iso"],
                        requirement_type=RequirementType.QUALITY_MANAGEMENT,
                    )
                ],
                role_specific_risks=[
                    _claim(
                        "The named lead requirement still needs a named CV package.",
                        refs["named_lead"],
                        requirement_type=RequirementType.QUALIFICATION_REQUIREMENT,
                    )
                ],
                missing_info=["Named security-cleared delivery lead CV."],
                recommended_actions=[
                    "Attach named security-cleared delivery lead CV before submission."
                ],
            ),
        ),
        (
            SpecialistRole.WIN_STRATEGIST,
            Round1Motion(
                agent_role=AgentRole.WIN_STRATEGIST,
                vote=BidVerdict.BID,
                confidence=0.81,
                top_findings=[
                    _claim(
                        "The quality-weighted award model favors a strong "
                        "public-sector case study.",
                        refs["evaluation"],
                        refs["company_reference"],
                    )
                ],
                role_specific_risks=[
                    _claim(
                        "Price still matters at 40 percent of evaluation.",
                        refs["evaluation"],
                    )
                ],
                recommended_actions=[
                    "Lead with public-sector delivery proof and quality "
                    "differentiators."
                ],
            ),
        ),
        (
            SpecialistRole.DELIVERY_CFO,
            Round1Motion(
                agent_role=AgentRole.DELIVERY_CFO,
                vote=BidVerdict.CONDITIONAL_BID,
                confidence=0.7,
                top_findings=[
                    _claim(
                        "The company has enough near-term capacity for a "
                        "credible delivery plan.",
                        refs["company_capacity"],
                    )
                ],
                role_specific_risks=[
                    _claim(
                        "Delay penalties need a liability cap review before "
                        "final bid approval.",
                        refs["liability"],
                        requirement_type=RequirementType.CONTRACT_OBLIGATION,
                    )
                ],
                recommended_actions=[
                    "Review liability cap and delivery contingency before submission."
                ],
            ),
        ),
        (
            SpecialistRole.RED_TEAM,
            Round1Motion(
                agent_role=AgentRole.RED_TEAM,
                vote=BidVerdict.NO_BID,
                confidence=0.62,
                top_findings=[
                    _claim(
                        "The tender has a hard named-lead proof point that "
                        "the fixture lacks.",
                        refs["named_lead"],
                        requirement_type=RequirementType.QUALIFICATION_REQUIREMENT,
                    )
                ],
                role_specific_risks=[
                    _claim(
                        "The signed data processing agreement is mandatory "
                        "submission content.",
                        refs["dpa"],
                        requirement_type=RequirementType.SUBMISSION_DOCUMENT,
                    )
                ],
                missing_info=[
                    "Signed data processing agreement and named lead CV are not shown."
                ],
                recommended_actions=[
                    "Treat missing submission proof as a pre-bid checklist gate."
                ],
            ),
        ),
    ]


def _build_round_2_rebuttals(
    refs: Mapping[str, EvidenceReference],
) -> list[tuple[SpecialistRole, Round2Rebuttal]]:
    return [
        (
            SpecialistRole.COMPLIANCE,
            Round2Rebuttal(
                agent_role=AgentRole.COMPLIANCE_OFFICER,
                target_roles=[AgentRole.RED_TEAM],
                targeted_disagreements=[
                    TargetedDisagreement(
                        target_role=AgentRole.RED_TEAM,
                        disputed_claim="The fixture lacks all submission proof.",
                        rebuttal=(
                            "The DPA requirement is known and can be handled as a "
                            "submission action."
                        ),
                        evidence_refs=[refs["dpa"]],
                    )
                ],
                revised_stance=BidVerdict.CONDITIONAL_BID,
                evidence_refs=[refs["dpa"]],
            ),
        ),
        (
            SpecialistRole.WIN_STRATEGIST,
            Round2Rebuttal(
                agent_role=AgentRole.WIN_STRATEGIST,
                target_roles=[AgentRole.DELIVERY_CFO],
                targeted_disagreements=[
                    TargetedDisagreement(
                        target_role=AgentRole.DELIVERY_CFO,
                        disputed_claim="Liability risk should stop the pursuit.",
                        rebuttal=(
                            "The quality-weighted award model supports continued "
                            "pursuit if liability is clarified."
                        ),
                        evidence_refs=[refs["evaluation"], refs["liability"]],
                    )
                ],
                revised_stance=BidVerdict.BID,
                evidence_refs=[refs["evaluation"]],
            ),
        ),
        (
            SpecialistRole.DELIVERY_CFO,
            Round2Rebuttal(
                agent_role=AgentRole.DELIVERY_CFO,
                target_roles=[AgentRole.WIN_STRATEGIST],
                targeted_disagreements=[
                    TargetedDisagreement(
                        target_role=AgentRole.WIN_STRATEGIST,
                        disputed_claim=(
                            "Quality weighting alone makes the bid attractive."
                        ),
                        rebuttal=(
                            "Rate card and liability exposure still need commercial "
                            "review."
                        ),
                        evidence_refs=[refs["company_rate_card"], refs["liability"]],
                    )
                ],
                revised_stance=BidVerdict.CONDITIONAL_BID,
                evidence_refs=[refs["company_rate_card"]],
            ),
        ),
        (
            SpecialistRole.RED_TEAM,
            Round2Rebuttal(
                agent_role=AgentRole.RED_TEAM,
                target_roles=[
                    AgentRole.WIN_STRATEGIST,
                    AgentRole.COMPLIANCE_OFFICER,
                    AgentRole.DELIVERY_CFO,
                ],
                targeted_disagreements=[
                    TargetedDisagreement(
                        target_role=AgentRole.WIN_STRATEGIST,
                        disputed_claim="The quality case outweighs missing proof.",
                        rebuttal=(
                            "Named lead proof is a qualification requirement, not "
                            "only a scoring issue."
                        ),
                        evidence_refs=[refs["named_lead"]],
                    )
                ],
                revised_stance=BidVerdict.NO_BID,
                evidence_refs=[refs["named_lead"]],
                missing_info=["Named lead CV remains the critical open item."],
            ),
        ),
    ]


def _build_judge_decision(
    refs: Mapping[str, EvidenceReference],
    *,
    verdict: FinalVerdict,
    vote_summary: VoteSummary,
) -> JudgeDecision:
    evidence_ids = [
        ref.evidence_id
        for ref in [
            refs["tender_iso"],
            refs["company_iso"],
            refs["named_lead"],
            refs["company_capacity"],
            refs["liability"],
        ]
        if ref.evidence_id is not None
    ]
    needs_review = verdict is FinalVerdict.NEEDS_HUMAN_REVIEW
    return JudgeDecision(
        verdict=verdict,
        confidence=0.42 if needs_review else 0.74,
        vote_summary=vote_summary,
        disagreement_summary=(
            "Specialists agree capability is credible but disagree on missing "
            "named-lead and liability risk."
        ),
        compliance_matrix=[
            {
                "requirement": "Active ISO 27001 certification",
                "requirement_type": RequirementType.QUALITY_MANAGEMENT,
                "status": "met",
                "assessment": "Tender requirement and company proof are both present.",
                "evidence_refs": [refs["tender_iso"], refs["company_iso"]],
            },
            {
                "requirement": "Named security-cleared delivery lead",
                "requirement_type": RequirementType.QUALIFICATION_REQUIREMENT,
                "status": "unknown" if needs_review else "unmet",
                "assessment": (
                    "The tender asks for a named lead; fixture evidence lacks "
                    "the CV."
                ),
                "evidence_refs": [refs["named_lead"]],
            },
        ],
        compliance_blockers=[],
        potential_blockers=[
            _claim(
                "Named lead proof remains open before submission.",
                refs["named_lead"],
                requirement_type=RequirementType.QUALIFICATION_REQUIREMENT,
            )
        ],
        risk_register=[
            {
                "risk": "Delay penalties may reduce delivery margin.",
                "requirement_type": RequirementType.CONTRACT_OBLIGATION,
                "severity": "medium",
                "mitigation": "Review liability cap and contingency staffing.",
                "evidence_refs": [refs["liability"], refs["company_capacity"]],
            }
        ],
        missing_info=(
            ["Named security-cleared lead CV is critical before a defensible verdict."]
            if needs_review
            else ["Named security-cleared lead CV."]
        ),
        missing_info_details=[
            {
                "text": (
                    "The tender requires a named lead, but the fixture only "
                    "proves capacity."
                ),
                "requirement_type": RequirementType.QUALIFICATION_REQUIREMENT,
                "evidence_refs": [refs["named_lead"], refs["company_capacity"]],
            }
        ],
        potential_evidence_gaps=(
            ["Critical named-lead proof is absent from fixture evidence."]
            if needs_review
            else ["Named lead evidence must be attached before submission."]
        ),
        recommended_actions=[
            "Attach named security-cleared lead CV.",
            "Confirm liability cap before final bid approval.",
        ],
        recommended_action_details=[
            {
                "text": (
                    "Use the ISO and capacity proof, then close named-lead and "
                    "liability gaps."
                ),
                "requirement_type": RequirementType.QUALIFICATION_REQUIREMENT,
                "evidence_refs": [
                    refs["company_iso"],
                    refs["company_capacity"],
                    refs["named_lead"],
                ],
            }
        ],
        cited_memo=(
            "Needs human review because critical named-lead proof is missing."
            if needs_review
            else (
                "Conditional bid because ISO proof, capacity, and public-sector "
                "reference are supported, while named-lead and liability actions "
                "remain open."
            )
        ),
        evidence_ids=evidence_ids,
        evidence_refs=[refs["tender_iso"], refs["company_iso"], refs["named_lead"]],
    )


def _claim(
    claim: str,
    *refs: EvidenceReference,
    requirement_type: RequirementType | None = None,
) -> SupportedClaim:
    return SupportedClaim(
        claim=claim,
        requirement_type=requirement_type,
        evidence_refs=list(refs),
    )


def _evidence_refs(
    evidence_by_key: Mapping[str, Mapping[str, Any]],
) -> dict[str, EvidenceReference]:
    return {
        "tender_iso": _agent_ref(evidence_by_key["DEMO-REPLAY-TENDER-ISO-27001"]),
        "named_lead": _agent_ref(evidence_by_key["DEMO-REPLAY-TENDER-NAMED-LEAD"]),
        "deadline": _agent_ref(evidence_by_key["DEMO-REPLAY-TENDER-DEADLINE"]),
        "evaluation": _agent_ref(evidence_by_key["DEMO-REPLAY-TENDER-EVALUATION"]),
        "liability": _agent_ref(evidence_by_key["DEMO-REPLAY-TENDER-LIABILITY"]),
        "dpa": _agent_ref(evidence_by_key["DEMO-REPLAY-TENDER-DPA"]),
        "exclusion": _agent_ref(evidence_by_key["DEMO-REPLAY-TENDER-EXCLUSION"]),
        "company_iso": _agent_ref(evidence_by_key["DEMO-REPLAY-COMPANY-ISO-27001"]),
        "company_capacity": _agent_ref(
            evidence_by_key["DEMO-REPLAY-COMPANY-CAPACITY"]
        ),
        "company_reference": _agent_ref(
            evidence_by_key["DEMO-REPLAY-COMPANY-REFERENCE"]
        ),
        "company_rate_card": _agent_ref(
            evidence_by_key["DEMO-REPLAY-COMPANY-RATE-CARD"]
        ),
    }


def _agent_ref(row: Mapping[str, Any]) -> EvidenceReference:
    return EvidenceReference(
        evidence_key=str(row["evidence_key"]),
        source_type=SourceType(str(row["source_type"])),
        evidence_id=_uuid_from_row(row, "evidence_items.id"),
    )


def _state_refs(refs: Sequence[EvidenceReference]) -> list[EvidenceRef]:
    seen: set[tuple[str, str, UUID | None]] = set()
    state_refs: list[EvidenceRef] = []
    for ref in refs:
        key = (ref.evidence_key, ref.source_type.value, ref.evidence_id)
        if key in seen:
            continue
        seen.add(key)
        state_refs.append(
            EvidenceRef(
                evidence_key=ref.evidence_key,
                source_type=EvidenceSourceType(ref.source_type.value),
                evidence_id=ref.evidence_id,
            )
        )
    return state_refs


def _agent_output_payload(
    *,
    state_name: str,
    run_id: UUID,
    output: AgentOutputState,
) -> dict[str, Any]:
    return {
        "id": str(
            _fixture_uuid(
                "agent_outputs",
                state_name,
                output.agent_role,
                output.round_name,
                output.output_type,
            )
        ),
        "tenant_key": DEMO_TENANT_KEY,
        "agent_run_id": str(run_id),
        "agent_role": output.agent_role,
        "round_name": output.round_name,
        "output_type": output.output_type,
        "validated_payload": output.payload,
        "model_metadata": {
            "provider": "fixture",
            "model": "deterministic-replayable-demo-state",
        },
        "started_at": "2026-04-19T08:05:30+00:00",
        "completed_at": "2026-04-19T08:06:00+00:00",
        "duration_ms": 100,
        "input_tokens": 0,
        "output_tokens": 0,
        "estimated_cost_usd": 0,
        "validation_errors": [
            error.model_dump(mode="json") for error in output.validation_errors
        ],
        "metadata": _fixture_metadata(
            "agent_outputs",
            state=state_name,
            details={
                "source": DEMO_STATES_SOURCE,
                "audit_artifact": "validated_payload",
                "evidence_refs": [
                    ref.model_dump(mode="json") for ref in output.evidence_refs
                ],
            },
        ),
    }


def _bid_decision_payload(
    *,
    state_name: str,
    run_id: UUID,
    judge_payload: Mapping[str, Any],
    agent_outputs: Sequence[AgentOutputState],
) -> dict[str, Any]:
    evidence_ids = [str(evidence_id) for evidence_id in judge_payload["evidence_ids"]]
    return {
        "id": str(_fixture_uuid("bid_decisions", state_name)),
        "tenant_key": DEMO_TENANT_KEY,
        "agent_run_id": str(run_id),
        "final_decision": dict(judge_payload),
        "verdict": str(judge_payload["verdict"]),
        "confidence": float(judge_payload["confidence"]),
        "evidence_ids": evidence_ids,
        "metadata": _fixture_metadata(
            "bid_decisions",
            state=state_name,
            details={
                "source_agent_outputs": [
                    {
                        "agent_role": output.agent_role,
                        "round_name": output.round_name,
                        "output_type": output.output_type,
                    }
                    for output in agent_outputs
                ],
            },
        ),
    }


def _upsert_owned_fixture_rows(
    client: SupabaseDemoStateClient,
    table_name: str,
    payloads: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        _upsert_owned_fixture_row(client, table_name, payload)
        for payload in payloads
    ]


def _upsert_owned_fixture_row(
    client: SupabaseDemoStateClient,
    table_name: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    existing = _select_one(client, table_name, {"id": str(payload["id"])})
    if existing is not None:
        _require_fixture_owned(table_name, existing)
    response = client.table(table_name).upsert(payload, on_conflict="id").execute()
    rows = _response_rows(response)
    if rows:
        return dict(rows[0])
    selected = _select_one(client, table_name, {"id": str(payload["id"])})
    if selected is None:
        raise DemoStatesSeedError(f"Supabase {table_name} upsert returned no row.")
    return dict(selected)


def _insert_missing_fixture_row(
    client: SupabaseDemoStateClient,
    table_name: str,
    payload: dict[str, Any],
    *,
    identity_filters: Mapping[str, object],
) -> dict[str, Any]:
    existing_by_id = _select_one(client, table_name, {"id": str(payload["id"])})
    if existing_by_id is not None:
        _require_fixture_owned(table_name, existing_by_id)
        return dict(existing_by_id)

    existing_by_identity = _select_one(client, table_name, identity_filters)
    if existing_by_identity is not None:
        _require_fixture_owned(table_name, existing_by_identity)
        return dict(existing_by_identity)

    response = client.table(table_name).insert(payload).execute()
    rows = _response_rows(response)
    if rows:
        return dict(rows[0])
    selected = _select_one(client, table_name, {"id": str(payload["id"])})
    if selected is None:
        raise DemoStatesSeedError(f"Supabase {table_name} insert returned no row.")
    return dict(selected)


def _select_one(
    client: SupabaseDemoStateClient,
    table_name: str,
    filters: Mapping[str, object],
) -> Mapping[str, Any] | None:
    query = client.table(table_name).select("*")
    for column, value in filters.items():
        query = query.eq(column, value)
    rows = _response_rows(query.limit(1).execute())
    return rows[0] if rows else None


def _response_rows(response: Any) -> list[Mapping[str, Any]]:
    data = getattr(response, "data", None)
    if not isinstance(data, list):
        raise DemoStatesSeedError("Supabase response did not return a row list.")
    return [row for row in data if isinstance(row, Mapping)]


def _require_fixture_owned(table_name: str, row: Mapping[str, Any]) -> None:
    if _is_fixture_owned(row):
        return
    raise DemoStatesSeedError(
        f"Refusing to mutate non-fixture {table_name} row {row.get('id')!r}."
    )


def _is_fixture_owned(row: Mapping[str, Any]) -> bool:
    metadata = row.get("metadata")
    if not isinstance(metadata, Mapping):
        return False
    fixture = metadata.get("fixture")
    return (
        isinstance(fixture, Mapping)
        and fixture.get("seed_key") == DEMO_STATES_FIXTURE_KEY
    )


def _fixture_metadata(
    table_name: str,
    *,
    state: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = {
        "created_via": DEMO_STATES_SOURCE,
        "fixture": {
            "seed_key": DEMO_STATES_FIXTURE_KEY,
            "version": DEMO_STATES_FIXTURE_VERSION,
            "table": table_name,
            "owned": True,
        },
    }
    if state is not None:
        metadata["fixture"]["state"] = state
    if details:
        metadata.update(dict(details))
    return metadata


def _evidence_state_from_row(row: Mapping[str, Any]) -> EvidenceItemState:
    return EvidenceItemState(
        evidence_id=_uuid_from_row(row, "evidence_items.id"),
        evidence_key=str(row["evidence_key"]),
        source_type=EvidenceSourceType(str(row["source_type"])),
        excerpt=str(row["excerpt"]),
        normalized_meaning=str(row["normalized_meaning"]),
        category=str(row["category"]),
        requirement_type=row.get("requirement_type"),
        confidence=float(row["confidence"]),
        source_metadata=dict(_mapping(row.get("source_metadata"))),
        document_id=_optional_uuid(row.get("document_id")),
        chunk_id=_optional_uuid(row.get("chunk_id")),
        page_start=_optional_int(row.get("page_start")),
        page_end=_optional_int(row.get("page_end")),
        company_id=_optional_uuid(row.get("company_id")),
        field_path=(
            str(row["field_path"]) if row.get("field_path") is not None else None
        ),
    )


def _uuid_from_row(row: Mapping[str, Any], field_name: str) -> UUID:
    value = row.get("id")
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise DemoStatesSeedError(f"{field_name} must be a UUID.") from exc


def _optional_uuid(value: Any) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(str(value))
    except ValueError as exc:
        raise DemoStatesSeedError("optional UUID field must be a UUID.") from exc


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise DemoStatesSeedError("optional integer field must be an integer.") from exc


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _fixture_uuid(*parts: object) -> UUID:
    return uuid5(_FIXTURE_NAMESPACE, "/".join(str(part) for part in parts))


__all__ = [
    "DEMO_STATES_FIXTURE_KEY",
    "DEMO_STATES_FIXTURE_VERSION",
    "DemoStatesSeedError",
    "DemoStatesSeedResult",
    "seed_demo_states",
]
