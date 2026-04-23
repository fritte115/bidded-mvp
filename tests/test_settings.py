"""BiddedSettings env binding and normalization."""

from __future__ import annotations

import pytest

from bidded.config import BiddedSettings


def test_bidded_anthropic_model_remaps_known_invalid_id() -> None:
    s = BiddedSettings(bidded_anthropic_model="claude-sonnet-4-20250514")
    assert s.bidded_anthropic_model == "claude-sonnet-4-6"


def test_bidded_anthropic_model_remaps_retired_claude_35() -> None:
    s = BiddedSettings(bidded_anthropic_model="claude-3-5-sonnet-20241022")
    assert s.bidded_anthropic_model == "claude-sonnet-4-6"


def test_bidded_anthropic_model_from_env_var_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIDDED_ANTHROPIC_MODEL", "claude-sonnet-4-6")
    s = BiddedSettings()
    assert s.bidded_anthropic_model == "claude-sonnet-4-6"


def test_bidded_swarm_backend_defaults_to_auto() -> None:
    assert BiddedSettings().bidded_swarm_backend == "auto"


def test_anthropic_model_routing_defaults_to_mixed() -> None:
    s = BiddedSettings()
    assert s.bidded_anthropic_model_routing == "mixed"
    assert s.bidded_anthropic_fast_model == "claude-haiku-4-5"
    assert s.bidded_anthropic_reasoning_model == s.bidded_anthropic_model


def test_anthropic_reasoning_model_defaults_to_legacy_model() -> None:
    s = BiddedSettings(bidded_anthropic_model="claude-sonnet-custom")
    assert s.bidded_anthropic_reasoning_model == "claude-sonnet-custom"


def test_anthropic_routing_env_vars_normalize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIDDED_ANTHROPIC_MODEL_ROUTING", " SINGLE ")
    monkeypatch.setenv("BIDDED_ANTHROPIC_FAST_MODEL", " claude-haiku-custom ")
    monkeypatch.setenv("BIDDED_ANTHROPIC_REASONING_MODEL", " claude-sonnet-custom ")

    s = BiddedSettings()

    assert s.bidded_anthropic_model_routing == "single"
    assert s.bidded_anthropic_fast_model == "claude-haiku-custom"
    assert s.bidded_anthropic_reasoning_model == "claude-sonnet-custom"


def test_bidded_swarm_backend_normalizes_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIDDED_SWARM_BACKEND", " ANTHROPIC ")
    assert BiddedSettings().bidded_swarm_backend == "anthropic"


def test_anthropic_model_env_does_not_set_bidded_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy/confusing ``ANTHROPIC_MODEL`` must not override Bidded model."""
    monkeypatch.delenv("BIDDED_ANTHROPIC_MODEL", raising=False)
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
    s = BiddedSettings()
    assert s.bidded_anthropic_model == "claude-sonnet-4-6"
