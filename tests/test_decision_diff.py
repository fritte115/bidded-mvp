from __future__ import annotations

import json
from pathlib import Path

from bidded.evals.decision_diff import (
    DecisionDiffError,
    diff_decision_payloads,
    load_persisted_run_decision_payload,
    render_decision_diff_text,
    write_decision_diff_json,
)


def test_decision_diff_ignores_prose_and_order_only_changes() -> None:
    baseline = _decision_payload(
        cited_memo="Proceed because the ISO proof and capacity evidence match.",
        blockers=[
            {
                "claim": "Named lead proof remains open before submission.",
                "evidence_keys": ["E-TENDER-LEAD"],
            },
            {
                "claim": "Liability cap needs commercial approval.",
                "evidence_keys": ["E-TENDER-LIABILITY"],
            },
        ],
        missing_info=[
            "Named security-cleared lead CV.",
            "Signed DPA attachment.",
        ],
        recommended_actions=[
            "Attach named security-cleared lead CV.",
            "Confirm liability cap before final bid approval.",
        ],
        evidence_keys=[
            "E-TENDER-LEAD",
            "E-TENDER-LIABILITY",
            "E-COMPANY-CAPACITY",
        ],
    )
    candidate = _decision_payload(
        cited_memo="Capacity evidence and ISO proof support proceeding.",
        blockers=[
            {
                "claim": "Liability cap needs commercial approval.",
                "evidence_keys": ["E-TENDER-LIABILITY"],
            },
            {
                "claim": "Named lead proof remains open before submission.",
                "evidence_keys": ["E-TENDER-LEAD"],
            },
        ],
        missing_info=[
            "Signed DPA attachment.",
            "Named security-cleared lead CV.",
        ],
        recommended_actions=[
            "Confirm liability cap before final bid approval.",
            "Attach named security-cleared lead CV.",
        ],
        evidence_keys=[
            "E-COMPANY-CAPACITY",
            "E-TENDER-LIABILITY",
            "E-TENDER-LEAD",
        ],
    )

    diff = diff_decision_payloads(baseline, candidate)

    assert not diff.has_material_changes
    assert diff.decision_diffs[0].changed_fields == ()


def test_decision_diff_reports_changed_verdict() -> None:
    baseline = _decision_payload(verdict="bid")
    candidate = _decision_payload(verdict="no_bid")

    diff = diff_decision_payloads(baseline, candidate)

    verdict_diff = diff.decision_diffs[0].fields["verdict"]
    assert diff.has_material_changes
    assert verdict_diff.changed[0].baseline == "bid"
    assert verdict_diff.changed[0].candidate == "no_bid"
    assert diff.decision_diffs[0].changed_fields == ("verdict",)


def test_decision_diff_reports_added_and_removed_blockers() -> None:
    baseline = _decision_payload(
        blockers=[
            {
                "claim": "Named lead proof remains open before submission.",
                "evidence_keys": ["E-TENDER-LEAD"],
            }
        ],
        evidence_keys=["E-TENDER-LEAD"],
    )
    candidate = _decision_payload(
        blockers=[
            {
                "claim": "Liability cap needs commercial approval.",
                "evidence_keys": ["E-TENDER-LIABILITY"],
            }
        ],
        evidence_keys=["E-TENDER-LIABILITY"],
    )

    diff = diff_decision_payloads(baseline, candidate)

    blocker_diff = diff.decision_diffs[0].fields["blockers"]
    assert diff.has_material_changes
    assert blocker_diff.added == ("Liability cap needs commercial approval.",)
    assert blocker_diff.removed == ("Named lead proof remains open before submission.",)


def test_decision_diff_reports_changed_cited_evidence_keys() -> None:
    baseline = _decision_payload(evidence_keys=["E-TENDER-LEAD"])
    candidate = _decision_payload(evidence_keys=["E-TENDER-LEAD", "E-COMPANY-ISO"])

    diff = diff_decision_payloads(baseline, candidate)

    evidence_diff = diff.decision_diffs[0].fields["cited_evidence_keys"]
    assert diff.has_material_changes
    assert evidence_diff.added == ("E-COMPANY-ISO",)
    assert evidence_diff.removed == ()


