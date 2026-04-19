from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from pydantic import Field

from bidded.orchestration.pending_run import DEMO_TENANT_KEY
from bidded.orchestration.state import StrictStateModel


class DecisionDiffError(ValueError):
    """Raised when decision diff inputs cannot be loaded or normalized."""


class SupabaseDecisionDiffQuery(Protocol):
    def select(self, columns: str) -> SupabaseDecisionDiffQuery: ...

    def eq(self, column: str, value: object) -> SupabaseDecisionDiffQuery: ...

    def limit(self, row_limit: int) -> SupabaseDecisionDiffQuery: ...

    def execute(self) -> Any: ...


class SupabaseDecisionDiffClient(Protocol):
    def table(self, table_name: str) -> SupabaseDecisionDiffQuery: ...


class ChangedValue(StrictStateModel):
    """One scalar or keyed element whose normalized value changed."""

    baseline: object
    candidate: object


class DecisionFieldDiff(StrictStateModel):
    """Added, removed, and changed values for one normalized decision field."""

    added: tuple[object, ...] = ()
    removed: tuple[object, ...] = ()
    changed: tuple[ChangedValue, ...] = ()

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed or self.changed)


class DecisionDiff(StrictStateModel):
    """Material diff for one normalized decision."""

    decision_id: str = Field(min_length=1)
    fields: dict[str, DecisionFieldDiff] = Field(default_factory=dict)

    @property
    def has_material_changes(self) -> bool:
        return any(diff.has_changes for diff in self.fields.values())

    @property
    def changed_fields(self) -> tuple[str, ...]:
        return tuple(
            field_name
            for field_name, field_diff in self.fields.items()
            if field_diff.has_changes
        )


class DecisionDiffReport(StrictStateModel):
    """Top-level normalized decision diff report."""

    schema_version: str = "2026-04-19.decision-diff.v1"
    baseline_source: str = "baseline"
    candidate_source: str = "candidate"
    decision_diffs: tuple[DecisionDiff, ...]

    @property
    def has_material_changes(self) -> bool:
        return any(diff.has_material_changes for diff in self.decision_diffs)


class NormalizedDecision(StrictStateModel):
    """Stable subset of a decision used for material comparisons."""

    decision_id: str = Field(min_length=1)
    verdict: str | None = None
    confidence: float | None = None
    blockers: tuple[str, ...] = ()
    risks: tuple[dict[str, object], ...] = ()
    missing_info: tuple[str, ...] = ()
    recommended_actions: tuple[str, ...] = ()
    cited_evidence_keys: tuple[str, ...] = ()


def diff_decision_payloads(
    baseline_payload: Mapping[str, Any],
    candidate_payload: Mapping[str, Any],
    *,
    baseline_source: str = "baseline",
    candidate_source: str = "candidate",
) -> DecisionDiffReport:
    """Compare two JSON-compatible decision or eval payloads."""

    baseline_decisions = _normalized_decisions_from_payload(baseline_payload)
    candidate_decisions = _normalized_decisions_from_payload(candidate_payload)
    if not baseline_decisions or not candidate_decisions:
        raise DecisionDiffError(
            "No decisions found in baseline or candidate payload."
        )
    return _diff_decisions(
        baseline_decisions,
        candidate_decisions,
        baseline_source=baseline_source,
        candidate_source=candidate_source,
    )


def load_persisted_run_decision_payload(
    client: SupabaseDecisionDiffClient,
    *,
    run_id: str,
    tenant_key: str = DEMO_TENANT_KEY,
) -> dict[str, Any]:
    """Load the normalized comparable payload for one persisted run decision."""

    decision_rows = _response_rows(
        client.table("bid_decisions")
        .select("*")
        .eq("tenant_key", tenant_key)
        .eq("agent_run_id", run_id)
        .limit(1)
        .execute()
    )
    if not decision_rows:
        raise DecisionDiffError(f"No persisted final decision for agent run {run_id}.")

    decision_row = decision_rows[0]
    final_decision = _mapping(decision_row.get("final_decision"))
    evidence_ids = {
        str(value)
        for value in _sequence(decision_row.get("evidence_ids"))
        if value is not None
    }
    _collect_evidence_ids(final_decision, evidence_ids)
    evidence_keys: list[str] = []
    _collect_evidence_keys(final_decision, evidence_keys)
    evidence_keys.extend(
        _evidence_keys_for_ids(
            client,
            tenant_key=tenant_key,
            evidence_ids=evidence_ids,
        )
    )

    return {
        "schema_version": "2026-04-19.persisted-run-decision.v1",
        "run_id": run_id,
        "decision": {
            "verdict": final_decision.get("verdict") or decision_row.get("verdict"),
            "confidence": final_decision.get(
                "confidence",
                decision_row.get("confidence"),
            ),
            "compliance_blockers": final_decision.get("compliance_blockers") or [],
            "potential_blockers": final_decision.get("potential_blockers") or [],
            "risk_register": final_decision.get("risk_register") or [],
            "missing_info": final_decision.get("missing_info") or [],
            "recommended_actions": final_decision.get("recommended_actions") or [],
        },
        "evidence": [
            {"evidence_key": evidence_key}
            for evidence_key in _normalized_strings(evidence_keys)
        ],
    }


