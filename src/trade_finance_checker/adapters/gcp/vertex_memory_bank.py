"""Agent Platform Memory Bank adapter (MemoryPort) : durable officer memory.

Backs the domain ``MemoryPort`` with the GA **Agent Platform Memory Bank** service (ADK
``VertexAiMemoryBankService``) so durable facts and preferences (e.g. an officer's standing
tolerance settings) persist across cases in ``asia-southeast1``. The ADK / Agent Platform
SDK imports are lazy so the on-prem / test profile imports this module without the SDK.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ...domain.models import MemoryItem, utcnow


class VertexMemoryBankAdapter:
    """Durable officer memory via the Agent Platform Memory Bank service."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._service: Any | None = None

    def _get_service(self) -> Any:
        if self._service is None:
            from google.adk.memory import VertexAiMemoryBankService  # lazy

            self._service = VertexAiMemoryBankService(
                project=self._settings.project_id,
                # MODEL location, not the compute region.
                location=self._settings.models.location,
            )
        return self._service

    def store(self, item: MemoryItem) -> None:
        """Persist a memory item into the Memory Bank under its scope."""
        service = self._get_service()
        service.add_memory(scope=item.scope, content=item.content, memory_id=item.id)

    def search(self, query: str, scope: str = "user", top_k: int = 5) -> list[MemoryItem]:
        """Search durable memory for items matching ``query`` within ``scope``."""
        service = self._get_service()
        results = service.search_memory(query=query, scope=scope, top_k=top_k) or []
        return [
            MemoryItem(
                id=str(getattr(r, "id", "")),
                content=str(getattr(r, "content", "")),
                scope=scope,
                created_at=utcnow(),
            )
            for r in results
        ]
