"""Minimal Anthropic Messages API helper for JSON agent artifacts."""

from __future__ import annotations

from typing import Any

from bidded.llm.json_extract import parse_json_object


def anthropic_complete_json(
    *,
    api_key: str,
    model: str,
    system: str,
    user: str,
    max_tokens: int = 8_000,
) -> dict[str, Any]:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    parts: list[str] = []
    for block in message.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return parse_json_object("".join(parts))