def decision_diff_json_payload(report: DecisionDiffReport) -> dict[str, Any]:
    """Return the stable JSON-compatible representation of a diff report."""

    return {
        "schema_version": report.schema_version,
        "has_material_changes": report.has_material_changes,
        "baseline_source": report.baseline_source,
        "candidate_source": report.candidate_source,
        "decision_diffs": [
            {
                "decision_id": decision_diff.decision_id,
                "has_material_changes": decision_diff.has_material_changes,
                "changed_fields": list(decision_diff.changed_fields),
                "fields": {
                    field_name: {
                        "added": list(field_diff.added),
                        "removed": list(field_diff.removed),
                        "changed": [
                            changed.model_dump(mode="json")
                            for changed in field_diff.changed
                        ],
                    }
                    for field_name, field_diff in decision_diff.fields.items()
                    if field_diff.has_changes
                },
            }
            for decision_diff in report.decision_diffs
        ],
    }


def write_decision_diff_json(report: DecisionDiffReport, path: Path) -> None:
    """Write a deterministic JSON representation of a decision diff."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(decision_diff_json_payload(report), indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def render_decision_diff_text(report: DecisionDiffReport) -> str:
    """Render a concise human-readable decision diff."""

    status = (
        "material changes detected"
        if report.has_material_changes
        else "no material changes"
    )
    lines = [
        f"Decision diff: {status}.",
        f"Sources: {report.baseline_source} -> {report.candidate_source}",
    ]
    for decision_diff in report.decision_diffs:
        if not decision_diff.has_material_changes:
            lines.append(f"PASS {decision_diff.decision_id}: no material changes")
            continue

        lines.append(f"DIFF {decision_diff.decision_id}")
        for field_name, field_diff in decision_diff.fields.items():
            if not field_diff.has_changes:
                continue
            for changed in field_diff.changed:
                lines.append(
                    "  CHANGED "
                    f"{field_name}: {_format_value(changed.baseline)} -> "
                    f"{_format_value(changed.candidate)}"
                )
            for value in field_diff.added:
                lines.append(f"  ADDED {field_name}: {_format_value(value)}")
            for value in field_diff.removed:
                lines.append(f"  REMOVED {field_name}: {_format_value(value)}")
    return "\n".join(lines) + "\n"


def _diff_decisions(
    baseline_decisions: Sequence[NormalizedDecision],
    candidate_decisions: Sequence[NormalizedDecision],
    *,
    baseline_source: str,
    candidate_source: str,
) -> DecisionDiffReport:
    baseline_by_id = {
        decision.decision_id: decision for decision in baseline_decisions
    }
    candidate_by_id = {
        decision.decision_id: decision for decision in candidate_decisions
    }
    decision_ids = tuple(
        sorted(set(baseline_by_id) | set(candidate_by_id))
    )
    return DecisionDiffReport(
        baseline_source=baseline_source,
        candidate_source=candidate_source,
        decision_diffs=tuple(
            _diff_one_decision(
                decision_id,
                baseline_by_id.get(decision_id),
                candidate_by_id.get(decision_id),
            )
            for decision_id in decision_ids
        ),
    )


def _diff_one_decision(
    decision_id: str,
    baseline: NormalizedDecision | None,
    candidate: NormalizedDecision | None,
) -> DecisionDiff:
    if baseline is None:
        return DecisionDiff(
            decision_id=decision_id,
            fields={
                "decision": DecisionFieldDiff(
                    added=(candidate.model_dump(mode="json"),)
                    if candidate is not None
                    else ()
                )
            },
        )
    if candidate is None:
        return DecisionDiff(
            decision_id=decision_id,
            fields={
                "decision": DecisionFieldDiff(
                    removed=(baseline.model_dump(mode="json"),)
                )
            },
        )

    fields = {
        "verdict": _scalar_diff(baseline.verdict, candidate.verdict),
        "confidence": _scalar_diff(baseline.confidence, candidate.confidence),
        "blockers": _tuple_diff(baseline.blockers, candidate.blockers),
        "risks": _keyed_mapping_diff(
            baseline.risks,
            candidate.risks,
            key_field="risk",
        ),
        "missing_info": _tuple_diff(baseline.missing_info, candidate.missing_info),
        "recommended_actions": _tuple_diff(
            baseline.recommended_actions,
            candidate.recommended_actions,
        ),
        "cited_evidence_keys": _tuple_diff(
            baseline.cited_evidence_keys,
            candidate.cited_evidence_keys,
        ),
    }
    return DecisionDiff(decision_id=decision_id, fields=fields)


def _scalar_diff(baseline: object, candidate: object) -> DecisionFieldDiff:
    if baseline == candidate:
        return DecisionFieldDiff()
    return DecisionFieldDiff(
        changed=(ChangedValue(baseline=baseline, candidate=candidate),)
    )


def _tuple_diff(
    baseline_values: Sequence[object],
    candidate_values: Sequence[object],
) -> DecisionFieldDiff:
    baseline = {_stable_key(value): value for value in baseline_values}
    candidate = {_stable_key(value): value for value in candidate_values}
    return DecisionFieldDiff(
        added=tuple(candidate[key] for key in sorted(set(candidate) - set(baseline))),
        removed=tuple(baseline[key] for key in sorted(set(baseline) - set(candidate))),
    )


def _keyed_mapping_diff(
    baseline_values: Sequence[Mapping[str, object]],
    candidate_values: Sequence[Mapping[str, object]],
    *,
    key_field: str,
) -> DecisionFieldDiff:
    baseline = {
        str(value.get(key_field) or _stable_key(value)): value
        for value in baseline_values
    }
    candidate = {
        str(value.get(key_field) or _stable_key(value)): value
        for value in candidate_values
    }
    changed = tuple(
        ChangedValue(baseline=baseline[key], candidate=candidate[key])
        for key in sorted(set(baseline) & set(candidate))
        if baseline[key] != candidate[key]
    )
    return DecisionFieldDiff(
        added=tuple(candidate[key] for key in sorted(set(candidate) - set(baseline))),
        removed=tuple(baseline[key] for key in sorted(set(baseline) - set(candidate))),
        changed=changed,
    )


def _normalized_decisions_from_payload(
    payload: Mapping[str, Any],
) -> tuple[NormalizedDecision, ...]:
    if isinstance(payload.get("decision"), Mapping):
        return (_normalized_decision_bundle(payload),)
    if isinstance(payload.get("results"), Sequence):
        return tuple(
            _normalized_eval_result(raw_result)
            for raw_result in _sequence(payload.get("results"))
            if isinstance(raw_result, Mapping)
        )
    return ()


def _normalized_decision_bundle(payload: Mapping[str, Any]) -> NormalizedDecision:
    decision = _mapping(payload.get("decision"))
    return _normalized_decision_mapping(
        str(payload.get("run_id") or "decision"),
        decision,
        fallback_evidence_keys=_evidence_keys_from_exported_rows(
            payload.get("evidence")
        ),
    )


def _normalized_eval_result(result: Mapping[str, Any]) -> NormalizedDecision:
    actual_decision = _mapping(result.get("actual_decision"))
    if not actual_decision:
        actual_decision = {"verdict": result.get("actual_verdict")}
    return _normalized_decision_mapping(
        str(result.get("case_id") or "case"),
        actual_decision,
    )


def _normalized_decision_mapping(
    decision_id: str,
    decision: Mapping[str, Any],
    *,
    fallback_evidence_keys: Sequence[str] = (),
) -> NormalizedDecision:
    return NormalizedDecision(
        decision_id=decision_id,
        verdict=_optional_string(decision.get("verdict")),
        confidence=_optional_float(decision.get("confidence")),
        blockers=_normalized_strings(
            [
                *_sequence(decision.get("blockers")),
                *_claims(decision.get("compliance_blockers")),
                *_claims(decision.get("potential_blockers")),
            ]
        ),
        risks=_normalized_risks(
            decision.get("risks") or decision.get("risk_register")
        ),
        missing_info=_normalized_strings(_sequence(decision.get("missing_info"))),
        recommended_actions=_normalized_strings(
            _sequence(decision.get("recommended_actions"))
        ),
        cited_evidence_keys=_normalized_strings(
            [
                *_evidence_keys_from_decision(decision),
                *fallback_evidence_keys,
            ]
        ),
    )


def _claims(raw_claims: object) -> tuple[str, ...]:
    claims: list[str] = []
    for raw_claim in _sequence(raw_claims):
        if isinstance(raw_claim, str):
            claims.append(raw_claim)
            continue
        claim = _mapping(raw_claim)
        if claim.get("claim") is not None:
            claims.append(str(claim["claim"]))
    return tuple(claims)


def _normalized_risks(raw_risks: object) -> tuple[dict[str, object], ...]:
    risks: list[dict[str, object]] = []
    for raw_risk in _sequence(raw_risks):
        if isinstance(raw_risk, str):
            risks.append({"risk": _normalize_text(raw_risk)})
            continue
        risk = _mapping(raw_risk)
        risk_text = _normalize_text(str(risk.get("risk") or ""))
        if not risk_text:
            continue
        risks.append(
            {
                "risk": risk_text,
                "severity": _normalize_text(str(risk.get("severity") or "")),
                "mitigation": _normalize_text(str(risk.get("mitigation") or "")),
                "evidence_keys": _normalized_strings(risk.get("evidence_keys")),
            }
        )
    return tuple(sorted(risks, key=_stable_key))


def _evidence_keys_from_decision(decision: Mapping[str, Any]) -> tuple[str, ...]:
    keys: list[str] = []
    for field_name in (
        "evidence_keys",
        "evidence_ids",
        "evidence_refs",
        "compliance_blockers",
        "potential_blockers",
        "risk_register",
        "recommended_actions",
    ):
        _collect_evidence_keys(decision.get(field_name), keys)
    return tuple(keys)


def _evidence_keys_from_exported_rows(raw_rows: object) -> tuple[str, ...]:
    keys: list[str] = []
    for row in _sequence(raw_rows):
        evidence_key = _mapping(row).get("evidence_key")
        if evidence_key is not None:
            keys.append(str(evidence_key))
    return tuple(keys)


def _collect_evidence_keys(value: object, keys: list[str]) -> None:
    if isinstance(value, Mapping):
        if value.get("evidence_key") is not None:
            keys.append(str(value["evidence_key"]))
        if value.get("evidence_keys") is not None:
            keys.extend(str(key) for key in _sequence(value["evidence_keys"]))
        for child in value.values():
            _collect_evidence_keys(child, keys)
    elif isinstance(value, Sequence) and not isinstance(value, str):
        for child in value:
            _collect_evidence_keys(child, keys)


def _collect_evidence_ids(value: object, evidence_ids: set[str]) -> None:
    if isinstance(value, Mapping):
        if value.get("evidence_id") is not None:
            evidence_ids.add(str(value["evidence_id"]))
        if value.get("evidence_ids") is not None:
            evidence_ids.update(str(item) for item in _sequence(value["evidence_ids"]))
        for child in value.values():
            _collect_evidence_ids(child, evidence_ids)
    elif isinstance(value, Sequence) and not isinstance(value, str):
        for child in value:
            _collect_evidence_ids(child, evidence_ids)


def _evidence_keys_for_ids(
    client: SupabaseDecisionDiffClient,
    *,
    tenant_key: str,
    evidence_ids: set[str],
) -> tuple[str, ...]:
    if not evidence_ids:
        return ()
    rows = _response_rows(
        client.table("evidence_items")
        .select("id,evidence_key")
        .eq("tenant_key", tenant_key)
        .execute()
    )
    return tuple(
        str(row["evidence_key"])
        for row in rows
        if row.get("id") is not None
        and str(row["id"]) in evidence_ids
        and row.get("evidence_key") is not None
    )


def _response_rows(response: Any) -> list[Mapping[str, Any]]:
    data = getattr(response, "data", None)
    if not isinstance(data, list):
        raise DecisionDiffError("Supabase query did not return a row list.")
    return [row for row in data if isinstance(row, Mapping)]


def _normalized_strings(values: object) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                normalized
                for value in _sequence(values)
                if (normalized := _normalize_text(str(value)))
            }
        )
    )


def _normalize_text(value: str) -> str:
    return " ".join(value.split())


def _stable_key(value: object) -> str:
    if isinstance(value, Mapping):
        return "|".join(
            f"{key}={_stable_key(value[key])}"
            for key in sorted(value)
        )
    if isinstance(value, Sequence) and not isinstance(value, str):
        return ",".join(_stable_key(child) for child in value)
    return str(value)


def _format_value(value: object) -> str:
    if isinstance(value, Mapping):
        return json.dumps(value, sort_keys=True)
    if isinstance(value, Sequence) and not isinstance(value, str):
        return ", ".join(_format_value(child) for child in value)
    return str(value)


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, str) else ()


def _optional_string(value: object) -> str | None:
    return str(value) if value is not None else None


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)
