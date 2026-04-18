"""Graph handler backend selection (evidence-locked vs Anthropic)."""

from __future__ import annotations

import os

import pytest

from bidded.config import BiddedSettings
from bidded.llm.factory import resolve_graph_handlers


def test_resolve_defaults_to_evidence_locked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BIDDED_SWARM_BACKEND", raising=False)
    h = resolve_graph_handlers(
        BiddedSettings(anthropic_api_key=None, supabase_url=None)
    )
    # Evidence scout is replaced vs default_graph_node_handlers
    assert h.evidence_scout is not None
    assert h.judge is not None


def test_resolve_anthropic_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BIDDED_SWARM_BACKEND", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        resolve_graph_handlers(BiddedSettings(anthropic_api_key=None))


def test_resolve_anthropic_with_key_uses_anthropic_handlers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIDDED_SWARM_BACKEND", "anthropic")
    settings = BiddedSettings(anthropic_api_key="sk-ant-test-key")
    h = resolve_graph_handlers(settings)
    assert h.evidence_scout is not None
    assert h.round_1_specialist is not None


def test_resolve_evidence_locked_even_if_key_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BIDDED_SWARM_BACKEND", raising=False)
    settings = BiddedSettings(anthropic_api_key="sk-ant-unused")
    h = resolve_graph_handlers(settings)
    assert h.evidence_scout is not None
