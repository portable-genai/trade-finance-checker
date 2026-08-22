"""Agent Runtime adapter (AgentRuntimePort) : the hosted ADK agent.

Backs the domain ``AgentRuntimePort`` with **Agent Runtime** (ex-Agent Engine), the managed
hosting surface of the Gemini Enterprise Agent Platform. A deployed ``reasoningEngine``
resource (recorded in ``settings.agent_engine.resource_name``) runs the root ADK agent; this
adapter sends a user message into a session and returns the agent's reply as a domain
:class:`DiscrepancyReport`.

All ``vertexai`` / Agent Platform SDK imports are lazy so the on-prem / test profile imports
this module without the SDK installed.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ...domain.models import (
    ComplianceVerdict,
    DiscrepancyReport,
    PresentationSummary,
    Session,
)


class AgentRuntimeAdapter:
    """Query the hosted ADK agent on Agent Runtime within a session."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._engine = settings.agent_engine
        self._remote: Any | None = None

    def _get_remote(self) -> Any:
        if self._remote is None:
            from vertexai import agent_engines  # lazy

            self._remote = agent_engines.get(self._engine.resource_name)
        return self._remote

    def query(self, session: Session, message: str) -> DiscrepancyReport:
        """Send ``message`` to the hosted agent within ``session`` and parse the reply."""
        remote = self._get_remote()
        reply = remote.query(input=message, session_id=session.id)
        narrative = str(getattr(reply, "output", reply) or "")
        return DiscrepancyReport(
            lc_number=session.case_id or "",
            documents_checked=(),
            discrepancies=(),
            verdict=ComplianceVerdict.DISCREPANT,
            summary=PresentationSummary(
                lc_number=session.case_id or "",
                currency="",
                amount=0.0,
                expiry_date="",
                latest_shipment="",
            ),
            requires_human_review=True,
            narrative=narrative,
        )

    def health(self) -> bool:
        """Liveness/readiness of the hosted agent runtime."""
        try:
            return self._get_remote() is not None
        except Exception:  # noqa: BLE001 - health must never raise
            return False
