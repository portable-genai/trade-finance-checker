"""ADK FunctionTools that expose the B4 domain service to the agent.

Each tool is a thin, side-effect-honest wrapper: it builds the
:class:`~trade_finance_checker.domain.services.TradeCheckService` from a
:class:`~trade_finance_checker.config.Container` (so every port is bound to the adapter
selected by the active profile), invokes the service, and returns a JSON-safe dict via
:func:`~trade_finance_checker.domain.serialization.to_jsonable`.

Design notes
------------
* The domain service owns orchestration (redact -> guardrail -> extract -> retrieve rules
  -> detect deterministically -> verdict -> draft -> guardrail -> audit; SPEC §5). These
  tools deliberately add **no** business logic of their own : the model decides *which*
  tool to call, the service decides *how*.
* ``google.adk`` is imported lazily inside :func:`build_function_tools` so this module
  imports cleanly under the on-prem/test profile with no ADK installed (SPEC §4). The plain
  Python tool callables are importable and unit-testable without ADK at all.
* Every callable carries a precise type-hinted signature and a docstring: ADK derives the
  tool's name, description and JSON parameter schema from them, so the wording here is part
  of the agent's contract surface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..config import Container, Settings, build_container
from ..domain.identity import Principal

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from google.adk.tools import FunctionTool


# Default actor for tool-initiated calls. The deployed Agent Runtime injects the real
# identity (via session state / request context); until then we record a stable service
# identity so every audit row has an actor.
_DEFAULT_ACTOR = "trade-finance-checker-agent"


def _container(settings: Settings | None) -> Container:
    """Build the DI container, honouring an optionally-injected ``Settings``."""
    return build_container(settings)


def _principal(actor: str) -> Principal:
    """A verified demo-bank principal for the agent's server-side calls.

    The domain service enforces object-level authorization, so the agent must pass a full
    :class:`Principal`, not a bare actor string. The tenant and entitlement principals are
    set SERVER-SIDE here (a trusted demo-bank service identity), never taken from the model;
    only the ``actor`` label flows through so the audit row names the caller. The deployed
    Agent Runtime replaces this with the real end-user assertion.
    """
    return Principal(
        subject=actor,
        principals=("group:trade-analyst", "group:trade-finance"),
        tenant="demo-bank",
        assurance="agent",
        source="agent",
    )


def _to_lc(lc: dict[str, Any]) -> Any:
    from ..domain.models import LetterOfCredit

    return LetterOfCredit(
        lc_number=str(lc.get("lc_number", "")),
        amount=float(lc.get("amount", 0.0) or 0.0),
        currency=str(lc.get("currency", "")),
        expiry_date=str(lc.get("expiry_date", "")),
        latest_shipment=str(lc.get("latest_shipment", "")),
        incoterm=str(lc.get("incoterm", "")),
        beneficiary=str(lc.get("beneficiary", "")),
        applicant=str(lc.get("applicant", "")),
        terms={str(k): str(v) for k, v in (lc.get("terms") or {}).items()},
    )


def _to_documents(documents: list[dict[str, Any]]) -> list[Any]:
    from ..domain.models import PresentedDocument, TradeDocType

    out = []
    for doc in documents or []:
        out.append(
            PresentedDocument(
                doc_type=TradeDocType(str(doc.get("doc_type", "other"))),
                fields={str(k): str(v) for k, v in (doc.get("fields") or {}).items()},
                pages=int(doc.get("pages", 1) or 1),
                document_id=str(doc.get("document_id", "")),
            )
        )
    return out


# --------------------------------------------------------------------------- #
# The tool callables (plain functions: importable & testable without ADK).
# --------------------------------------------------------------------------- #
def check_presentation(
    lc: dict[str, Any],
    documents: list[dict[str, Any]],
    actor: str = _DEFAULT_ACTOR,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Examine a presented document set against an LC and UCP600.

    Returns a cited ``DiscrepancyReport`` (verdict, discrepancies, narrative). The report
    is consequential, so it is always flagged for human review (maker-checker, P-06).

    Args:
      lc: the Letter of Credit as a dict (lc_number, amount, currency, expiry_date,
        latest_shipment, incoterm, terms).
      documents: the presented documents, each a dict (doc_type, fields, pages).
      actor: authenticated user / service identity the request is made for.

    Returns:
      A JSON-safe ``DiscrepancyReport`` dict.
    """
    from .. import api  # noqa: F401 - keep package import-safe ordering
    from ..api.deps import build_trade_check_service
    from ..domain.serialization import to_jsonable

    service = build_trade_check_service(_container(settings))
    report = service.check(_to_lc(lc), _to_documents(documents), principal=_principal(actor))
    return to_jsonable(report)


def detect_discrepancies(
    lc: dict[str, Any],
    documents: list[dict[str, Any]],
    actor: str = _DEFAULT_ACTOR,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Run the full check and return its discrepancy list.

    A convenience surface over ``check_presentation`` for callers that only want the
    discrepancies; the deterministic detector and the full safety pipeline still run.

    Args:
      lc: the Letter of Credit as a dict.
      documents: the presented documents.
      actor: authenticated user / service identity the request is made for.

    Returns:
      A JSON-safe dict with the verdict and the list of discrepancies.
    """
    from ..api.deps import build_trade_check_service
    from ..domain.serialization import to_jsonable

    service = build_trade_check_service(_container(settings))
    report = service.check(_to_lc(lc), _to_documents(documents), principal=_principal(actor))
    return {
        "verdict": to_jsonable(report.verdict),
        "discrepancies": to_jsonable(report.discrepancies),
    }


def extract_document(
    document: dict[str, Any],
    actor: str = _DEFAULT_ACTOR,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Parse a single trade document into structured fields.

    Args:
      document: the presented document as a dict (doc_type, fields, pages).
      actor: authenticated user / service identity the request is made for.

    Returns:
      A JSON-safe ``DocumentExtract`` dict.
    """
    from ..api.deps import build_trade_check_service
    from ..domain.serialization import to_jsonable

    service = build_trade_check_service(_container(settings))
    doc = _to_documents([document])[0]
    return to_jsonable(service.extract(doc, principal=_principal(actor)))


# The plain callables, in stable order, so the agent layer and tests share one list.
TOOL_FUNCTIONS = (
    check_presentation,
    detect_discrepancies,
    extract_document,
)


def build_function_tools() -> list[FunctionTool]:
    """Wrap each domain-service callable as an ADK ``FunctionTool``.

    ADK introspects each function's signature and docstring to derive the tool name,
    description and parameter JSON schema. ``google.adk`` is imported here (lazily) so the
    module is import-safe without ADK installed (SPEC §4).
    """
    from google.adk.tools import FunctionTool

    return [FunctionTool(func=fn) for fn in TOOL_FUNCTIONS]
