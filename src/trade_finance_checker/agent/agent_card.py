"""A2A AgentCard for the B4 Trade-Finance Document Checker (A3 Registry & Governance).

This builds the checker's discovery card : the same minimal A2A shape the
``agent-registry`` service stores and serves (SPEC §6). It is published at
``/.well-known/agent-card.json``; :func:`agent_card_document` returns the JSON-safe body
the API layer serves there.

The card advertises the three skills B4 produces (check a presentation, detect
discrepancies, extract a document), mirroring the ADK FunctionTools so a peer agent or the
registry sees one consistent capability surface.

This module is pure (domain models only) and imports without ADK or any Google Cloud SDK
installed (SPEC §4).
"""

from __future__ import annotations

from typing import Any

from ..config import Settings
from ..domain.models import AgentCard, AgentSkill

# Skill ids are the stable, machine-facing capability names; they intentionally match the
# FunctionTool callables in ``agent.tools`` so the card and the tool surface stay in lockstep.
SKILLS: tuple[AgentSkill, ...] = (
    AgentSkill(
        id="check_presentation",
        name="Check a documentary-credit presentation",
        description=(
            "Examine a presented document set (invoice, bill of lading, insurance, "
            "packing list, certificate of origin, draft) against the Letter of Credit "
            "terms and UCP600, returning a cited DiscrepancyReport with a deterministic "
            "verdict and a maker-checker review flag."
        ),
    ),
    AgentSkill(
        id="detect_discrepancies",
        name="Detect discrepancies",
        description=(
            "Run the deterministic discrepancy detector over an LC and a document set and "
            "return each discrepancy with its UCP600 article, severity and citations."
        ),
    ),
    AgentSkill(
        id="extract_document",
        name="Extract a trade document",
        description=(
            "Parse a single trade document into structured fields (amount, currency, "
            "shipment date, goods description) for traceability."
        ),
    ),
)

_DESCRIPTION = (
    "Trade-finance document checker for Transaction Banking. Parses a Letter of Credit "
    "and the presented document set and detects discrepancies against the LC terms and "
    "the UCP600 rules, with each discrepancy cited to a UCP600 article / LC term. "
    "Decision support for a trade-finance officer, not an approval. Built "
    "ports-and-adapters on the Gemini Enterprise Agent Platform (Document AI extraction, "
    "A2 governed UCP600 rules, Agent Runtime hosting)."
)


def build_agent_card(settings: Settings) -> AgentCard:
    """Construct the A2A :class:`AgentCard` for this checker.

    The card ``url`` is derived from the deployed Agent Runtime resource name when
    available, otherwise a stable logical endpoint; operators override it via the public
    ingress when serving ``/.well-known/agent-card.json``.
    """
    base_url = _resolve_url(settings)
    return AgentCard(
        name="trade-finance-checker",
        description=_DESCRIPTION,
        url=base_url,
        version="0.1.0",
        skills=SKILLS,
        provider="trade-finance-checker",
    )


def agent_card_document(settings: Settings) -> dict[str, Any]:
    """Return the JSON-safe body to serve at ``/.well-known/agent-card.json``.

    Uses :func:`~trade_finance_checker.domain.serialization.to_jsonable` so enums and
    dataclasses become plain JSON (matching the SPEC §6 AgentCard shape).
    """
    from ..domain.serialization import to_jsonable

    return to_jsonable(build_agent_card(settings))


def _resolve_url(settings: Settings) -> str:
    """Best-effort public URL for the card, region-pinned to asia-southeast1."""
    resource = settings.agent_engine.resource_name
    if resource:
        # Logical reasoningEngine endpoint on the Agent Platform API host.
        return f"https://aiplatform.googleapis.com/v1/{resource}"
    return "https://trade-finance-checker.doc.internal/a2a"
