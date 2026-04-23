from __future__ import annotations

import sys
from typing import Any

from bidded.llm.anthropic_client import anthropic_complete_json


def test_anthropic_complete_json_forwards_content_blocks(
    monkeypatch,
) -> None:
    recorded: dict[str, Any] = {}

    class _FakeMessages:
        def create(self, **kwargs: Any) -> object:
            recorded.update(kwargs)
            return type(
                "Response",
                (),
                {"content": [type("TextBlock", (), {"type": "text", "text": "{}"})()]},
            )()

    class _FakeAnthropicClient:
        def __init__(self, *, api_key: str) -> None:
            recorded["api_key"] = api_key
            self.messages = _FakeMessages()

    fake_module = type("AnthropicModule", (), {"Anthropic": _FakeAnthropicClient})
    monkeypatch.setitem(sys.modules, "anthropic", fake_module)

    user_blocks = [
        {
            "type": "text",
            "text": "{\"evidence_catalog\": []}",
            "cache_control": {"type": "ephemeral"},
        },
        {"type": "text", "text": "{\"task\": \"judge\"}"},
    ]

    anthropic_complete_json(
        api_key="sk-ant-test",
        model="claude-sonnet",
        system="base rules",
        user=user_blocks,
        max_tokens=123,
    )

    assert recorded["api_key"] == "sk-ant-test"
    assert recorded["model"] == "claude-sonnet"
    assert recorded["system"] == "base rules"
    assert recorded["max_tokens"] == 123
    assert recorded["messages"] == [{"role": "user", "content": user_blocks}]
