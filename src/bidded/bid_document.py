from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any


class BidDocumentError(RuntimeError):
    """Raised when a bid document cannot be generated."""


_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}

_ROLE_LABELS = {
    "compliance_officer": "Compliance Officer",
    "win_strategist": "Win Strategist",
    "delivery_cfo": "Delivery / CFO",
    "red_team": "Red Team",
}


def generate_bid_document(
    client: Any,
    *,
    run_id: str,
    tenant_key: str = "demo",
) -> str:
    """Assemble a Markdown bid response document from persisted agent run data."""

    decision_rows = _query_rows(
        client.table("bid_decisions")
        .select("*")
        .eq("tenant_key", tenant_key)
        .eq("agent_run_id", run_id)
        .limit(1)
        .execute()
    )
    if not decision_rows:
        raise BidDocumentError(f"No persisted decision for run {run_id}.")

    decision_row = decision_rows[0]
    final_decision = _mapping(decision_row.get("final_decision"))
    verdict = str(
        final_decision.get("verdict") or decision_row.get("verdict") or ""
    )
    if verdict not in ("bid", "conditional_bid"):
        raise BidDocumentError(
            f"Cannot generate bid document for verdict: {verdict!r}. "
            "Only 'bid' and 'conditional_bid' verdicts are supported."
        )

    run_rows = _query_rows(
        client.table("agent_runs")
        .select("tender_id,company_id")
        .eq("id", run_id)
        .limit(1)
        .execute()
    )
    if not run_rows:
        raise BidDocumentError(f"Agent run {run_id} not found.")
    run_row = run_rows[0]
    tender_id = str(run_row.get("tender_id") or "")
    company_id = str(run_row.get("company_id") or "")

    tender_rows = _query_rows(
        client.table("tenders")
        .select("title,issuing_authority,procurement_reference")
        .eq("id", tender_id)
        .limit(1)
        .execute()
    )
    tender = tender_rows[0] if tender_rows else {}
    title = str(tender.get("title") or "Untitled Procurement")
    issuing_authority = str(tender.get("issuing_authority") or "—")
    procurement_ref = str(tender.get("procurement_reference") or "—")

    bid_rows = _query_rows(
        client.table("bids")
        .select("rate_sek,margin_pct,hours_estimated,notes")
        .eq("agent_run_id", run_id)
        .limit(1)
        .execute()
    )
    bid = bid_rows[0] if bid_rows else {}

    output_rows = _query_rows(
        client.table("agent_outputs")
        .select("agent_role,round_name,validated_payload")
        .eq("tenant_key", tenant_key)
        .eq("agent_run_id", run_id)
        .execute()
    )
    motions = [
        _mapping(r.get("validated_payload"))
        for r in output_rows
        if str(r.get("round_name") or "") == "round_1_motion"
    ]

    company_rows = _query_rows(
        client.table("companies")
        .select("name,organization_number,capabilities")
        .eq("id", company_id)
        .limit(1)
        .execute()
    )
    company = company_rows[0] if company_rows else {}

    return _render(
        run_id=run_id,
        title=title,
        issuing_authority=issuing_authority,
        procurement_ref=procurement_ref,
        verdict=verdict,
        final_decision=final_decision,
        decision_row=decision_row,
        bid=bid,
        motions=motions,
        company=company,
    )


