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

    if evidence_id is not None:
        id_match = _match_by_id(
            evidence_id,
            source_type=source_type,
            board=board,
        )
        if id_match is not None:
            return _canonical_ref(out, id_match)
        return out

    key_match = _match_by_key(
        key,
        source_type=source_type,
        board=board,
    )
    if key_match is not None:
        return _canonical_ref(out, key_match)

    return out


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


def _match_by_key(
    evidence_key: str,
    *,
    source_type: str,
    board: Sequence[EvidenceItemState],
) -> EvidenceItemState | None:
    return next(
        (
            item
            for item in board
            if item.evidence_key == evidence_key
            and (not source_type or item.source_type.value == source_type)
        ),
        None,
    )


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


__all__ = ["resolve_evidence_ref_dict_against_board"]
