from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import UUID

from bidded.orchestration import (
    AgentRunStatus,
    BidRunState,
    DocumentChunkState,
    EvidenceItemState,
    EvidenceSourceType,
    GraphRouteNode,
    ScoutOutputState,
    SpecialistRole,
    default_graph_node_handlers,
    run_bidded_graph_shell,
)
from bidded.orchestration.specialist_motions import (
    Round1SpecialistRequest,
    build_round_1_specialist_handler,
    build_round_1_specialist_request,
)
from bidded.requirements import RequirementType

RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
COMPANY_ID = UUID("22222222-2222-4222-8222-222222222222")
TENDER_ID = UUID("33333333-3333-4333-8333-333333333333")
DOCUMENT_ID = UUID("44444444-4444-4444-8444-444444444444")
CHUNK_ID = UUID("55555555-5555-4555-8555-555555555555")
TENDER_EVIDENCE_ID = UUID("66666666-6666-4666-8666-666666666666")
COMPANY_EVIDENCE_ID = UUID("77777777-7777-4777-8777-777777777777")
FINANCIAL_EVIDENCE_ID = UUID("88888888-8888-4888-8888-888888888888")


class RecordingRound1Model:
    def __init__(self) -> None:
        self.requests: list[Round1SpecialistRequest] = []

    def draft_motion(self, request: Round1SpecialistRequest) -> dict[str, Any]:
        self.requests.append(request)
        tender_ref = {
            "evidence_key": "TENDER-SHALL-001",
            "source_type": "tender_document",
            "evidence_id": str(TENDER_EVIDENCE_ID),
        }
        company_ref = {
            "evidence_key": "COMPANY-CERT-001",
            "source_type": "company_profile",
            "evidence_id": str(COMPANY_EVIDENCE_ID),
        }
        formal_blockers = []
        if request.agent_role.value == SpecialistRole.COMPLIANCE.value:
            formal_blockers = [
                {
                    "claim": ("The tender requires ISO 27001 proof before submission."),
                    "evidence_refs": [tender_ref],
                }
            ]

        return {
            "agent_role": request.agent_role.value,
            "vote": "conditional_bid",
            "confidence": 0.76,
            "top_findings": [
                {
                    "claim": (
                        "The tender requires ISO 27001 and the company profile "
                        "cites ISO 27001."
                    ),
                    "evidence_refs": [tender_ref, company_ref],
                }
            ],
            "role_specific_risks": [
                {
                    "claim": f"{request.agent_role.value} needs certificate validity.",
                    "evidence_refs": [company_ref],
                }
            ],
            "formal_blockers": formal_blockers,
            "potential_blockers": [],
            "assumptions": ["The certificate remains valid through submission."],
            "missing_info": ["Certificate expiry date."],
            "recommended_actions": ["Confirm certificate validity."],
        }


class InvalidFormalBlockerModel(RecordingRound1Model):
    def draft_motion(self, request: Round1SpecialistRequest) -> dict[str, Any]:
        payload = super().draft_motion(request)
        if request.agent_role.value == SpecialistRole.WIN_STRATEGIST.value:
            payload["formal_blockers"] = [
                {
                    "claim": "Win Strategist must not mark formal blockers.",
                    "evidence_refs": [
                        {
                            "evidence_key": "TENDER-SHALL-001",
                            "source_type": "tender_document",
                            "evidence_id": str(TENDER_EVIDENCE_ID),
                        }
                    ],
                }
            ]
        return payload


class FinancialProofFormalBlockerModel(RecordingRound1Model):
    def draft_motion(self, request: Round1SpecialistRequest) -> dict[str, Any]:
        payload = super().draft_motion(request)
        if request.agent_role.value == SpecialistRole.COMPLIANCE.value:
            payload["formal_blockers"] = [
                {
                    "claim": (
                        "Missing credit report evidence is a hard no-bid blocker."
                    ),
                    "evidence_refs": [_financial_ref()],
                }
            ]
        return payload


