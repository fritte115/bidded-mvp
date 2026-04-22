from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from bidded.orchestration.state import EvidenceItemState

_BLANK_EVIDENCE_ID_VALUES = {"", "null", "none"}


def resolve_evidence_ref_dict_against_board(
    ref_dict: Mapping[str, Any],
    board: Sequence[EvidenceItemState],
) -> dict[str, Any]:
    """
    Canonicalize an LLM evidence ref against the evidence board.

    Claude sometimes copies the UUID correctly but slightly mutates long evidence
    keys. The evidence board remains the source of truth: if either
    ``evidence_id + source_type`` or ``evidence_key + source_type`` resolves to a
    board item, return the canonical triplet expected by strict validators.
    """

    out = dict(ref_dict)
    key = str(out.get("evidence_key") or "")
    source_type = str(out.get("source_type") or "")
    evidence_id = _present_evidence_id(out.get("evidence_id"))

    # Strategy: try every signal the LLM gave us. The LLM regularly confuses
    # evidence_key / evidence_id — copying the UUID into both fields, copying
    # the key into the id slot, or inventing a slightly-mutated key. The
    # evidence board is the source of truth; resolve to whichever board item
    # matches any of: (id), (key), (id tried as key), (key tried as id).
    if evidence_id is not None:
        id_match = _match_by_id(evidence_id, source_type=source_type, board=board)
        if id_match is not None:
            return _canonical_ref(out, id_match)

        # The LLM may have put the evidence_key into the evidence_id slot.
        id_as_key_match = _match_by_key_unique(
            evidence_id, source_type=source_type, board=board
        )
        if id_as_key_match is not None:
            return _canonical_ref(out, id_as_key_match)

    if key:
        key_match = _match_by_key_unique(key, source_type=source_type, board=board)
        if key_match is not None:
            return _canonical_ref(out, key_match)

        # The LLM may have put the UUID into the evidence_key slot.
        key_as_id_match = _match_by_id(key, source_type=source_type, board=board)
        if key_as_id_match is not None:
            return _canonical_ref(out, key_as_id_match)

    return out


def coerce_evidence_refs(
    refs: Any,
    board: Sequence[EvidenceItemState],
) -> list[dict[str, Any]]:
    """Normalize a Claude-produced ``evidence_refs`` value into canonical dicts.

    Shared across the Round 1 motion, Round 2 rebuttal, and scout coercers so
    the same LLM-drift healing rules apply everywhere. Returns a list of dicts
    shaped ``{evidence_key, source_type, evidence_id}`` — no Pydantic types —
    which the caller then feeds into ``model_validate``.

    Healing rules (in order):

    1. **Container normalization.** ``None`` → ``[]``. A bare string is treated
       as a single-item list. Anything else non-list is dropped.
    2. **Item normalization.** A string item is wrapped in a dict under
       ``evidence_key``; a dict is used as-is; anything else is dropped.
    3. **Field-swap + field-fill canonicalization.** Each ref is passed through
       :func:`resolve_evidence_ref_dict_against_board` which tries every
       signal the LLM gave: id, id-as-key, key, and key-as-id matches.
    4. **Drop unresolvables.** Refs that still don't match a board item after
       canonicalization are removed. The alternative — letting them through —
       trips ``SupportedClaim.validate_evidence_ids`` (non-null evidence_id
       required) or the post-validate board-membership check, both of which
       abort the whole run. Dropping lets the claim's remaining refs, or the
       whole motion minus this claim, carry forward.
    """
    normalized_items = _normalize_items(refs)

    canonical: list[dict[str, Any]] = []
    for item in normalized_items:
        resolved = resolve_evidence_ref_dict_against_board(item, board)
        # Drop anything still not resolvable: either the LLM invented a
        # citation or the key is ambiguous across source_types.
        if _resolves_to_board_item(resolved, board):
            canonical.append(resolved)
    return canonical


def _normalize_items(refs: Any) -> list[dict[str, Any]]:
    """Turn a (possibly malformed) LLM value into a list of ref-shaped dicts."""

    if refs is None:
        return []
    if isinstance(refs, str):
        # Bare string — treat as a single identifier. The canonicalizer will
        # try it as both evidence_key and evidence_id.
        return [{"evidence_key": refs}]
    if not isinstance(refs, list):
        return []

    items: list[dict[str, Any]] = []
    for item in refs:
        if isinstance(item, str):
            items.append({"evidence_key": item})
        elif isinstance(item, dict):
            items.append(item)
        # Silently drop anything else (None, ints, nested lists) — these
        # are pure hallucinations with no recoverable signal.
    return items


def _resolves_to_board_item(
    ref_dict: Mapping[str, Any],
    board: Sequence[EvidenceItemState],
) -> bool:
    """True iff the ref has the canonical triplet and matches a board item."""

    key = str(ref_dict.get("evidence_key") or "")
    source_type = str(ref_dict.get("source_type") or "")
    evidence_id = _present_evidence_id(ref_dict.get("evidence_id"))
    if not key or not source_type or evidence_id is None:
        return False
    return any(
        item.evidence_key == key
        and item.source_type.value == source_type
        and item.evidence_id is not None
        and str(item.evidence_id) == evidence_id
        for item in board
    )


def _present_evidence_id(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.casefold() in _BLANK_EVIDENCE_ID_VALUES:
        return None
    return text


def _match_by_id(
    evidence_id: str,
    *,
    source_type: str,
    board: Sequence[EvidenceItemState],
) -> EvidenceItemState | None:
    return next(
        (
            item
            for item in board
            if item.evidence_id is not None
            and str(item.evidence_id) == evidence_id
            and (not source_type or item.source_type.value == source_type)
        ),
        None,
    )


def _match_by_key_unique(
    evidence_key: str,
    *,
    source_type: str,
    board: Sequence[EvidenceItemState],
) -> EvidenceItemState | None:
    """Return the board item matching ``evidence_key`` iff the match is
    unambiguous. When ``source_type`` is provided it disambiguates directly.
    When ``source_type`` is blank (the LLM omitted it), we only accept a
    match if exactly one board item has that key — otherwise we refuse to
    guess which source_type the LLM meant, and the ref is dropped downstream.
    """
    matches = [
        item
        for item in board
        if item.evidence_key == evidence_key
        and (not source_type or item.source_type.value == source_type)
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def _canonical_ref(
    original: Mapping[str, Any],
    item: EvidenceItemState,
) -> dict[str, Any]:
    out = dict(original)
    out["evidence_key"] = item.evidence_key
    out["source_type"] = item.source_type.value
    if item.evidence_id is not None:
        out["evidence_id"] = str(item.evidence_id)
    return out


__all__ = [
    "coerce_evidence_refs",
    "resolve_evidence_ref_dict_against_board",
]
