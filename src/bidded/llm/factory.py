"""Select swarm graph handlers: deterministic evidence-locked vs Anthropic Claude."""

from __future__ import annotations

import os

from bidded.config import BiddedSettings, load_settings
from bidded.orchestration.graph import GraphNodeHandlers


def resolve_graph_handlers(settings: BiddedSettings | None = None) -> GraphNodeHandlers:
    """
    Return graph handlers for ``run_worker_once``.

    * ``BIDDED_SWARM_BACKEND=evidence_locked`` (default): deterministic handlers
      (no API calls; reproducible).
    * ``BIDDED_SWARM_BACKEND=anthropic``: Claude via ``ANTHROPIC_API_KEY``.
      Optional ``BIDDED_ANTHROPIC_MODEL`` overrides the default model id.
    """
    s = settings or load_settings()
    backend = os.environ.get("BIDDED_SWARM_BACKEND", "evidence_locked").strip().lower()
    if backend == "anthropic":
        if not s.anthropic_api_key:
            msg = (
                "BIDDED_SWARM_BACKEND=anthropic requires ANTHROPIC_API_KEY in the "
                "environment."
            )
            raise RuntimeError(msg)
        from bidded.llm.anthropic_swarm import anthropic_graph_handlers

        return anthropic_graph_handlers(api_key=s.anthropic_api_key)

    from bidded.orchestration.evidence_locked_swarm import evidence_locked_graph_handlers

    return evidence_locked_graph_handlers()


def load_settings_and_handlers() -> tuple[BiddedSettings, GraphNodeHandlers]:
    """Convenience for worker entrypoints."""
    s = load_settings()
    return s, resolve_graph_handlers(s)


__all__ = ["load_settings_and_handlers", "resolve_graph_handlers"]