class MutatedEvidenceKeyModel(RecordingRound1Model):
    def draft_motion(self, request: Round1SpecialistRequest) -> dict[str, Any]:
        payload = super().draft_motion(request)
        for field in (
            "top_findings",
            "role_specific_risks",
            "formal_blockers",
            "potential_blockers",
        ):
            for claim in payload.get(field, []):
                for ref in claim.get("evidence_refs", []):
                    if ref.get("evidence_id") == str(TENDER_EVIDENCE_ID):
                        ref["evidence_key"] = "TENDER-SHALL-MUTATED-BY-CLAUDE"
        return payload


class UuidPastedIntoBothFieldsModel(RecordingRound1Model):
    """Simulates the LLM pasting the same UUID into evidence_key AND evidence_id.

    Observed in production (see the SiS tender run logs). The canonicalizer's
    "key-as-id" match branch rescues this by recognizing the evidence_key
    slot contains what's actually a UUID.
    """

    def draft_motion(self, request: Round1SpecialistRequest) -> dict[str, Any]:
        payload = super().draft_motion(request)
        for field in ("top_findings", "role_specific_risks"):
            for claim in payload.get(field, []):
                for ref in claim.get("evidence_refs", []):
                    if ref.get("evidence_id") == str(TENDER_EVIDENCE_ID):
                        ref["evidence_key"] = str(TENDER_EVIDENCE_ID)
        return payload


class MissingEvidenceIdModel(RecordingRound1Model):
    """Simulates the LLM emitting only ``evidence_key`` without ``evidence_id``.

    ``SupportedClaim.validate_evidence_ids`` would reject a null evidence_id
    pre-coercion; the shared canonicalizer fills it in by looking up the key
    against the evidence board.
    """

    def draft_motion(self, request: Round1SpecialistRequest) -> dict[str, Any]:
        payload = super().draft_motion(request)
        for field in ("top_findings", "role_specific_risks"):
            for claim in payload.get(field, []):
                for ref in claim.get("evidence_refs", []):
                    ref.pop("evidence_id", None)
        return payload


class ExtraTopLevelKeyModel(RecordingRound1Model):
    """Simulates the LLM adding an un-schema'd top-level key like
    ``evaluation_summary``. ``StrictAgentOutputModel`` sets
    ``extra="forbid"`` so without the whitelist step this would abort.
    """

    def draft_motion(self, request: Round1SpecialistRequest) -> dict[str, Any]:
        payload = super().draft_motion(request)
        payload["evaluation_summary"] = "Looks like a solid opportunity."
        payload["reasoning"] = "Strong alignment with prior engagements."
        return payload


def _ready_state() -> BidRunState:
    return BidRunState(
        run_id=RUN_ID,
        company_id=COMPANY_ID,
        tender_id=TENDER_ID,
        document_ids=[DOCUMENT_ID],
        run_context={
            "tenant_key": "demo",
            "private_context": "must not reach Round 1 specialists",
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
        ],
    )


