"""Extract a JSON object from model text (handles ```json fences and malformed JSON)."""

from __future__ import annotations

import json
import re
from typing import Any


def parse_json_object(text: str) -> dict[str, Any]:
    raw = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL)
    if fence:
        raw = fence.group(1)
    else:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            raw = raw[start : end + 1]

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Fallback: use json-repair for malformed LLM output (unescaped quotes,
    # trailing commas, truncated JSON, etc.)
    try:
        from json_repair import repair_json  # type: ignore[import-untyped]
        repaired = repair_json(raw, return_objects=True)
        if isinstance(repaired, dict):
            return repaired
    except Exception:
        pass

    raise ValueError(f"Could not parse JSON from model output (length {len(raw)})")
