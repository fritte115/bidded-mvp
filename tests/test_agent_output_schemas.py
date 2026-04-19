from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

from bidded.agents import (
    AgentRole,
    AgentValidationError,
    BidVerdict,
    BlockerChallenge,
    ComplianceMatrixItem,
    EvidenceReference,
    EvidenceScoutOutput,
    FinalVerdict,
    JudgeDecision,
    RequirementReasoningItem,
    RequirementType,
    RiskRegisterItem,
    Round1Motion,
    Round2Rebuttal,
    SourceType,
    SupportedClaim,
    TargetedDisagreement,
    UnsupportedClaim,
    VoteSummary,
)

EVIDENCE_ID = UUID("66666666-6666-4666-8666-666666666666")
COMPANY_EVIDENCE_ID = UUID("77777777-7777-4777-8777-777777777777")


def _evidence_ref() -> EvidenceReference:
    return EvidenceReference(
        evidence_id=EVIDENCE_ID,
        evidence_key="TENDER-REQ-001",
        source_type=SourceType.TENDER_DOCUMENT,
    )


def _unresolved_evidence_ref() -> EvidenceReference:
    return EvidenceReference(
        evidence_key="TENDER-REQ-001",
        source_type=SourceType.TENDER_DOCUMENT,
    )


def _company_evidence_ref() -> EvidenceReference:
    return EvidenceReference(
        evidence_id=COMPANY_EVIDENCE_ID,
        evidence_key="COMPANY-CERT-001",
        source_type=SourceType.COMPANY_PROFILE,
    )


def _supported_claim(
    claim: str = "ISO 27001 certification is mandatory.",
    evidence_refs: list[EvidenceReference] | None = None,
    requirement_type: RequirementType | None = None,
) -> SupportedClaim:
    return SupportedClaim(
        claim=claim,
        requirement_type=requirement_type,
        evidence_refs=evidence_refs or [_evidence_ref()],
    )


def test_requirement_type_contract_is_strict_and_nullable_on_scout_findings() -> None:
    assert [requirement_type.value for requirement_type in RequirementType] == [
        "shall_requirement",
        "qualification_requirement",
        "exclusion_ground",
        "financial_standing",
        "legal_or_regulatory_reference",
        "quality_management",
        "submission_document",
        "contract_obligation",
    ]

    output = EvidenceScoutOutput.model_validate(
        {
            "agent_role": "evidence_scout",
            "findings": [
                {
                    "category": "shall_requirement",
                    "requirement_type": "shall_requirement",
                    "claim": "The supplier shall provide ISO 27001 certification.",
                    "evidence_refs": [_evidence_ref().model_dump(mode="json")],
                },
                {
                    "category": "contract_risk",
                    "claim": "Delay penalties apply for missed milestones.",
                    "evidence_refs": [_evidence_ref().model_dump(mode="json")],
                },
            ],
        }
    )

    payload = output.model_dump(mode="json")

    assert output.findings[0].requirement_type is RequirementType.SHALL_REQUIREMENT
    assert output.findings[1].requirement_type is None
    assert payload["findings"][0]["category"] == "shall_requirement"
    assert payload["findings"][0]["requirement_type"] == "shall_requirement"
    assert payload["findings"][1]["requirement_type"] is None
    assert EvidenceScoutOutput.model_validate(payload) == output

    with pytest.raises(ValidationError, match="Input should be"):
        EvidenceScoutOutput.model_validate(
            {
                **payload,
                "findings": [
                    {
                        **payload["findings"][0],
                        "requirement_type": "nice_to_have",
                    }
                ],
            }
        )


def test_round_1_motion_is_strict_evidence_backed_and_serializable() -> None:
    motion = Round1Motion(
        agent_role=AgentRole.COMPLIANCE_OFFICER,
        vote=BidVerdict.CONDITIONAL_BID,
        confidence=0.72,
        top_findings=[_supported_claim()],
        role_specific_risks=[_supported_claim("Bid validity depends on ISO proof.")],
        formal_blockers=[],
        potential_blockers=[
            _supported_claim("Certificate expiry date has not been confirmed.")
        ],
        assumptions=["The company profile certificate remains valid."],
        missing_info=["Certificate expiry date."],
        potential_evidence_gaps=["Company evidence does not cite certificate expiry."],
        recommended_actions=["Confirm ISO certificate validity before submission."],
        validation_errors=[
            AgentValidationError(
                code="missing_evidence_id",
                field_path="top_findings[0].evidence_refs",
                message="Evidence citation was normalized to evidence key.",
                retryable=True,
            )
        ],
    )

    payload = motion.model_dump(mode="json")

    assert payload["agent_role"] == "compliance_officer"
    assert payload["vote"] == "conditional_bid"
    assert payload["top_findings"][0]["evidence_refs"][0]["evidence_id"] == str(
        EVIDENCE_ID
    )
    assert payload["potential_evidence_gaps"] == [
        "Company evidence does not cite certificate expiry."
    ]
    assert payload["validation_errors"][0]["code"] == "missing_evidence_id"
    assert payload["validation_errors"][0]["retryable"] is True
    assert Round1Motion.model_validate(payload) == motion

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        Round1Motion.model_validate({**payload, "private_notes": "not audit safe"})

    with pytest.raises(ValidationError, match="at least 1 item"):
        SupportedClaim(claim="Unsupported material claim.", evidence_refs=[])

    with pytest.raises(ValidationError, match="evidence_id"):
        SupportedClaim(
            claim="Unsupported material claim.",
            evidence_refs=[_unresolved_evidence_ref()],
        )


