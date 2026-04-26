"""Select swarm graph handlers: deterministic evidence-locked vs Anthropic Claude."""

from __future__ import annotations

from bidded.config import BiddedSettings, load_settings
from bidded.orchestration.graph import GraphNodeHandlers


def resolve_graph_handlers(settings: BiddedSettings | None = None) -> GraphNodeHandlers:
    """
    Return graph handlers for ``run_worker_once``.

    * ``bidded_swarm_backend=auto`` (default): use Anthropic when
      ``ANTHROPIC_API_KEY`` is configured, otherwise deterministic handlers.
    * ``bidded_swarm_backend=evidence_locked``: deterministic handlers
      (no API calls; reproducible). Read from ``BIDDED_SWARM_BACKEND`` in ``.env``.
    * ``bidded_swarm_backend=anthropic``: Claude via ``ANTHROPIC_API_KEY``.
      Model id: ``BIDDED_ANTHROPIC_MODEL`` (maps to ``bidded_anthropic_model``).
      ``BIDDED_ANTHROPIC_MODEL_ROUTING=mixed`` sends bounded/low-risk roles to
      the fast model and high-stakes roles to the reasoning model; ``single``
      preserves the legacy one-model behavior.

    Uses :class:`BiddedSettings` so values in ``.env`` / ``.env.local`` apply even
    when those variables are not exported into ``os.environ`` (fixes silent fallback
    to evidence-locked when only ``.env`` was edited).
    """
    s = settings or load_settings()
    backend = s.bidded_swarm_backend.strip().lower()
    if backend == "auto":
        backend = "anthropic" if s.anthropic_api_key else "evidence_locked"
    if backend == "anthropic":
        if not s.anthropic_api_key:
            msg = (
                "bidded_swarm_backend=anthropic requires ANTHROPIC_API_KEY in .env "
                "or the environment."
            )
            raise RuntimeError(msg)
        from bidded.llm.anthropic_swarm import anthropic_graph_handlers

        return anthropic_graph_handlers(
            api_key=s.anthropic_api_key,
            model=s.bidded_anthropic_model,
            fast_model=s.bidded_anthropic_fast_model,
            reasoning_model=s.bidded_anthropic_reasoning_model,
            model_routing=s.bidded_anthropic_model_routing,
        )

    from bidded.orchestration.evidence_locked_swarm import (
        evidence_locked_graph_handlers,
    )

    return evidence_locked_graph_handlers()


def load_settings_and_handlers() -> tuple[BiddedSettings, GraphNodeHandlers]:
    """Convenience for worker entrypoints."""
    s = load_settings()
    return s, resolve_graph_handlers(s)


__all__ = ["load_settings_and_handlers", "resolve_graph_handlers"]