def _render(
    *,
    run_id: str,
    title: str,
    issuing_authority: str,
    procurement_ref: str,
    verdict: str,
    final_decision: Mapping[str, Any],
    decision_row: Mapping[str, Any],
    bid: Mapping[str, Any],
    motions: list[Mapping[str, Any]],
    company: Mapping[str, Any],
) -> str:
    confidence_raw = final_decision.get("confidence") or decision_row.get("confidence")
    try:
        confidence_pct = (
            round(float(confidence_raw) * 100) if confidence_raw is not None else None
        )
    except (TypeError, ValueError):
        confidence_pct = None

    vote_summary = _mapping(final_decision.get("vote_summary"))
    cited_memo = str(final_decision.get("cited_memo") or "").strip()

    company_name = str(company.get("name") or "—")
    org_number = str(company.get("organization_number") or "—")
    capabilities = _mapping(company.get("capabilities") or {})
    service_lines = capabilities.get("service_lines") or capabilities.get("areas") or []
    if isinstance(service_lines, list):
        capabilities_summary = ", ".join(str(s) for s in service_lines[:6]) or "—"
    else:
        capabilities_summary = str(service_lines) or "—"

    lines: list[str] = []

    lines += [
        f"# Bid Response: {title}",
        "",
        f"**Reference:** {procurement_ref}  ",
        f"**Issuing Authority:** {issuing_authority}  ",
        f"**Generated:** {date.today().isoformat()}",
        "",
        "---",
        "",
    ]

    lines += [
        "## Bidder Information",
        "",
        f"- **Company:** {company_name}",
        f"- **Organisation Number:** {org_number}",
        f"- **Capabilities:** {capabilities_summary}",
        "",
    ]

    verdict_label = verdict.replace("_", " ").title()
    confidence_str = (
        f" (Confidence: {confidence_pct}%)" if confidence_pct is not None else ""
    )
    vote_line = (
        f"BID {vote_summary.get('bid', 0)} / "
        f"NO-BID {vote_summary.get('no_bid', 0)} / "
        f"CONDITIONAL {vote_summary.get('conditional_bid', 0)}"
    )
    lines += [
        "## Executive Summary",
        "",
        f"**Verdict:** {verdict_label}{confidence_str}  ",
        f"**Vote summary:** {vote_line}",
        "",
    ]
    if cited_memo:
        lines += [cited_memo, ""]

    rate = bid.get("rate_sek")
    margin = bid.get("margin_pct")
    hours = bid.get("hours_estimated")
    notes = str(bid.get("notes") or "").strip()

    lines += [
        "## Pricing Proposal",
        "",
        "| Item | Value |",
        "|------|-------|",
        f"| Hourly Rate | {_fmt_sek(rate)} |",
        f"| Target Margin | {_fmt_pct(margin)} |",
        f"| Estimated Hours | {_fmt_int(hours)} h |",
        f"| Total Contract Value | {_fmt_total(rate, hours)} |",
        "",
    ]
    if notes:
        lines += [f"> {notes}", ""]

    compliance_matrix = list(_sequence(final_decision.get("compliance_matrix")))
    compliance_blockers = list(_sequence(final_decision.get("compliance_blockers")))
    lines += ["## Compliance Statement", ""]
    if compliance_matrix:
        for item in compliance_matrix:
            m = _mapping(item)
            req = str(m.get("requirement") or "")
            status = str(m.get("status") or "unknown")
            assessment = str(m.get("assessment") or "")
            icon = {"met": "✓", "unmet": "✗", "unknown": "?"}.get(status, "?")
            label = {
                "met": "", "unmet": "UNMET — ", "unknown": "UNKNOWN — "
            }.get(status, "")
            suffix = f": {assessment}" if assessment else ""
            lines.append(f"- [{icon}] {label}{req}{suffix}")
        lines.append("")
    else:
        lines += ["_No compliance matrix available._", ""]

    if compliance_blockers:
        lines += ["### Compliance Blockers", ""]
        for item in compliance_blockers:
            m = _mapping(item)
            lines.append(f"- {m.get('claim') or ''}")
        lines.append("")
    else:
        lines += ["### Compliance Blockers", "", "_None identified._", ""]

    risk_register = sorted(
        _sequence(final_decision.get("risk_register")),
        key=lambda r: _SEVERITY_ORDER.get(
            str(_mapping(r).get("severity") or "").lower(), 99
        ),
    )
    lines += ["## Risk Register", ""]
    if risk_register:
        for item in risk_register:
            r = _mapping(item)
            severity = str(r.get("severity") or "").upper()
            risk = str(r.get("risk") or "")
            mitigation = str(r.get("mitigation") or "")
            lines.append(f"**[{severity}]** {risk}")
            if mitigation:
                lines.append(f"  *Mitigation:* {mitigation}")
            lines.append("")
    else:
        lines += ["_No risks identified._", ""]

    recommended_actions = list(_sequence(final_decision.get("recommended_actions")))
    lines += ["## Recommended Actions", ""]
    if recommended_actions:
        for i, action in enumerate(recommended_actions, 1):
            lines.append(f"{i}. {action}")
        lines.append("")
    else:
        lines += ["_No actions specified._", ""]

    lines += ["## Specialist Assessment Summary", ""]
    for motion in motions:
        role = str(motion.get("agent_role") or "")
        role_label = _ROLE_LABELS.get(role, role.replace("_", " ").title())
        vote = str(motion.get("vote") or "").replace("_", " ").title()
        m_conf_raw = motion.get("confidence")
        try:
            m_conf = round(float(m_conf_raw) * 100) if m_conf_raw is not None else None
        except (TypeError, ValueError):
            m_conf = None
        conf_str = f" ({m_conf}%)" if m_conf is not None else ""
        lines += [f"### {role_label} — {vote}{conf_str}", ""]

        top_findings = list(_sequence(motion.get("top_findings")))
        if top_findings:
            lines.append("**Top findings:**")
            for f_item in top_findings:
                f_m = _mapping(f_item)
                lines.append(f"- {f_m.get('claim') or ''}")
            lines.append("")

        assumptions = list(_sequence(motion.get("assumptions")))
        if assumptions:
            lines.append("**Assumptions:**")
            for a in assumptions:
                lines.append(f"- {a}")
            lines.append("")

    if verdict == "conditional_bid":
        potential_blockers = list(_sequence(final_decision.get("potential_blockers")))
        lines += ["## Conditions", ""]
        lines.append(
            "The following conditions must be resolved before formal submission:"
        )
        lines.append("")
        if potential_blockers:
            for item in potential_blockers:
                m = _mapping(item)
                lines.append(f"- {m.get('claim') or ''}")
        else:
            lines.append(
                "_No explicit conditions listed — review recommended actions above._"
            )
        lines.append("")

    lines += [
        "---",
        f"*Generated by Bidded Agent — {run_id}*",
        "",
    ]

    return "\n".join(lines)


def _fmt_sek(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{int(value):,} SEK/h".replace(",", " ")
    except (TypeError, ValueError):
        return str(value)


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "—"
    return f"{value}%"


def _fmt_int(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{int(value):,}".replace(",", " ")
    except (TypeError, ValueError):
        return str(value)


def _fmt_total(rate: Any, hours: Any) -> str:
    if rate is None or hours is None:
        return "—"
    try:
        total = int(rate) * int(hours)
        return f"{total:,} SEK".replace(",", " ")
    except (TypeError, ValueError):
        return "—"


def _query_rows(response: Any) -> list[Mapping[str, Any]]:
    data = getattr(response, "data", None)
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, Mapping)]


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, str) else ()


__all__ = ["BidDocumentError", "generate_bid_document"]
