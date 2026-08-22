"""MCP tool-catalog adapter (ToolCatalogPort) : the governed, least-privilege tools.

Backs the domain ``ToolCatalogPort`` with the governed Model Context Protocol (MCP) tool
catalog B4 exposes (R5 / P-03). The catalog advertises exactly the three skills B4 produces
(check a presentation, detect discrepancies, extract a document) with their input schemas,
so a peer agent or the registry sees a least-privilege capability surface : no tool beyond
what the checker actually offers.

The catalog is declared in code (no network needed to enumerate it); when a live MCP server
is wired up, ``McpToolset`` from the ADK would surface these same specs. The ADK / MCP
imports needed to *serve* the catalog live in the agent layer and are lazy there, so this
adapter imports cleanly with no SDK installed.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import ToolSpec

_TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="check_presentation",
        description="Examine a presented document set against an LC and UCP600.",
        input_schema={
            "type": "object",
            "properties": {
                "lc": {"type": "object"},
                "documents": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["lc", "documents"],
        },
    ),
    ToolSpec(
        name="detect_discrepancies",
        description="Run the deterministic discrepancy detector over a presentation.",
        input_schema={
            "type": "object",
            "properties": {
                "lc": {"type": "object"},
                "documents": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["lc", "documents"],
        },
    ),
    ToolSpec(
        name="extract_document",
        description="Parse a single trade document into structured fields.",
        input_schema={
            "type": "object",
            "properties": {"document": {"type": "object"}},
            "required": ["document"],
        },
    ),
)


class McpToolCatalogAdapter:
    """Governed MCP tool catalog for the standalone (gcp) profile."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._tools = {tool.name: tool for tool in _TOOLS}

    def list_tools(self) -> list[ToolSpec]:
        """List the governed, least-privilege tools B4 exposes."""
        return list(self._tools.values())

    def get_tool(self, name: str) -> ToolSpec | None:
        """Resolve one tool spec by name; ``None`` if not in the catalog."""
        return self._tools.get(name)