def test_decision_diff_reports_changed_risk_details_by_risk_text() -> None:
    baseline = _decision_payload(risk_severity="medium")
    candidate = _decision_payload(risk_severity="high")

    diff = diff_decision_payloads(baseline, candidate)

    risk_diff = diff.decision_diffs[0].fields["risks"]
    assert diff.has_material_changes
    assert risk_diff.added == ()
    assert risk_diff.removed == ()
    assert risk_diff.changed[0].baseline == {
        "risk": "Delay penalties may reduce delivery margin.",
        "severity": "medium",
        "mitigation": "Review liability cap and contingency staffing.",
        "evidence_keys": ("E-TENDER-LIABILITY",),
    }
    assert risk_diff.changed[0].candidate == {
        "risk": "Delay penalties may reduce delivery margin.",
        "severity": "high",
        "mitigation": "Review liability cap and contingency staffing.",
        "evidence_keys": ("E-TENDER-LIABILITY",),
    }


def test_decision_diff_writes_json_and_human_readable_text(tmp_path: Path) -> None:
    baseline = _decision_payload(verdict="bid")
    candidate = _decision_payload(verdict="no_bid")
    diff = diff_decision_payloads(
        baseline,
        candidate,
        baseline_source="baseline.json",
        candidate_source="candidate.json",
    )
    json_path = tmp_path / "decision-diff.json"

    write_decision_diff_json(diff, json_path)
    text = render_decision_diff_text(diff)

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "2026-04-19.decision-diff.v1"
    assert payload["has_material_changes"] is True
    assert payload["baseline_source"] == "baseline.json"
    assert payload["candidate_source"] == "candidate.json"
    assert payload["decision_diffs"][0]["changed_fields"] == ["verdict"]
    assert payload["decision_diffs"][0]["fields"]["verdict"]["changed"] == [
        {"baseline": "bid", "candidate": "no_bid"}
    ]
    assert "Decision diff: material changes detected." in text
    assert "baseline.json -> candidate.json" in text
    assert "CHANGED verdict: bid -> no_bid" in text


def test_decision_diff_compares_eval_result_payloads_by_case_id() -> None:
    baseline = {
        "passed": True,
        "total_count": 1,
        "passed_count": 1,
        "failed_count": 0,
        "results": [
            {
                "case_id": "obvious_bid",
                "title": "Obvious bid",
                "passed": True,
                "expected_verdict": "bid",
                "actual_verdict": "bid",
                "actual_decision": {
                    "verdict": "bid",
                    "confidence": 0.82,
                    "blockers": [],
                    "risks": [],
                    "missing_info": [],
                    "recommended_actions": ["Submit bid."],
                    "cited_evidence_keys": ["E-TENDER-ISO", "E-COMPANY-ISO"],
                },
            }
        ],
    }
    candidate = {
        **baseline,
        "results": [
            {
                **baseline["results"][0],
                "actual_decision": {
                    "verdict": "bid",
                    "confidence": 0.82,
                    "blockers": [],
                    "risks": [],
                    "missing_info": [],
                    "recommended_actions": ["Submit bid.", "Confirm staffing."],
                    "cited_evidence_keys": ["E-TENDER-ISO", "E-COMPANY-ISO"],
                },
            }
        ],
    }

    diff = diff_decision_payloads(baseline, candidate)

    assert diff.decision_diffs[0].decision_id == "obvious_bid"
    assert diff.decision_diffs[0].fields["recommended_actions"].added == (
        "Confirm staffing.",
    )


