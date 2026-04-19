from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class ContractClauseTag:
    tag_id: str
    display_label: str
    match_patterns: tuple[str, ...]
    risk_lens: str
    suggested_proof_action: str
    blocker_review_hint: str


@dataclass(frozen=True)
class ContractClauseTagMatch:
    tag_id: str
    display_label: str
    risk_lens: str
    suggested_proof_action: str
    blocker_review_hint: str
    matched_patterns: tuple[str, ...]


CONTRACT_CLAUSE_TAGS: tuple[ContractClauseTag, ...] = (
    ContractClauseTag(
        tag_id="penalties_liquidated_damages",
        display_label="Penalties and liquidated damages",
        match_patterns=(
            "penalty",
            "penalties",
            "liquidated damages",
            "service credit",
            "vite",
            "avtalsvite",
            "förseningsvite",
        ),
        risk_lens="Check whether monetary sanctions are capped and operationally fair.",
        suggested_proof_action=(
            "Model likely service-credit exposure and confirm delivery controls."
        ),
        blocker_review_hint=(
            "Escalate uncapped or disproportionate penalties for review."
        ),
    ),
    ContractClauseTag(
        tag_id="liability_caps",
        display_label="Liability caps",
        match_patterns=(
            "liability cap",
            "limitation of liability",
            "limited liability",
            "ansvarsbegränsning",
            "ansvaret är begränsat",
            "begränsat ansvar",
        ),
        risk_lens="Check total liability exposure against deal value and insurance.",
        suggested_proof_action=(
            "Confirm proposed cap and carve-outs with legal and commercial owners."
        ),
        blocker_review_hint="Escalate unlimited or unusually high liability exposure.",
    ),
    ContractClauseTag(
        tag_id="gdpr_dpa",
        display_label="GDPR / data processing agreement",
        match_patterns=(
            "gdpr",
            "data processing agreement",
            "dpa",
            "article 28",
            "personuppgiftsbiträdesavtal",
            "dataskyddsförordningen",
            "personuppgifter",
        ),
        risk_lens=(
            "Check privacy roles, processing instructions, and audit obligations."
        ),
        suggested_proof_action=(
            "Prepare DPA review notes and standard processor security evidence."
        ),
        blocker_review_hint=(
            "Escalate non-standard privacy duties or missing DPA terms."
        ),
    ),
    ContractClauseTag(
        tag_id="subprocessors",
        display_label="Subprocessors",
        match_patterns=(
            "subprocessor",
            "sub-processors",
            "sub processor",
            "underbiträde",
            "underbiträden",
        ),
        risk_lens=(
            "Check approval, notice, and flow-down duties for data subprocessors."
        ),
        suggested_proof_action=(
            "List subprocessors and confirm customer notification obligations."
        ),
        blocker_review_hint="Escalate prior-approval or forced-localization duties.",
    ),
    ContractClauseTag(
        tag_id="confidentiality",
        display_label="Confidentiality",
        match_patterns=(
            "confidentiality",
            "confidential information",
            "non-disclosure",
            "secret information",
            "sekretess",
            "konfidentiell information",
            "tystnadsplikt",
        ),
        risk_lens=(
            "Check confidentiality scope, survival, and public-sector carve-outs."
        ),
        suggested_proof_action=(
            "Confirm NDA/process controls and exceptions for required disclosures."
        ),
        blocker_review_hint="Escalate perpetual or one-sided confidentiality duties.",
    ),
    ContractClauseTag(
        tag_id="insurance",
        display_label="Insurance",
        match_patterns=(
            "insurance",
            "professional liability insurance",
            "liability insurance",
            "försäkring",
            "ansvarsförsäkring",
            "konsultansvarsförsäkring",
        ),
        risk_lens="Check required policy types, coverage levels, and proof timing.",
        suggested_proof_action=(
            "Prepare insurance certificate and compare coverage to tender minimums."
        ),
        blocker_review_hint="Escalate coverage requirements above current policies.",
    ),
    ContractClauseTag(
        tag_id="gross_negligence_wilful_misconduct",
        display_label="Gross negligence / wilful misconduct",
        match_patterns=(
            "gross negligence",
            "wilful misconduct",
            "willful misconduct",
            "intentional misconduct",
            "grov vårdslöshet",
            "uppsåt",
            "avsiktlig försummelse",
        ),
        risk_lens="Check whether liability carve-outs are standard and bounded.",
        suggested_proof_action=(
            "Ask legal to review carve-outs from liability caps and indemnities."
        ),
        blocker_review_hint=(
            "Escalate broad carve-outs beyond gross negligence or intent."
        ),
    ),
    ContractClauseTag(
        tag_id="public_access",
        display_label="Public access",
        match_patterns=(
            "public access",
            "freedom of information",
            "public records",
            "offentlighetsprincipen",
            "allmän handling",
            "offentlig handling",
        ),
        risk_lens="Check disclosure exposure for pricing, methods, and customer data.",
        suggested_proof_action=(
            "Mark confidential bid parts and prepare public-records caveats."
        ),
        blocker_review_hint=(
            "Escalate if confidential delivery material cannot be protected."
        ),
    ),
    ContractClauseTag(
        tag_id="reporting",
        display_label="Reporting",
        match_patterns=(
            "reporting obligations",
            "monthly report",
            "quarterly report",
            "service report",
            "avtalsrapportering",
            "månadsrapport",
            "kvartalsrapport",
            "rapportera",
        ),
        risk_lens="Check reporting cadence, data availability, and delivery overhead.",
        suggested_proof_action=(
            "Confirm reporting owner, templates, and automation assumptions."
        ),
        blocker_review_hint="Escalate unusually frequent or manual reporting duties.",
    ),
    ContractClauseTag(
        tag_id="termination",
        display_label="Termination",
        match_patterns=(
            "termination",
            "terminate the agreement",
            "termination for convenience",
            "early termination",
            "uppsägning",
            "hävning",
            "säga upp avtalet",
        ),
        risk_lens="Check termination triggers, notice periods, and stranded cost risk.",
        suggested_proof_action=(
            "Confirm exit assumptions, notice requirements, and termination fees."
        ),
        blocker_review_hint=(
            "Escalate broad convenience termination without compensation."
        ),
    ),
    ContractClauseTag(
        tag_id="subcontractors",
        display_label="Subcontractors",
        match_patterns=(
            "subcontractor",
            "subcontractors",
            "subcontracting",
            "sub-consultant",
            "underleverantör",
            "underleverantörer",
            "underkonsult",
        ),
        risk_lens="Check approval, responsibility, and replacement limits.",
        suggested_proof_action=(
            "List likely subcontractors and confirm approval/change process."
        ),
        blocker_review_hint=(
            "Escalate blanket bans or impractical approval constraints."
        ),
    ),
    ContractClauseTag(
        tag_id="unknown_contract_clause",
        display_label="Unknown contract clause",
        match_patterns=(
            "other contract condition",
            "general contract terms",
            "special contract terms",
            "övriga avtalsvillkor",
            "allmänna avtalsvillkor",
            "särskilda avtalsvillkor",
        ),
        risk_lens=(
            "Check whether the clause creates material commercial or delivery risk."
        ),
        suggested_proof_action=(
            "Route the clause for human review when no specific taxonomy tag applies."
        ),
        blocker_review_hint=(
            "Escalate unclear clauses that affect price, delivery, or risk."
        ),
    ),
)


def match_contract_clause_tags(text: str) -> tuple[ContractClauseTagMatch, ...]:
    normalized_text = _normalize_for_matching(text)
    matches: list[ContractClauseTagMatch] = []
    for tag in CONTRACT_CLAUSE_TAGS:
        matched_patterns = tuple(
            pattern
            for pattern in tag.match_patterns
            if _normalize_for_matching(pattern) in normalized_text
        )
        if not matched_patterns:
            continue
        matches.append(
            ContractClauseTagMatch(
                tag_id=tag.tag_id,
                display_label=tag.display_label,
                risk_lens=tag.risk_lens,
                suggested_proof_action=tag.suggested_proof_action,
                blocker_review_hint=tag.blocker_review_hint,
                matched_patterns=matched_patterns,
            )
        )
    return tuple(matches)


def _normalize_for_matching(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_diacritics = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return re.sub(r"\s+", " ", without_diacritics).strip()


__all__ = [
    "CONTRACT_CLAUSE_TAGS",
    "ContractClauseTag",
    "ContractClauseTagMatch",
    "match_contract_clause_tags",
]
