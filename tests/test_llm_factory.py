"""Graph handler backend selection (evidence-locked vs Anthropic)."""

from __future__ import annotations

import pytest

from bidded.config import BiddedSettings
from bidded.llm.factory import resolve_graph_handlers
from bidded.orchestration.evidence_locked_swarm import evidence_locked_graph_handlers


def test_resolve_defaults_to_evidence_locked_without_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BIDDED_SWARM_BACKEND", raising=False)
    h = resolve_graph_handlers(
        BiddedSettings(
            anthropic_api_key=None,
            supabase_url=None,
        )
    )
    # Evidence scout is replaced vs default_graph_node_handlers
    assert h.evidence_scout is not None
    assert h.judge is not None


def test_resolve_auto_uses_anthropic_when_key_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bidded.llm import anthropic_swarm

    captured: dict[str, str | None] = {}

    def fake_anthropic_handlers(
        *,
        api_key: str,
        model: str,
        fast_model: str | None = None,
        reasoning_model: str | None = None,
        model_routing: str = "mixed",
    ):
        captured["api_key"] = api_key
        captured["model"] = model
        captured["fast_model"] = fast_model
        captured["reasoning_model"] = reasoning_model
        captured["model_routing"] = model_routing
        return evidence_locked_graph_handlers()

    monkeypatch.setattr(
        anthropic_swarm,
        "anthropic_graph_handlers",
        fake_anthropic_handlers,
    )
    h = resolve_graph_handlers(
        BiddedSettings(
            anthropic_api_key="sk-ant-test-key",
            bidded_anthropic_model="claude-sonnet-4-6",
        )
    )

    assert h.evidence_scout is not None
    assert captured == {
        "api_key": "sk-ant-test-key",
        "model": "claude-sonnet-4-6",
        "fast_model": "claude-haiku-4-5",
        "reasoning_model": "claude-sonnet-4-6",
        "model_routing": "mixed",
    }


def test_resolve_anthropic_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        resolve_graph_handlers(
            BiddedSettings(
                anthropic_api_key=None,
                bidded_swarm_backend="anthropic",
            )
        )


def test_resolve_anthropic_with_key_uses_anthropic_handlers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = BiddedSettings(
        anthropic_api_key="sk-ant-test-key",
        bidded_swarm_backend="anthropic",
    )
    h = resolve_graph_handlers(settings)
    assert h.evidence_scout is not None
    assert h.round_1_specialist is not None


def test_resolve_anthropic_passes_explicit_mixed_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bidded.llm import anthropic_swarm

    captured: dict[str, str | None] = {}

    def fake_anthropic_handlers(
        *,
        api_key: str,
        model: str,
        fast_model: str | None = None,
        reasoning_model: str | None = None,
        model_routing: str = "mixed",
    ):
        captured["api_key"] = api_key
        captured["model"] = model
        captured["fast_model"] = fast_model
        captured["reasoning_model"] = reasoning_model
        captured["model_routing"] = model_routing
        return evidence_locked_graph_handlers()

    monkeypatch.setattr(
        anthropic_swarm,
        "anthropic_graph_handlers",
        fake_anthropic_handlers,
    )

    resolve_graph_handlers(
        BiddedSettings(
            anthropic_api_key="sk-ant-test-key",
            bidded_swarm_backend="anthropic",
            bidded_anthropic_model="claude-sonnet-legacy",
            bidded_anthropic_fast_model="claude-haiku-fast",
            bidded_anthropic_reasoning_model="claude-sonnet-reasoning",
            bidded_anthropic_model_routing="mixed",
        )
    )

    assert captured == {
        "api_key": "sk-ant-test-key",
        "model": "claude-sonnet-legacy",
        "fast_model": "claude-haiku-fast",
        "reasoning_model": "claude-sonnet-reasoning",
        "model_routing": "mixed",
    }


def test_resolve_evidence_locked_even_if_key_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bidded.llm import anthropic_swarm

    def fail_anthropic_handlers(*, api_key: str, model: str):  # noqa: ARG001
        raise AssertionError("explicit evidence_locked must not call Anthropic")

    monkeypatch.setattr(
        anthropic_swarm,
        "anthropic_graph_handlers",
        fail_anthropic_handlers,
    )
    settings = BiddedSettings(
        anthropic_api_key="sk-ant-unused",
        bidded_swarm_backend="evidence_locked",
    )
    h = resolve_graph_handlers(settings)
    assert h.evidence_scout is not None