def _state_with_financial_requirement() -> BidRunState:
    state = _ready_state()
    return state.model_copy(
        update={
            "evidence_board": [
                *state.evidence_board,
                EvidenceItemState(
                    evidence_id=FINANCIAL_EVIDENCE_ID,
                    evidence_key="TENDER-FINANCIAL-001",
                    source_type=EvidenceSourceType.TENDER_DOCUMENT,
                    excerpt="Supplier must submit a current credit report.",
                    normalized_meaning="Financial standing proof is required.",
                    category="qualification_criterion",
                    requirement_type=RequirementType.FINANCIAL_STANDING,
                    confidence=0.92,
                    source_metadata={
                        "source_label": "Tender page 2",
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
                    page_start=2,
                    page_end=2,
                ),
            ]
        }
    )


def test_round_1_specialists_get_evidence_locked_requests_and_persist_rows() -> None:
    model = RecordingRound1Model()
    handlers = replace(
        default_graph_node_handlers(),
        round_1_specialist=build_round_1_specialist_handler(model),
    )

    result = run_bidded_graph_shell(_ready_state(), handlers=handlers)

    assert result.state.status is AgentRunStatus.SUCCEEDED
    assert GraphRouteNode.ROUND_1_JOIN in result.visited_nodes
    assert {request.agent_role.value for request in model.requests} == {
        role.value for role in SpecialistRole
    }
    expected_evidence_keys = ["TENDER-SHALL-001", "COMPANY-CERT-001"]
    assert [
        [item.evidence_key for item in request.evidence_board]
        for request in model.requests
    ] == [expected_evidence_keys] * 4
    assert all(request.scout_output is not None for request in model.requests)
    compliance_request = next(
        request
        for request in model.requests
        if request.agent_role.value == SpecialistRole.COMPLIANCE.value
    )
    assert [
        context.model_dump(mode="json")
        for context in compliance_request.requirement_context
    ] == [
        {
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
                    "suggested_proof_action": (
                        "Prepare quality management certificates."
                    ),
                    "blocker_hint": (
                        "Missing mandatory quality-system proof can block "
                        "qualification."
                    ),
                }
            ],
        }
    ]

    request_fields = set(Round1SpecialistRequest.model_fields)
    assert "motions" not in request_fields
    assert "rebuttals" not in request_fields
    assert "run_context" not in request_fields
    assert "private_context" not in request_fields

    assert set(result.state.motions) == set(SpecialistRole)
    motion_rows = [
        output
        for output in result.state.agent_outputs
        if output.round_name == "round_1_motion"
    ]
    assert len(motion_rows) == 4
    assert {row.agent_role for row in motion_rows} == {
        role.value for role in SpecialistRole
    }
    assert all(row.output_type == "motion" for row in motion_rows)
    assert all(row.evidence_refs for row in motion_rows)

    for row in motion_rows:
        payload = row.payload
        assert payload["vote"] == "conditional_bid"
        assert payload["confidence"] == 0.76
        assert payload["top_findings"][0]["evidence_refs"]
        assert payload["role_specific_risks"][0]["evidence_refs"]
        assert payload["assumptions"] == [
            "The certificate remains valid through submission."
        ]
        assert payload["missing_info"] == ["Certificate expiry date."]
        assert payload["recommended_actions"] == ["Confirm certificate validity."]

    blockers_by_role = {
        row.agent_role: row.payload["formal_blockers"] for row in motion_rows
    }
    assert blockers_by_role[SpecialistRole.COMPLIANCE.value]
    assert blockers_by_role[SpecialistRole.WIN_STRATEGIST.value] == []
    assert blockers_by_role[SpecialistRole.DELIVERY_CFO.value] == []
    assert blockers_by_role[SpecialistRole.RED_TEAM.value] == []


def test_compliance_request_includes_evidence_recall_warnings() -> None:
    state = _ready_state().model_copy(
        update={
            "chunks": [
                DocumentChunkState(
                    chunk_id=UUID("55555555-5555-4555-8555-555555555556"),
                    document_id=DOCUMENT_ID,
                    chunk_index=1,
                    page_start=2,
                    page_end=2,
                    text="Bidders must submit a current credit report.",
                    metadata={"source_label": "Tender page 2"},
                )
            ],
            "scout_output": ScoutOutputState(),
        }
    )

    request = build_round_1_specialist_request(state, SpecialistRole.COMPLIANCE)

    recalled_types = [
        warning.requirement_type for warning in request.evidence_recall_warnings
    ]
    assert recalled_types == [RequirementType.FINANCIAL_STANDING]
    assert request.evidence_recall_warnings[0].source_label == "Tender page 2"
    assert "financial_standing" in request.evidence_recall_warnings[0].missing_info


def test_round_1_request_includes_fit_gap_board() -> None:
    state = _ready_state().model_copy(
        update={
            "scout_output": ScoutOutputState(),
            "fit_gap_board": [_fit_gap_payload()],
        }
    )

    request = build_round_1_specialist_request(state, SpecialistRole.COMPLIANCE)

    assert request.fit_gap_board[0].requirement_key == "TENDER-SHALL-001"
    assert request.fit_gap_board[0].match_status.value == "partial_match"


