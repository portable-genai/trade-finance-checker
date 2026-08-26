"""Agent Platform Sessions adapter (SessionPort) : per-case conversation state.

Backs the domain ``SessionPort`` with the GA **Agent Platform Sessions** service (ADK
``VertexAiSessionService``) so each documentary-credit case has durable, server-side
conversation state in ``asia-southeast1``. The ADK / Agent Platform SDK imports are lazy so
the on-prem / test profile imports this module without the SDK installed.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ...domain.models import LlmMessage, Session, utcnow


class VertexSessionsAdapter:
    """Per-case session state via the Agent Platform Sessions service."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._service: Any | None = None

    def _get_service(self) -> Any:
        if self._service is None:
            from google.adk.sessions import VertexAiSessionService  # lazy

            self._service = VertexAiSessionService(
                project=self._settings.project_id,
                # MODEL location, not the compute region.
                location=self._settings.models.location,
            )
        return self._service

    def create_session(self, user_id: str, case_id: str | None = None) -> Session:
        """Create a server-side session for ``user_id`` (optionally for a case)."""
        service = self._get_service()
        created = service.create_session(
            app_name=self._settings.agent_engine.display_name,
            user_id=user_id,
        )
        return Session(
            id=str(getattr(created, "id", "")),
            user_id=user_id,
            case_id=case_id,
            created_at=utcnow(),
        )

    def get(self, session_id: str) -> Session | None:
        """Resolve a session by id; ``None`` if it does not exist."""
        service = self._get_service()
        found = service.get_session(
            app_name=self._settings.agent_engine.display_name,
            session_id=session_id,
        )
        if found is None:
            return None
        return Session(id=session_id, user_id=str(getattr(found, "user_id", "")))

    def append(self, session_id: str, message: LlmMessage) -> None:
        """Append a message event to the server-side session history."""
        service = self._get_service()
        service.append_event(
            session_id=session_id, event={"role": message.role, "text": message.content}
        )

    def history(self, session_id: str) -> list[LlmMessage]:
        """Return the session's message history as domain ``LlmMessage`` objects."""
        service = self._get_service()
        found = service.get_session(
            app_name=self._settings.agent_engine.display_name,
            session_id=session_id,
        )
        events = getattr(found, "events", None) or []
        return [
            LlmMessage(role=str(getattr(e, "role", "user")), content=str(getattr(e, "text", "")))
            for e in events
        ]
