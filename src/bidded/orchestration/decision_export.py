from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from bidded.orchestration.pending_run import DEMO_TENANT_KEY


class DecisionExportError(RuntimeError):
    """Raised when a persisted decision bundle cannot be exported."""


class SupabaseDecisionExportQuery(Protocol):
    def select(self, columns: str) -> SupabaseDecisionExportQuery: ...

    def eq(self, column: str, value: object) -> SupabaseDecisionExportQuery: ...

    def limit(self, row_limit: int) -> SupabaseDecisionExportQuery: ...

    def execute(self) -> Any: ...


class SupabaseDecisionExportClient(Protocol):
    def table(self, table_name: str) -> SupabaseDecisionExportQuery: ...


@dataclass(frozen=True)
class DecisionExportResult:
    run_id: UUID
    tenant_key: str
    verdict: str
    markdown_path: Path
    json_path: Path
    evidence_count: int
    agent_output_count: int


def export_decision_bundle(
    client: SupabaseDecisionExportClient,
    *,
    run_id: UUID | str,
    markdown_path: Path,
    json_path: Path,
    tenant_key: str = DEMO_TENANT_KEY,
) -> DecisionExportResult:
    """Write a persisted bid decision bundle as Markdown and stable JSON."""

    normalized_run_id = _normalize_uuid(run_id, "run_id")
    decision_row = _require_decision_row(
        client,
        run_id=normalized_run_id,
        tenant_key=tenant_key,
    )
    agent_outputs = _agent_output_rows(
        client,
        run_id=normalized_run_id,
        tenant_key=tenant_key,
    )
    evidence_rows = _cited_evidence_rows(
        client,
        tenant_key=tenant_key,
        decision_row=decision_row,
        agent_outputs=agent_outputs,
    )
    payload = _bundle_payload(
        run_id=normalized_run_id,
        tenant_key=tenant_key,
        decision_row=decision_row,
        agent_outputs=agent_outputs,
        evidence_rows=evidence_rows,
    )

    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(_render_markdown(payload), encoding="utf-8")
    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    return DecisionExportResult(
        run_id=normalized_run_id,
        tenant_key=tenant_key,
        verdict=str(payload["decision"]["verdict"]),
        markdown_path=markdown_path,
        json_path=json_path,
        evidence_count=len(evidence_rows),
        agent_output_count=len(agent_outputs),
    )


def _require_decision_row(
    client: SupabaseDecisionExportClient,
    *,
    run_id: UUID,
    tenant_key: str,
) -> Mapping[str, Any]:
    rows = _response_rows(
        client.table("bid_decisions")
        .select("*")
        .eq("tenant_key", tenant_key)
        .eq("agent_run_id", str(run_id))
        .limit(1)
        .execute()
    )
    if not rows:
        raise DecisionExportError(
            f"No persisted final decision for agent run {run_id}."
        )
    return rows[0]


def _agent_output_rows(
    client: SupabaseDecisionExportClient,
    *,
    run_id: UUID,
    tenant_key: str,
) -> list[Mapping[str, Any]]:
    rows = _response_rows(
        client.table("agent_outputs")
        .select("*")
        .eq("tenant_key", tenant_key)
        .eq("agent_run_id", str(run_id))
        .execute()
    )
    return sorted(rows, key=_agent_output_sort_key)