def test_specialist_artifacts_reject_non_specialist_roles() -> None:
    motion_payload = {
        "agent_role": AgentRole.JUDGE,
        "vote": BidVerdict.BID,
        "confidence": 0.9,
        "top_findings": [_supported_claim().model_dump(mode="json")],
    }

    with pytest.raises(ValidationError, match="agent_role must be a specialist"):
        Round1Motion.model_validate(motion_payload)

    win_payload = {
        **motion_payload,
        "agent_role": AgentRole.WIN_STRATEGIST,
        "formal_blockers": [_supported_claim().model_dump(mode="json")],
    }

    with pytest.raises(ValidationError, match="formal_blockers"):
        Round1Motion.model_validate(win_payload)

    with pytest.raises(ValidationError, match="target_roles must be specialists"):
        Round2Rebuttal(
            agent_role=AgentRole.COMPLIANCE_OFFICER,
            target_roles=[AgentRole.JUDGE],
            confidence=0.5,
        )


def test_tender_company_comparison_claims_can_cite_both_sources() -> None:
    comparison_claim = _supported_claim(
        "The tender requires ISO 27001 and the company profile cites ISO 27001.",
        evidence_refs=[_evidence_ref(), _company_evidence_ref()],
    )

    motion = Round1Motion(
        agent_role=AgentRole.WIN_STRATEGIST,
        vote=BidVerdict.BID,
        confidence=0.8,
        top_findings=[comparison_claim],
        assumptions=["The certificate remains valid through submission."],
        missing_info=["Exact expiry date is not in the company evidence."],
        potential_evidence_gaps=["Company profile lacks certificate expiry evidence."],
    )

    evidence_refs = motion.top_findings[0].evidence_refs
    source_types = {evidence_ref.source_type for evidence_ref in evidence_refs}

    assert source_types == {
        SourceType.TENDER_DOCUMENT,
        SourceType.COMPANY_PROFILE,
    }


def test_round_2_rebuttal_captures_disagreements_and_revised_stance() -> None:
    rebuttal = Round2Rebuttal(
        agent_role=AgentRole.RED_TEAM,
        target_roles=[AgentRole.WIN_STRATEGIST, AgentRole.DELIVERY_CFO],
        targeted_disagreements=[
            TargetedDisagreement(
                target_role=AgentRole.WIN_STRATEGIST,
                disputed_claim="Strategic fit offsets compliance uncertainty.",
                rebuttal="The uncertainty is a hard dependency, not a preference.",
                evidence_refs=[_evidence_ref()],
            )
        ],
        unsupported_claims=[
            UnsupportedClaim(
                target_role=AgentRole.DELIVERY_CFO,
                claim="Named staff are confirmed.",
                reason="No evidence item cites named consultant availability.",
            )
        ],
        blocker_challenges=[
            BlockerChallenge(
                blocker="Missing ISO certificate expiry date.",
                position="uphold",
                rationale="The expiry date remains unresolved in the evidence board.",
                evidence_refs=[_evidence_ref()],
            )
        ],
        revised_stance=BidVerdict.NO_BID,
        confidence=0.71,
        evidence_refs=[_evidence_ref()],
        missing_info=["Named staffing confirmation."],
        recommended_actions=["Escalate unresolved blockers to the operator."],
        validation_errors=[],
    )

    payload = rebuttal.model_dump(mode="json")

    assert payload["agent_role"] == "red_team"
    assert payload["confidence"] == 0.71
    assert payload["revised_stance"] == "no_bid"
    assert payload["targeted_disagreements"][0]["target_role"] == "win_strategist"
    assert Round2Rebuttal.model_validate(payload) == rebuttal

    with pytest.raises(ValidationError, match="Input should be"):
        BlockerChallenge(
            blocker="Invalid blocker challenge.",
            position="defer",
            rationale="Unsupported position values should not validate.",
            evidence_refs=[_evidence_ref()],
        )

    unresolved_ref_payload = _unresolved_evidence_ref().model_dump(mode="json")
    with pytest.raises(ValidationError, match="evidence_id"):
        Round2Rebuttal.model_validate(
            {
                "agent_role": "red_team",
                "target_roles": ["win_strategist"],
                "confidence": 0.62,
                "targeted_disagreements": [
                    {
                        "target_role": "win_strategist",
                        "disputed_claim": (
                            "Strategic fit offsets compliance uncertainty."
                        ),
                        "rebuttal": (
                            "The rebuttal cites only an unresolved evidence key."
                        ),
                        "evidence_refs": [unresolved_ref_payload],
                    }
                ],
            }
        )

    with pytest.raises(ValidationError, match="at least 1 item"):
        BlockerChallenge(
            blocker="Missing ISO certificate expiry date.",
            position="uphold",
            rationale="A blocker challenge is material and must cite evidence.",
            evidence_refs=[],
        )