def test_non_compliance_formal_blocker_is_migrated_to_potential_blocker() -> None:
    """A non-compliance specialist that wrongly populates ``formal_blockers``
    no longer aborts the run. The pre-validate coercer migrates every entry
    into ``potential_blockers`` and clears ``formal_blockers``, so the
    Pydantic ``@model_validator`` that would have rejected it never fires.
    The concern is preserved — the Judge still weighs it — but it does not
    automatically gate to no_bid.
    """
    handlers = replace(
        default_graph_node_handlers(),
        round_1_specialist=build_round_1_specialist_handler(
            InvalidFormalBlockerModel()
        ),
    )

    result = run_bidded_graph_shell(_ready_state(), handlers=handlers)

    assert result.state.status is AgentRunStatus.SUCCEEDED
    win_motion = next(
        output
        for output in result.state.agent_outputs
        if output.round_name == "round_1_motion"
        and output.agent_role == SpecialistRole.WIN_STRATEGIST.value
    )
    # formal_blockers is empty on the persisted motion...
    assert win_motion.payload["formal_blockers"] == []
    # ...and the blocker text survives under potential_blockers with its
    # original evidence_ref intact.
    migrated = [
        b
        for b in win_motion.payload["potential_blockers"]
        if b["claim"] == "Win Strategist must not mark formal blockers."
    ]
    assert len(migrated) == 1
    assert migrated[0]["evidence_refs"][0]["evidence_key"] == "TENDER-SHALL-001"


def test_financial_proof_gap_demoted_to_potential_blocker() -> None:
    """A compliance_officer claim that cites FINANCIAL_STANDING evidence as a
    formal_blocker should be auto-demoted to potential_blockers rather than
    failing the whole run. Formal blockers gate to no_bid and therefore require
    exclusion_ground or qualification_requirement evidence; financial-standing
    concerns still surface as potential blockers for the Judge to weigh.
    """
    handlers = replace(
        default_graph_node_handlers(),
        round_1_specialist=build_round_1_specialist_handler(
            FinancialProofFormalBlockerModel()
        ),
    )

    result = run_bidded_graph_shell(
        _state_with_financial_requirement(),
        handlers=handlers,
    )

    assert result.state.status is AgentRunStatus.SUCCEEDED
    compliance_motion = next(
        output
        for output in result.state.agent_outputs
        if output.round_name == "round_1_motion"
        and output.agent_role == "compliance_officer"
    )
    # The claim is no longer in formal_blockers...
    assert compliance_motion.payload["formal_blockers"] == []
    # ...it has been demoted to potential_blockers, preserving the claim text
    # and the same evidence_ref.
    demoted = [
        b
        for b in compliance_motion.payload["potential_blockers"]
        if b["claim"] == "Missing credit report evidence is a hard no-bid blocker."
    ]
    assert len(demoted) == 1
    assert demoted[0]["evidence_refs"][0]["evidence_key"] == "TENDER-FINANCIAL-001"


def test_round_1_canonicalizes_evidence_key_from_matching_id() -> None:
    handlers = replace(
        default_graph_node_handlers(),
        round_1_specialist=build_round_1_specialist_handler(MutatedEvidenceKeyModel()),
    )

    result = run_bidded_graph_shell(_ready_state(), handlers=handlers)

    assert result.state.status is AgentRunStatus.SUCCEEDED
    motion_rows = [
        output
        for output in result.state.agent_outputs
        if output.round_name == "round_1_motion"
    ]
    assert motion_rows
    assert {
        ref.evidence_key
        for output in motion_rows
        for ref in output.evidence_refs
        if ref.evidence_id == TENDER_EVIDENCE_ID
    } == {"TENDER-SHALL-001"}
    assert {
        ref["evidence_key"]
        for output in motion_rows
        for claim in output.payload["top_findings"]
        for ref in claim["evidence_refs"]
        if ref["evidence_id"] == str(TENDER_EVIDENCE_ID)
    } == {"TENDER-SHALL-001"}


def _financial_ref() -> dict[str, str]:
    return {
        "evidence_key": "TENDER-FINANCIAL-001",
        "source_type": "tender_document",
        "evidence_id": str(FINANCIAL_EVIDENCE_ID),
    }