def _cited_evidence_rows(
    client: SupabaseDecisionExportClient,
    *,
    tenant_key: str,
    decision_row: Mapping[str, Any],
    agent_outputs: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    final_decision = _mapping(decision_row.get("final_decision"))
    evidence_ids = {str(value) for value in _sequence(decision_row.get("evidence_ids"))}
    evidence_keys: set[str] = set()
    _collect_evidence_identifiers(final_decision, evidence_ids, evidence_keys)
    for output in agent_outputs:
        _collect_evidence_identifiers(
            _mapping(output.get("metadata")),
            evidence_ids,
            evidence_keys,
        )
        _collect_evidence_identifiers(
            _mapping(output.get("validated_payload")),
            evidence_ids,
            evidence_keys,
        )

    rows = _response_rows(
        client.table("evidence_items")
        .select("*")
        .eq("tenant_key", tenant_key)
        .execute()
    )
    cited_rows = [
        row
        for row in rows
        if _evidence_row_is_cited(
            row, evidence_ids=evidence_ids, evidence_keys=evidence_keys
        )
    ]
    return _merge_cited_snapshot_rows(
        cited_rows,
        _decision_evidence_snapshot_rows(decision_row),
        evidence_ids=evidence_ids,
        evidence_keys=evidence_keys,
    )


def _bundle_payload(
    *,
    run_id: UUID,
    tenant_key: str,
    decision_row: Mapping[str, Any],
    agent_outputs: Sequence[Mapping[str, Any]],
    evidence_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    final_decision = _mapping(decision_row.get("final_decision"))
    decision_metadata = _mapping(decision_row.get("metadata"))
    evidence_by_id = {
        evidence_id: row
        for row in evidence_rows
        if (evidence_id := _evidence_row_id(row)) is not None
    }
    evidence_by_key = {
        str(row.get("evidence_key")): row
        for row in evidence_rows
        if row.get("evidence_key") is not None
    }
    return {
        "schema_version": "2026-04-19.v1",
        "run_id": str(run_id),
        "tenant_key": tenant_key,
        "decision": {
            "verdict": str(
                final_decision.get("verdict") or decision_row.get("verdict")
            ),
            "confidence": _float_or_none(
                final_decision.get("confidence", decision_row.get("confidence"))
            ),
            "cited_memo": str(final_decision.get("cited_memo") or ""),
            "vote_summary": dict(_mapping(final_decision.get("vote_summary"))),
            "disagreement_summary": str(
                final_decision.get("disagreement_summary") or ""
            ),
            "compliance_blockers": _claim_exports(
                final_decision.get("compliance_blockers"),
                evidence_by_id=evidence_by_id,
                evidence_by_key=evidence_by_key,
            ),
            "potential_blockers": _claim_exports(
                final_decision.get("potential_blockers"),
                evidence_by_id=evidence_by_id,
                evidence_by_key=evidence_by_key,
            ),
            "risk_register": _risk_exports(
                final_decision.get("risk_register"),
                evidence_by_id=evidence_by_id,
                evidence_by_key=evidence_by_key,
            ),
            "missing_info": sorted(
                str(item) for item in _sequence(final_decision.get("missing_info"))
            ),
            "potential_evidence_gaps": sorted(
                str(item)
                for item in _sequence(final_decision.get("potential_evidence_gaps"))
            ),
            "recommended_actions": [
                str(item)
                for item in _sequence(final_decision.get("recommended_actions"))
            ],
            "decision_evidence_audit": dict(
                _mapping(decision_metadata.get("decision_evidence_audit"))
            ),
        },
        "agent_outputs": [
            _agent_output_export(row, evidence_by_id=evidence_by_id)
            for row in agent_outputs
        ],
        "evidence": [_evidence_export(row) for row in evidence_rows],
    }


def _claim_exports(
    raw_claims: object,
    *,
    evidence_by_id: Mapping[str, Mapping[str, Any]],
    evidence_by_key: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    claims = []
    for raw_claim in _sequence(raw_claims):
        claim = _mapping(raw_claim)
        claims.append(
            {
                "claim": str(claim.get("claim") or ""),
                "evidence_keys": _evidence_keys_from_refs(
                    claim.get("evidence_refs"),
                    evidence_by_id=evidence_by_id,
                    evidence_by_key=evidence_by_key,
                ),
                "requirement_type": _optional_string(claim.get("requirement_type")),
            }
        )
    return sorted(claims, key=lambda item: item["claim"])


def _risk_exports(
    raw_risks: object,
    *,
    evidence_by_id: Mapping[str, Mapping[str, Any]],
    evidence_by_key: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    risks = []
    for raw_risk in _sequence(raw_risks):
        risk = _mapping(raw_risk)
        risks.append(
            {
                "risk": str(risk.get("risk") or ""),
                "severity": str(risk.get("severity") or ""),
                "mitigation": str(risk.get("mitigation") or ""),
                "evidence_keys": _evidence_keys_from_refs(
                    risk.get("evidence_refs"),
                    evidence_by_id=evidence_by_id,
                    evidence_by_key=evidence_by_key,
                ),
                "requirement_type": _optional_string(risk.get("requirement_type")),
            }
        )
    return sorted(risks, key=lambda item: item["risk"])


def _agent_output_export(
    row: Mapping[str, Any],
    *,
    evidence_by_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    evidence_keys: set[str] = set()
    evidence_ids: set[str] = set()
    metadata = _mapping(row.get("metadata"))
    _collect_evidence_identifiers(metadata, evidence_ids, evidence_keys)
    _collect_evidence_identifiers(
        _mapping(row.get("validated_payload")),
        evidence_ids,
        evidence_keys,
    )
    for evidence_id in evidence_ids:
        row_for_id = evidence_by_id.get(evidence_id)
        if row_for_id is not None and row_for_id.get("evidence_key") is not None:
            evidence_keys.add(str(row_for_id["evidence_key"]))
    return {
        "agent_role": str(row.get("agent_role") or ""),
        "round_name": str(row.get("round_name") or ""),
        "output_type": str(row.get("output_type") or ""),
        "evidence_keys": sorted(evidence_keys),
    }


def _evidence_export(row: Mapping[str, Any]) -> dict[str, Any]:
    source_metadata = _mapping(row.get("source_metadata"))
    return {
        "evidence_id": _evidence_row_id(row),
        "evidence_key": str(row.get("evidence_key") or ""),
        "source_type": str(row.get("source_type") or ""),
        "source_label": str(source_metadata.get("source_label") or ""),
        "excerpt": str(row.get("excerpt") or ""),
        "normalized_meaning": str(row.get("normalized_meaning") or ""),
        "requirement_type": _optional_string(row.get("requirement_type")),
        "page_start": _optional_int(row.get("page_start")),
        "page_end": _optional_int(row.get("page_end")),
        "field_path": _optional_string(row.get("field_path")),
    }


def _render_markdown(payload: Mapping[str, Any]) -> str:
    decision = _mapping(payload.get("decision"))
    lines = [
        "# Bidded Decision Bundle",
        "",
        f"Run: {payload.get('run_id')}",
        f"Tenant: {payload.get('tenant_key')}",
        f"Verdict: {decision.get('verdict')}",
        f"Confidence: {decision.get('confidence')}",
        "",
        "## Cited Memo",
        str(decision.get("cited_memo") or "None"),
        "",
    ]
    lines.extend(
        _markdown_claim_section(
            "Compliance Blockers",
            _sequence(decision.get("compliance_blockers")),
        )
    )
    lines.extend(
        _markdown_claim_section(
            "Potential Blockers",
            _sequence(decision.get("potential_blockers")),
        )
    )
    lines.extend(_markdown_risk_section(_sequence(decision.get("risk_register"))))
    lines.extend(
        _markdown_string_section(
            "Missing Information",
            _sequence(decision.get("missing_info")),
        )
    )
    lines.extend(
        _markdown_string_section(
            "Potential Evidence Gaps",
            _sequence(decision.get("potential_evidence_gaps")),
        )
    )
    lines.extend(
        _markdown_string_section(
            "Recommended Actions",
            _sequence(decision.get("recommended_actions")),
        )
    )
    lines.extend(
        _markdown_decision_evidence_audit_section(
            _mapping(decision.get("decision_evidence_audit"))
        )
    )
    lines.extend(_markdown_evidence_section(_sequence(payload.get("evidence"))))
    return "\n".join(lines).rstrip() + "\n"


def _markdown_claim_section(title: str, claims: Sequence[Any]) -> list[str]:
    lines = [f"## {title}"]
    if not claims:
        return [*lines, "- None", ""]
    for raw_claim in claims:
        claim = _mapping(raw_claim)
        evidence = _format_evidence_keys(_sequence(claim.get("evidence_keys")))
        lines.append(f"- {claim.get('claim')} Evidence: {evidence}")
    lines.append("")
    return lines


def _markdown_risk_section(risks: Sequence[Any]) -> list[str]:
    lines = ["## Risk Register"]
    if not risks:
        return [*lines, "- None", ""]
    for raw_risk in risks:
        risk = _mapping(raw_risk)
        evidence = _format_evidence_keys(_sequence(risk.get("evidence_keys")))
        lines.append(
            "- "
            f"{risk.get('severity')}: {risk.get('risk')} "
            f"Mitigation: {risk.get('mitigation')} Evidence: {evidence}"
        )
    lines.append("")
    return lines


def _markdown_string_section(title: str, items: Sequence[Any]) -> list[str]:
    lines = [f"## {title}"]
    if not items:
        return [*lines, "- None", ""]
    lines.extend(f"- {item}" for item in items)
    lines.append("")
    return lines


def _markdown_decision_evidence_audit_section(
    audit: Mapping[str, Any],
) -> list[str]:
    lines = ["## Decision Evidence Audit"]
    if not audit:
        return [*lines, "- None", ""]

    lines.extend(
        [
            f"- Gate verdict: {audit.get('gate_verdict')}",
            f"- Structural score: {audit.get('structural_score')}",
            f"- Judge confidence: {audit.get('judge_confidence')}",
            f"- Unsupported claims: {audit.get('unsupported_claim_count', 0)}",
            f"- Source unverified: {audit.get('source_unverified_count', 0)}",
            f"- Source type mismatches: {audit.get('source_type_mismatch_count', 0)}",
        ]
    )
    findings = [
        _mapping(finding)
        for finding in _sequence(audit.get("findings"))
        if _mapping(finding)
    ]
    if findings:
        lines.append("- Findings:")
        for finding in findings[:8]:
            message = str(finding.get("message") or "")
            kind = str(finding.get("kind") or "")
            evidence_keys = _format_evidence_keys(
                _sequence(finding.get("evidence_keys"))
            )
            lines.append(f"  - {kind}: {message} Evidence: {evidence_keys}")
    lines.append("")
    return lines


def _markdown_evidence_section(evidence_rows: Sequence[Any]) -> list[str]:
    lines = ["## Evidence"]
    if not evidence_rows:
        return [*lines, "- None", ""]
    for raw_row in evidence_rows:
        row = _mapping(raw_row)
        source = ", ".join(
            value
            for value in [
                str(row.get("source_type") or ""),
                str(row.get("source_label") or ""),
                _page_label(row),
                _optional_string(row.get("field_path")),
            ]
            if value
        )
        lines.append(f"- {row.get('evidence_key')} ({source}): {row.get('excerpt')}")
    lines.append("")
    return lines


def _format_evidence_keys(evidence_keys: Sequence[Any]) -> str:
    keys = [str(key) for key in evidence_keys]
    if not keys:
        return "none"
    return ", ".join(f"[{key}]" for key in keys)


def _page_label(row: Mapping[str, Any]) -> str | None:
    page_start = row.get("page_start")
    page_end = row.get("page_end")
    if page_start is None:
        return None
    if page_end is None or page_end == page_start:
        return f"page {page_start}"
    return f"pages {page_start}-{page_end}"


def _evidence_keys_from_refs(
    raw_refs: object,
    *,
    evidence_by_id: Mapping[str, Mapping[str, Any]],
    evidence_by_key: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for raw_ref in _sequence(raw_refs):
        ref = _mapping(raw_ref)
        evidence_key = ref.get("evidence_key")
        if evidence_key is not None and str(evidence_key) in evidence_by_key:
            key = str(evidence_key)
            if key not in seen:
                seen.add(key)
                keys.append(key)
            continue
        evidence_id = ref.get("evidence_id")
        if evidence_id is not None:
            row = evidence_by_id.get(str(evidence_id))
            if row is not None and row.get("evidence_key") is not None:
                key = str(row["evidence_key"])
                if key not in seen:
                    seen.add(key)
                    keys.append(key)
    return keys


def _decision_evidence_snapshot_rows(
    decision_row: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    metadata = _mapping(decision_row.get("metadata"))
    rows: list[Mapping[str, Any]] = []
    for raw_row in _sequence(metadata.get("evidence_snapshot")):
        row = _mapping(raw_row)
        if row:
            rows.append(row)
    return rows


def _merge_cited_snapshot_rows(
    live_rows: Sequence[Mapping[str, Any]],
    snapshot_rows: Sequence[Mapping[str, Any]],
    *,
    evidence_ids: set[str],
    evidence_keys: set[str],
) -> list[Mapping[str, Any]]:
    merged: list[Mapping[str, Any]] = [dict(row) for row in live_rows]
    seen_ids = {
        evidence_id
        for row in merged
        if (evidence_id := _evidence_row_id(row)) is not None
    }
    seen_keys = {
        evidence_key
        for row in merged
        if (evidence_key := _evidence_row_key(row)) is not None
    }
    for snapshot_row in snapshot_rows:
        if not _evidence_row_is_cited(
            snapshot_row,
            evidence_ids=evidence_ids,
            evidence_keys=evidence_keys,
        ):
            continue
        evidence_id = _evidence_row_id(snapshot_row)
        evidence_key = _evidence_row_key(snapshot_row)
        if evidence_id is not None and evidence_id in seen_ids:
            continue
        if evidence_key is not None and evidence_key in seen_keys:
            continue
        row = dict(snapshot_row)
        if row.get("id") is None and row.get("evidence_id") is not None:
            row["id"] = row["evidence_id"]
        merged.append(row)
        if evidence_id is not None:
            seen_ids.add(evidence_id)
        if evidence_key is not None:
            seen_keys.add(evidence_key)
    return sorted(merged, key=lambda row: str(row.get("evidence_key") or ""))


def _evidence_row_is_cited(
    row: Mapping[str, Any],
    *,
    evidence_ids: set[str],
    evidence_keys: set[str],
) -> bool:
    evidence_id = _evidence_row_id(row)
    evidence_key = _evidence_row_key(row)
    return (
        evidence_id is not None
        and evidence_id in evidence_ids
        or evidence_key is not None
        and evidence_key in evidence_keys
    )


def _evidence_row_id(row: Mapping[str, Any]) -> str | None:
    value = row.get("id", row.get("evidence_id"))
    return str(value) if value is not None else None


def _evidence_row_key(row: Mapping[str, Any]) -> str | None:
    value = row.get("evidence_key")
    return str(value) if value is not None else None


def _collect_evidence_identifiers(
    value: object,
    evidence_ids: set[str],
    evidence_keys: set[str],
) -> None:
    if isinstance(value, Mapping):
        if value.get("evidence_id") is not None:
            evidence_ids.add(str(value["evidence_id"]))
        if value.get("evidence_key") is not None:
            evidence_keys.add(str(value["evidence_key"]))
        for child in value.values():
            _collect_evidence_identifiers(child, evidence_ids, evidence_keys)
    elif isinstance(value, Sequence) and not isinstance(value, str):
        for child in value:
            _collect_evidence_identifiers(child, evidence_ids, evidence_keys)


def _agent_output_sort_key(row: Mapping[str, Any]) -> tuple[int, int, str, str, str]:
    round_name = str(row.get("round_name") or "")
    agent_role = str(row.get("agent_role") or "")
    return (
        _ROUND_ORDER.get(round_name, 99),
        _ROLE_ORDER.get(agent_role, 99),
        round_name,
        agent_role,
        str(row.get("output_type") or ""),
    )


def _response_rows(response: Any) -> list[Mapping[str, Any]]:
    data = getattr(response, "data", None)
    if not isinstance(data, list):
        raise DecisionExportError("Supabase query did not return a row list.")
    return [row for row in data if isinstance(row, Mapping)]


def _normalize_uuid(value: UUID | str, field_name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise DecisionExportError(f"{field_name} must be a UUID.") from exc


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, str) else ()


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise DecisionExportError(
            f"Expected numeric confidence, got {value!r}."
        ) from exc


def _optional_string(value: object) -> str | None:
    return str(value) if value is not None else None


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise DecisionExportError(f"Expected integer value, got {value!r}.") from exc


_ROUND_ORDER = {
    "evidence": 0,
    "round_1_motion": 1,
    "round_2_rebuttal": 2,
    "final_decision": 3,
}

_ROLE_ORDER = {
    "evidence_scout": 0,
    "compliance_officer": 1,
    "win_strategist": 2,
    "delivery_cfo": 3,
    "red_team": 4,
    "judge": 5,
}


__all__ = [
    "DecisionExportError",
    "DecisionExportResult",
    "SupabaseDecisionExportClient",
    "export_decision_bundle",
]
