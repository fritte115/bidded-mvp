"""
Anthropic Claude adapters for the Bidded LangGraph swarm.

Uses the Messages API with JSON-only outputs that are validated by existing
Pydantic agent schemas (same contracts as evidence-locked handlers).

Swarm communication model (matches the graph):
- Evidence Scout runs first on retrieved chunks + evidence board.
- Four specialists run in parallel on scout + evidence (no peer motion text).
- Four specialists run Round 2 with all Round 1 motions visible (cross-review).
- Judge consumes motions + rebuttals + vote summary.

Set ``BIDDED_SWARM_BACKEND=anthropic`` and ``ANTHROPIC_API_KEY`` to use this path.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from bidded.agents.schemas import AgentRole
from bidded.llm.anthropic_client import anthropic_complete_json
from bidded.orchestration.evidence_scout import EvidenceScoutRequest
from bidded.orchestration.graph import GraphNodeHandlers, default_graph_node_handlers
from bidded.orchestration.judge import JudgeDecisionRequest
from bidded.orchestration.specialist_motions import Round1SpecialistRequest
from bidded.orchestration.specialist_rebuttals import Round2RebuttalRequest
from bidded.orchestration.state import EvidenceItemState


def _catalog(board: Sequence[EvidenceItemState]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for e in board:
        rows.append(
            {
                "evidence_key": e.evidence_key,
                "source_type": e.source_type.value,
                "evidence_id": str(e.evidence_id) if e.evidence_id else None,
                "excerpt": (e.excerpt or "")[:2000],
                "normalized_meaning": (e.normalized_meaning or "")[:800],
                "field_path": e.field_path,
                "category": e.category,
            }
        )
    return rows


def _scout_chunks_payload(request: EvidenceScoutRequest) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rc in request.retrieved_chunks:
        out.append(
            {
                "category": rc.category,
                "chunk_id": str(rc.chunk_id),
                "document_id": str(rc.document_id),
                "page_start": rc.page_start,
                "page_end": rc.page_end,
                "text": rc.text[:4000],
            }
        )
    return out


_BASE_RULES = (
    "You are part of an audit-grade bid/no-bid workflow. "
    "Every factual claim must cite evidence_refs using evidence_key, source_type, "
    "and evidence_id taken VERBATIM from the evidence catalog JSON provided. "
    "Never invent evidence keys or UUIDs — copy them exactly from the catalog. "
    'Each evidence_ref must look like: {"evidence_key": "...", "source_type": '
    '"tender_document", "evidence_id": "<UUID from catalog>"}. '
    "If a claim cannot be supported by any catalog entry, move it to missing_info "
    "or potential_evidence_gaps — do not hallucinate an evidence reference. "
    "Output a single JSON object only (no markdown fences, no prose outside JSON)."
)


class AnthropicEvidenceScoutModel:
    def __init__(self, *, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    def extract(self, request: EvidenceScoutRequest) -> dict[str, Any]:
        catalog_example = (
            '{"evidence_key": "td-001", "source_type": "tender_document", '
            '"evidence_id": "<UUID from catalog>"}'
        )
        system = (
            _BASE_RULES
            + " You are the Evidence Scout: extract procurement facts by category. "
            "Findings must use ScoutCategory values: deadline, shall_requirement, "
            "qualification_criterion, evaluation_criterion, contract_risk, "
            "required_submission_document. "
            "Each finding must be a JSON object with exactly these keys: "
            "category (string), claim (string — the full factual statement), "
            "evidence_refs (array of evidence refs). "
            "Do not use title, detail, summary, or description instead of claim. "
            f"evidence_refs example: [{catalog_example}]. "
            "Include at least one finding per non-empty evidence catalog. "
            "Return JSON: {agent_role, findings, missing_info, potential_blockers, "
            "validation_errors}."
        )
        user = json.dumps(
            {
                "retrieved_chunks": _scout_chunks_payload(request),
                "evidence_catalog": _catalog(request.evidence_board),
            },
            ensure_ascii=False,
            indent=2,
        )
        data = anthropic_complete_json(
            api_key=self._api_key,
            model=self._model,
            system=system,
            user=user,
            max_tokens=6_000,
        )
        data.setdefault("agent_role", AgentRole.EVIDENCE_SCOUT.value)
        return data


_ROUND1_ROLE_INSTRUCTIONS: dict[AgentRole, str] = {
    AgentRole.COMPLIANCE_OFFICER: (
        "You are the Compliance Officer. Focus on mandatory requirements, "
        "disqualification language, and submission gates. "
        "Only compliance_officer may populate formal_blockers (supported claims)."
    ),
    AgentRole.WIN_STRATEGIST: (
        "You are the Win Strategist. Focus on evaluation criteria, "
        "differentiation, and commercial win themes grounded in tender text."
    ),
    AgentRole.DELIVERY_CFO: (
        "You are Delivery/CFO. Focus on staffing, milestones, capacity, "
        "and financial/contractual delivery risk."
    ),
    AgentRole.RED_TEAM: (
        "You are Red Team. Challenge optimistic assumptions; surface residual "
        "execution and compliance exposure. Do not recommend bid without caveats "
        "unless evidence strongly supports it."
    ),
}


class AnthropicRound1Model:
    def __init__(self, *, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    def draft_motion(self, request: Round1SpecialistRequest) -> dict[str, Any]:
        role = request.agent_role
        spec = _ROUND1_ROLE_INSTRUCTIONS.get(
            role,
            "You are a specialist reviewer.",
        )
        scout = {
            "findings": [
                {"category": f.category, "claim": f.claim}
                for f in request.scout_output.findings
            ],
            "missing_info": list(request.scout_output.missing_info),
        }
        user = json.dumps(
            {
                "your_role": role.value,
                "scout_summary": scout,
                "evidence_catalog": _catalog(request.evidence_board),
            },
            ensure_ascii=False,
            indent=2,
        )
        system = (
            _BASE_RULES
            + " "
            + spec
            + (
                " Produce a Round1Motion JSON with these exact keys: "
                "agent_role (your role string), vote (bid|no_bid|conditional_bid), "
                "confidence (0.0-1.0), top_findings (array, at least 1 item required), "
                "role_specific_risks (array, at least 1 item required), "
                "formal_blockers (array — compliance_officer only, else []), "
                "potential_blockers (array), assumptions (array of strings), "
                "missing_info (array of strings), "
                "potential_evidence_gaps (array of strings), "
                "recommended_actions (array of strings), validation_errors []. "
                "Each item in top_findings/role_specific_risks/formal_blockers"
                "/potential_blockers must be: {claim: string, evidence_refs: [...]}. "
                "claim must be a non-empty string (never title/detail/description). "
                "evidence_refs: use evidence_key, source_type, evidence_id "
                "from catalog. "
                "HARD RULE — every claim in top_findings, role_specific_risks, "
                "formal_blockers, and potential_blockers MUST have at least one "
                "evidence_ref drawn from evidence_catalog. If you cannot cite a "
                "concrete evidence_ref for an item, do NOT put it in those arrays. "
                "Instead, put the plain text into potential_evidence_gaps (a list "
                "of strings) or missing_info. An empty evidence_refs array is "
                "invalid and the run will fail."
            )
        )
        data = anthropic_complete_json(
            api_key=self._api_key,
            model=self._model,
            system=system,
            user=user,
            max_tokens=8_000,
        )
        data.setdefault("agent_role", role.value)
        return data


class AnthropicRound2Model:
    def __init__(self, *, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    def draft_rebuttal(self, request: Round2RebuttalRequest) -> dict[str, Any]:
        role = request.agent_role

        motions_payload: list[dict[str, Any]] = []
        for ar, motion in request.motions.items():
            motions_payload.append(
                {
                    "agent_role": ar.value,
                    "verdict": motion.verdict.value,
                    "confidence": motion.confidence,
                    "summary": motion.summary,
                    "findings": list(motion.findings)[:12],
                    "risks": list(motion.risks)[:8],
                    "blockers": list(motion.blockers)[:8],
                }
            )

        focus = [
            {
                "kind": p.kind,
                "target_role": p.target_role.value if p.target_role else None,
                "prompt": p.prompt,
            }
            for p in request.focus_points
        ]

        user = json.dumps(
            {
                "your_role": role.value,
                "all_round_1_motions": motions_payload,
                "focus_points": focus,
                "evidence_catalog": _catalog(request.evidence_board),
            },
            ensure_ascii=False,
            indent=2,
        )

        red_extra = ""
        if role is AgentRole.RED_TEAM:
            red_extra = (
                " As Red Team you MUST set target_roles to include at least one "
                "specialist who voted bid or conditional_bid (not yourself). "
                "Challenge the strongest bid/conditional arguments."
            )

        system = (
            _BASE_RULES
            + " You are writing a focused Round 2 rebuttal after reading ALL "
            "specialists' Round 1 motions above. Reference peers by agent_role. "
            + red_extra
            + " Output Round2Rebuttal JSON with these exact keys: "
            "agent_role (your role string — one of: compliance_officer, "
            "win_strategist, "
            "delivery_cfo, red_team), "
            "target_roles (array of at least 1 peer role string — NOT yourself; valid "
            "values: compliance_officer, win_strategist, delivery_cfo, red_team), "
            "targeted_disagreements (array — each needs: target_role "
            "(peer role string), "
            "disputed_claim, rebuttal, evidence_refs), "
            "unsupported_claims (array — each needs: target_role (peer role string), "
            "claim, reason), "
            "blocker_challenges (array — each needs: blocker, "
            "position (MUST be exactly one of the strings: uphold, downgrade, reject), "
            "rationale, evidence_refs), "
            "revised_stance (exactly one of: bid, no_bid, conditional_bid, or null), "
            "confidence (0.0–1.0), evidence_refs (array), missing_info (array), "
            "potential_evidence_gaps (array), recommended_actions (array), "
            "validation_errors []. "
            "You MUST include at least one of: targeted_disagreements, "
            "unsupported_claims, blocker_challenges, or missing_info. "
            "HARD RULE — every blocker_challenge MUST have at least one "
            "evidence_ref drawn from evidence_catalog. If you cannot cite a "
            "concrete evidence_ref, drop the item from blocker_challenges "
            "entirely (or move the concern into missing_info). An empty "
            "evidence_refs array on any blocker_challenge is invalid and the "
            "run will fail."
        )
        data = anthropic_complete_json(
            api_key=self._api_key,
            model=self._model,
            system=system,
            user=user,
            max_tokens=8_000,
        )
        data.setdefault("agent_role", role.value)
        return data


class AnthropicJudgeModel:
    def __init__(self, *, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    def decide(self, request: JudgeDecisionRequest) -> dict[str, Any]:
        vote_json = request.vote_summary.model_dump()
        motions_j = [
            {
                "role": r.value,
                "verdict": m.verdict.value,
                "summary": m.summary,
            }
            for r, m in request.motions.items()
        ]
        rebuttals_j = [
            {
                "role": r.value,
                "summary": rb.summary,
                "challenged": list(rb.challenged_claims)[:16],
            }
            for r, rb in request.rebuttals.items()
        ]
        user = json.dumps(
            {
                "vote_summary_MUST_MATCH_EXACTLY": vote_json,
                "formal_compliance_blockers": [
                    c.model_dump(mode="json")
                    for c in request.formal_compliance_blockers
                ],
                "motions": motions_j,
                "rebuttals": rebuttals_j,
                "evidence_catalog": _catalog(request.evidence_board),
            },
            ensure_ascii=False,
            indent=2,
        )
        system = (
            _BASE_RULES
            + " You are the Judge. Synthesize motions and rebuttals into a final "
            "bid/no-bid recommendation. "
            "vote_summary MUST EXACTLY equal vote_summary_MUST_MATCH_EXACTLY "
            "(same bid/no_bid/conditional_bid integer counts). "
            "If verdict is conditional_bid, recommended_actions must be non-empty. "
            "If verdict is needs_human_review, missing_info must be non-empty. "
            "Output JudgeDecision JSON with these exact keys: "
            'agent_role ("judge"), '
            "verdict (bid|no_bid|conditional_bid|needs_human_review), "
            "confidence (0.0-1.0), "
            "vote_summary ({bid, no_bid, conditional_bid} — copy exactly), "
            "disagreement_summary (non-empty string), "
            "compliance_matrix (array — each: requirement, "
            "status (MUST be exactly: met|unmet|unknown — lowercase), "
            "assessment, evidence_refs), "
            "compliance_blockers (array — each: claim, evidence_refs), "
            "potential_blockers (array — each: claim, evidence_refs), "
            "risk_register (array — each: risk, "
            "severity (MUST be exactly: low|medium|high — lowercase), "
            "mitigation, evidence_refs), "
            "missing_info (array of strings), "
            "potential_evidence_gaps (array of strings), "
            "recommended_actions (array of strings), "
            "cited_memo (non-empty string summarizing the decision rationale), "
            "evidence_ids (array of UUID strings from the evidence catalog), "
            "evidence_refs (array of evidence ref objects), "
            "validation_errors []. "
            "HARD RULE — every item in compliance_blockers and "
            "potential_blockers MUST have at least one evidence_ref drawn "
            "from evidence_catalog. If you cannot cite a concrete "
            "evidence_ref for a blocker, do NOT put it in compliance_blockers "
            "or potential_blockers. Instead, put the plain text into "
            "potential_evidence_gaps or missing_info. An empty evidence_refs "
            "array on any blocker is invalid and the run will fail."
        )
        data = anthropic_complete_json(
            api_key=self._api_key,
            model=self._model,
            system=system,
            user=user,
            max_tokens=8_000,
        )
        data.setdefault("agent_role", AgentRole.JUDGE.value)
        # Enforce exact vote summary if the model drifted
        data["vote_summary"] = vote_json
        return data


def anthropic_graph_handlers(
    *,
    api_key: str,
    model: str | None = None,
) -> GraphNodeHandlers:
    """Build graph handlers that call Anthropic for each agent node."""
    from bidded.orchestration.evidence_scout import build_evidence_scout_handler
    from bidded.orchestration.judge import build_judge_handler
    from bidded.orchestration.specialist_motions import build_round_1_specialist_handler
    from bidded.orchestration.specialist_rebuttals import build_round_2_rebuttal_handler

    resolved_model = (model or "claude-sonnet-4-6").strip()
    defaults = default_graph_node_handlers()
    return replace(
        defaults,
        evidence_scout=build_evidence_scout_handler(
            AnthropicEvidenceScoutModel(api_key=api_key, model=resolved_model),
        ),
        round_1_specialist=build_round_1_specialist_handler(
            AnthropicRound1Model(api_key=api_key, model=resolved_model),
        ),
        round_2_rebuttal=build_round_2_rebuttal_handler(
            AnthropicRound2Model(api_key=api_key, model=resolved_model),
        ),
        judge=build_judge_handler(
            AnthropicJudgeModel(api_key=api_key, model=resolved_model),
        ),
    )


__all__ = [
    "AnthropicEvidenceScoutModel",
    "AnthropicJudgeModel",
    "AnthropicRound1Model",
    "AnthropicRound2Model",
    "anthropic_graph_handlers",
]