def test_judge_decision_covers_final_audit_artifact_contract() -> None:
    decision = JudgeDecision(
        verdict=FinalVerdict.CONDITIONAL_BID,
        confidence=0.81,
        vote_summary=VoteSummary(bid=1, no_bid=1, conditional_bid=2),
        disagreement_summary="The main disagreement is whether ISO proof is blocking.",
        compliance_matrix=[
            ComplianceMatrixItem(
                requirement="ISO 27001 certificate",
                requirement_type=RequirementType.QUALITY_MANAGEMENT,
                status="unknown",
                assessment="Requirement is identified but expiry evidence is missing.",
                evidence_refs=[_evidence_ref()],
            )
        ],
        compliance_blockers=[],
        potential_blockers=[
            _supported_claim(
                "ISO certificate expiry date is not confirmed.",
                requirement_type=RequirementType.QUALITY_MANAGEMENT,
            )
        ],
        risk_register=[
            RiskRegisterItem(
                risk="Submission could be rejected if the certificate has expired.",
                requirement_type=RequirementType.QUALITY_MANAGEMENT,
                severity="high",
                mitigation="Confirm certificate validity before final bid approval.",
                evidence_refs=[_evidence_ref()],
            )
        ],
        missing_info=["Certificate expiry date."],
        missing_info_details=[
            RequirementReasoningItem(
                text="Certificate expiry date.",
                requirement_type=RequirementType.QUALITY_MANAGEMENT,
                evidence_refs=[_evidence_ref()],
            )
        ],
        potential_evidence_gaps=[
            "Company evidence lacks a certificate expiry excerpt."
        ],
        recommended_actions=["Verify the certificate with the bid manager."],
        recommended_action_details=[
            RequirementReasoningItem(
                text="Verify the certificate with the bid manager.",
                requirement_type=RequirementType.QUALITY_MANAGEMENT,
                evidence_refs=[_evidence_ref()],
            )
        ],
        cited_memo="Conditional bid is defensible only if the certificate is valid.",
        evidence_ids=[EVIDENCE_ID],
        evidence_refs=[_evidence_ref()],
        validation_errors=[],
    )

    payload = decision.model_dump(mode="json")

    assert payload["agent_role"] == "judge"
    assert payload["verdict"] == "conditional_bid"
    assert payload["vote_summary"] == {
        "bid": 1,
        "no_bid": 1,
        "conditional_bid": 2,
    }
    assert payload["potential_evidence_gaps"] == [
        "Company evidence lacks a certificate expiry excerpt."
    ]
    assert payload["compliance_matrix"][0]["requirement_type"] == ("quality_management")
    assert payload["potential_blockers"][0]["requirement_type"] == (
        "quality_management"
    )
    assert payload["risk_register"][0]["requirement_type"] == "quality_management"
    assert payload["missing_info_details"][0]["requirement_type"] == (
        "quality_management"
    )
    assert payload["recommended_action_details"][0]["requirement_type"] == (
        "quality_management"
    )
    assert payload["evidence_ids"] == [str(EVIDENCE_ID)]
    assert JudgeDecision.model_validate(payload) == decision

    with pytest.raises(ValidationError, match="less than or equal to 1"):
        JudgeDecision.model_validate({**payload, "confidence": 1.1})

    with pytest.raises(ValidationError, match="at least 1 item"):
        JudgeDecision.model_validate({**payload, "evidence_ids": []})

    with pytest.raises(ValidationError, match="evidence_id"):
        JudgeDecision.model_validate(
            {
                **payload,
                "risk_register": [
                    {
                        "risk": (
                            "Submission could be rejected if ISO evidence is stale."
                        ),
                        "severity": "high",
                        "mitigation": "Resolve the missing certificate evidence.",
                        "evidence_refs": [
                            _unresolved_evidence_ref().model_dump(mode="json")
                        ],
                    }
                ],
            }
        )
