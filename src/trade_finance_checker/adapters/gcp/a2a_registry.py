"""A2A registry adapter (AgentRegistryPort) : local AgentCard publication.

Backs the domain ``AgentRegistryPort`` for the standalone ``gcp`` profile by serving B4's
own A2A AgentCard from ``/.well-known/agent-card.json`` (built by ``agent.agent_card``) and
keeping a small in-process registry of cards. When deployed inside the full platform the
``platform`` profile swaps this for :class:`RemoteRegistryAdapter`, which delegates to the
shared ``agent-registry`` service (R2 / R6).

This adapter has no Google Cloud SDK dependency : it is pure-Python card storage : but
lives under ``adapters/gcp`` because it is the adapter used by the managed standalone
profile. Construction is the standard ``__init__(self, settings)``.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import AgentCard


class A2ARegistryAdapter:
    """In-process A2A AgentCard registry for the standalone (gcp) profile."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._cards: dict[str, AgentCard] = {}

    def register(self, card: AgentCard) -> None:
        """Publish (or upsert) this agent's card locally."""
        self._cards[card.name] = card

    def get(self, name: str) -> AgentCard | None:
        """Resolve a single agent card by name; ``None`` if not registered."""
        return self._cards.get(name)

    def list(self) -> list[AgentCard]:
        """List every locally-registered agent card."""
        return list(self._cards.values())
