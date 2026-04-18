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
    FinalVerdict,
    JudgeDecision,
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


def _evidence_ref() -> EvidenceReference:
    return EvidenceReference(
        evidence_id=EVIDENCE_ID,
        evidence_key="TENDER-REQ-001",
        source_type=SourceType.TENDER_DOCUMENT,
    )


def _supported_claim(
    claim: str = "ISO 27001 certification is mandatory.",
) -> SupportedClaim:
    return SupportedClaim(
        claim=claim,
        evidence_refs=[_evidence_ref()],
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
        recommended_actions=["Confirm ISO certificate validity before submission."],
        validation_errors=[
            AgentValidationError(
                field_path="top_findings[0].evidence_refs",
                message="Evidence citation was normalized to evidence key.",
            )
        ],
    )

    payload = motion.model_dump(mode="json")

    assert payload["agent_role"] == "compliance_officer"
    assert payload["vote"] == "conditional_bid"
    assert payload["top_findings"][0]["evidence_refs"][0]["evidence_id"] == str(
        EVIDENCE_ID
    )
    assert Round1Motion.model_validate(payload) == motion

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        Round1Motion.model_validate({**payload, "private_notes": "not audit safe"})

    with pytest.raises(ValidationError, match="at least 1 item"):
        SupportedClaim(claim="Unsupported material claim.", evidence_refs=[])


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
        )


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
        evidence_refs=[_evidence_ref()],
        missing_info=["Named staffing confirmation."],
        recommended_actions=["Escalate unresolved blockers to the operator."],
        validation_errors=[],
    )

    payload = rebuttal.model_dump(mode="json")

    assert payload["agent_role"] == "red_team"
    assert payload["revised_stance"] == "no_bid"
    assert payload["targeted_disagreements"][0]["target_role"] == "win_strategist"
    assert Round2Rebuttal.model_validate(payload) == rebuttal

    with pytest.raises(ValidationError, match="Input should be"):
        BlockerChallenge(
            blocker="Invalid blocker challenge.",
            position="defer",
            rationale="Unsupported position values should not validate.",
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
                status="unknown",
                assessment="Requirement is identified but expiry evidence is missing.",
                evidence_refs=[_evidence_ref()],
            )
        ],
        compliance_blockers=[],
        potential_blockers=[
            _supported_claim("ISO certificate expiry date is not confirmed.")
        ],
        risk_register=[
            RiskRegisterItem(
                risk="Submission could be rejected if the certificate has expired.",
                severity="high",
                mitigation="Confirm certificate validity before final bid approval.",
                evidence_refs=[_evidence_ref()],
            )
        ],
        missing_info=["Certificate expiry date."],
        recommended_actions=["Verify the certificate with the bid manager."],
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
    assert payload["evidence_ids"] == [str(EVIDENCE_ID)]
    assert JudgeDecision.model_validate(payload) == decision

    with pytest.raises(ValidationError, match="less than or equal to 1"):
        JudgeDecision.model_validate({**payload, "confidence": 1.1})