def test_decision_diff_loads_persisted_run_payload_with_evidence_keys() -> None:
    client = InMemoryDecisionDiffClient(
        {
            "bid_decisions": [
                {
                    "tenant_key": "demo",
                    "agent_run_id": "11111111-1111-4111-8111-111111111111",
                    "verdict": "conditional_bid",
                    "confidence": 0.74,
                    "evidence_ids": ["evidence-id-1"],
                    "final_decision": {
                        "potential_blockers": [
                            {
                                "claim": "Named lead proof remains open.",
                                "evidence_refs": [
                                    {
                                        "evidence_key": "E-TENDER-LEAD",
                                        "evidence_id": "evidence-id-1",
                                    }
                                ],
                            }
                        ],
                        "missing_info": ["Named lead CV."],
                        "recommended_actions": ["Attach named lead CV."],
                    },
                }
            ],
            "evidence_items": [
                {
                    "tenant_key": "demo",
                    "id": "evidence-id-1",
                    "evidence_key": "E-TENDER-LEAD",
                }
            ],
        }
    )

    payload = load_persisted_run_decision_payload(
        client,
        run_id="11111111-1111-4111-8111-111111111111",
    )
    diff = diff_decision_payloads(payload, payload)

    assert payload["decision"]["verdict"] == "conditional_bid"
    assert payload["evidence"] == [{"evidence_key": "E-TENDER-LEAD"}]
    assert not diff.has_material_changes


def test_decision_diff_rejects_payloads_without_decisions() -> None:
    try:
        diff_decision_payloads({"not": "a decision"}, {"also": "not a decision"})
    except DecisionDiffError as exc:
        assert "No decisions found" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("Expected unrecognized payloads to fail")


def _decision_payload(
    *,
    verdict: str = "conditional_bid",
    cited_memo: str = "Proceed because the evidence supports a conditional bid.",
    blockers: list[dict[str, object]] | None = None,
    missing_info: list[str] | None = None,
    recommended_actions: list[str] | None = None,
    evidence_keys: list[str] | None = None,
    risk_severity: str = "medium",
) -> dict[str, object]:
    blockers = blockers or [
        {
            "claim": "Named lead proof remains open before submission.",
            "evidence_keys": ["E-TENDER-LEAD"],
        }
    ]
    missing_info = missing_info or ["Named security-cleared lead CV."]
    recommended_actions = recommended_actions or [
        "Attach named security-cleared lead CV."
    ]
    evidence_keys = evidence_keys or ["E-TENDER-LEAD"]
    return {
        "schema_version": "2026-04-19.v1",
        "run_id": "11111111-1111-4111-8111-111111111111",
        "decision": {
            "verdict": verdict,
            "confidence": 0.74,
            "cited_memo": cited_memo,
            "compliance_blockers": [],
            "potential_blockers": blockers,
            "risk_register": [
                {
                    "risk": "Delay penalties may reduce delivery margin.",
                    "severity": risk_severity,
                    "mitigation": "Review liability cap and contingency staffing.",
                    "evidence_keys": ["E-TENDER-LIABILITY"],
                }
            ],
            "missing_info": missing_info,
            "recommended_actions": recommended_actions,
        },
        "evidence": [{"evidence_key": evidence_key} for evidence_key in evidence_keys],
    }


class InMemoryDecisionDiffClient:
    def __init__(self, rows: dict[str, list[dict[str, object]]]) -> None:
        self.rows = rows

    def table(self, table_name: str) -> InMemoryDecisionDiffQuery:
        return InMemoryDecisionDiffQuery(self.rows.get(table_name, ()))


class InMemoryDecisionDiffQuery:
    def __init__(self, rows: object) -> None:
        self.rows = [dict(row) for row in rows] if isinstance(rows, list) else []
        self.filters: list[tuple[str, str]] = []
        self.row_limit: int | None = None

    def select(self, _columns: str) -> InMemoryDecisionDiffQuery:
        return self

    def eq(self, column: str, value: object) -> InMemoryDecisionDiffQuery:
        self.filters.append((column, str(value)))
        return self

    def limit(self, row_limit: int) -> InMemoryDecisionDiffQuery:
        self.row_limit = row_limit
        return self

    def execute(self) -> object:
        rows = [
            row
            for row in self.rows
            if all(str(row.get(column)) == value for column, value in self.filters)
        ]
        if self.row_limit is not None:
            rows = rows[: self.row_limit]
        return type("Response", (), {"data": rows})()