def _fit_gap_payload() -> dict[str, Any]:
    return {
        "agent_run_id": str(RUN_ID),
        "tender_id": str(TENDER_ID),
        "company_id": str(COMPANY_ID),
        "requirement_key": "TENDER-SHALL-001",
        "requirement": "ISO 27001 certification is mandatory.",
        "requirement_type": "qualification_requirement",
        "match_status": "partial_match",
        "risk_level": "medium",
        "confidence": 0.68,
        "assessment": "Company evidence partially supports the requirement.",
        "tender_evidence_refs": [
            {
                "evidence_key": "TENDER-SHALL-001",
                "source_type": "tender_document",
                "evidence_id": str(TENDER_EVIDENCE_ID),
            }
        ],
        "company_evidence_refs": [
            {
                "evidence_key": "COMPANY-CERT-001",
                "source_type": "company_profile",
                "evidence_id": str(COMPANY_EVIDENCE_ID),
            }
        ],
        "tender_evidence_ids": [str(TENDER_EVIDENCE_ID)],
        "company_evidence_ids": [str(COMPANY_EVIDENCE_ID)],
        "missing_info": ["Certificate expiry date."],
        "recommended_actions": ["Confirm certificate validity."],
        "metadata": {"source": "test"},
    }


def test_round_1_heals_uuid_pasted_into_evidence_key() -> None:
    """Classic LLM drift: same UUID in both evidence_key and evidence_id.

    Pre-coercion canonicalizer recognizes the key slot holds a UUID and
    rebuilds the ref from the board item that matches. Without this healing
    SupportedClaim.validate_evidence_ids would pass (id is present) but the
    downstream board-membership check would fail because evidence_key
    doesn't match any board item.
    """
    handlers = replace(
        default_graph_node_handlers(),
        round_1_specialist=build_round_1_specialist_handler(
            UuidPastedIntoBothFieldsModel()
        ),
    )

    result = run_bidded_graph_shell(_ready_state(), handlers=handlers)

    assert result.state.status is AgentRunStatus.SUCCEEDED
    motion_rows = [
        output
        for output in result.state.agent_outputs
        if output.round_name == "round_1_motion"
    ]
    assert motion_rows
    # Every persisted evidence_ref carries the canonical human-readable key,
    # not the UUID the LLM accidentally pasted there.
    for output in motion_rows:
        for claim in output.payload["top_findings"]:
            for ref in claim["evidence_refs"]:
                if ref["evidence_id"] == str(TENDER_EVIDENCE_ID):
                    assert ref["evidence_key"] == "TENDER-SHALL-001"


def test_round_1_fills_missing_evidence_id_from_key() -> None:
    """LLM emits only ``evidence_key``; the canonicalizer fills the missing
    evidence_id from the board (since the key is unambiguous).
    """
    handlers = replace(
        default_graph_node_handlers(),
        round_1_specialist=build_round_1_specialist_handler(MissingEvidenceIdModel()),
    )

    result = run_bidded_graph_shell(_ready_state(), handlers=handlers)

    assert result.state.status is AgentRunStatus.SUCCEEDED
    motion_rows = [
        output
        for output in result.state.agent_outputs
        if output.round_name == "round_1_motion"
    ]
    assert motion_rows
    for output in motion_rows:
        for claim in output.payload["top_findings"]:
            for ref in claim["evidence_refs"]:
                # Every ref is canonical: key, source_type, AND evidence_id.
                assert ref.get("evidence_id") is not None
                assert len(ref["evidence_id"]) > 0


def test_round_1_drops_extra_top_level_keys() -> None:
    """LLM sprinkles unspec'd keys like ``evaluation_summary``. The
    top-level whitelist strips them pre-validate so Pydantic's
    ``extra="forbid"`` doesn't trip.
    """
    handlers = replace(
        default_graph_node_handlers(),
        round_1_specialist=build_round_1_specialist_handler(ExtraTopLevelKeyModel()),
    )

    result = run_bidded_graph_shell(_ready_state(), handlers=handlers)

    assert result.state.status is AgentRunStatus.SUCCEEDED
    motion_rows = [
        output
        for output in result.state.agent_outputs
        if output.round_name == "round_1_motion"
    ]
    assert motion_rows
    # Persisted payload doesn't carry the stripped extras.
    for output in motion_rows:
        assert "evaluation_summary" not in output.payload
        assert "reasoning" not in output.payload
