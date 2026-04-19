from __future__ import annotations


def is_missing_requirement_type_column(exc: BaseException) -> bool:
    """Detect older Supabase schemas that predate evidence requirement_type."""
    text = str(exc).lower()
    return "requirement_type" in text and (
        "schema cache" in text
        or "column evidence_items.requirement_type does not exist" in text
        or "could not find" in text
    )


def select_without_requirement_type(columns: str) -> str:
    """Drop the optional evidence requirement_type column from a select list."""
    return ",".join(
        part.strip()
        for part in columns.split(",")
        if part.strip() and part.strip() != "requirement_type"
    )


__all__ = ["is_missing_requirement_type_column", "select_without_requirement_type"]
