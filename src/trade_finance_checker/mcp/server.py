"""Serve the governed tool catalog Fin2 already declares, over MCP 2026-07-28.

The catalog declared three governed tools and served none of them: there was no MCP server
process anywhere in the fleet. This supplies the callables that answer the existing catalog and
declares nothing new. `hex_service_kit.mcpserve.bind` refuses a mismatch in either direction at
start-up.

Unlike most trees here the inputs are self-contained: the letter of credit and the presented
documents arrive in the call rather than being resolved from a store, so no lookup is invented.

`check_presentation` and `detect_discrepancies` are the same computation. The service produces
one `DiscrepancyReport`, and a UCP 600 check IS the discrepancy detection: the catalog declares
both names, so both are answered from that one call rather than by inventing a second checking
path that could disagree with the first.

MCP stdio verifies no end user, so the principal below is a SERVICE caller carrying no
entitlements and no tenant.
"""

from __future__ import annotations

from typing import Any

from hex_service_kit import mcpserve
from hex_service_kit.identity import Principal

from ..api import deps
from ..domain.models import LetterOfCredit, PresentedDocument, TradeDocType

#: The tools this module answers, as data, so a test can hold it against the catalog.
HANDLER_NAMES: tuple[str, ...] = (
    "check_presentation",
    "detect_discrepancies",
    "extract_document",
)


def _lc(raw: Any) -> LetterOfCredit:
    data = raw if isinstance(raw, dict) else {}
    terms = data.get("terms")
    return LetterOfCredit(
        lc_number=str(data.get("lc_number", "") or ""),
        amount=float(data.get("amount") or 0.0),
        currency=str(data.get("currency", "") or ""),
        expiry_date=str(data.get("expiry_date", "") or ""),
        latest_shipment=str(data.get("latest_shipment", "") or ""),
        incoterm=str(data.get("incoterm", "") or ""),
        beneficiary=str(data.get("beneficiary", "") or ""),
        applicant=str(data.get("applicant", "") or ""),
        terms={str(k): str(v) for k, v in terms.items()} if isinstance(terms, dict) else {},
    )


def _document(raw: Any) -> PresentedDocument:
    data = raw if isinstance(raw, dict) else {}
    fields = data.get("fields")
    try:
        doc_type = TradeDocType(str(data.get("doc_type", "")))
    except ValueError:
        # An unrecognised document type is data the caller sent, not a crash: the checker
        # reports it as a discrepancy rather than the transport refusing the whole call.
        doc_type = TradeDocType(next(iter(TradeDocType)).value)
    return PresentedDocument(
        doc_type=doc_type,
        fields={str(k): str(v) for k, v in fields.items()} if isinstance(fields, dict) else {},
        pages=int(data.get("pages") or 1),
        document_id=str(data.get("document_id", "") or ""),
    )


def build_handlers(actor: str) -> dict[str, mcpserve.Handler]:
    """Bind each declared tool to the check service that already performs it."""
    principal = Principal(subject=actor, principals=(), tenant="", source="mcp")

    def _check(arguments: dict[str, Any]) -> Any:
        documents = [_document(d) for d in (arguments.get("documents") or ())]
        return deps.get_trade_check_service().check(_lc(arguments.get("lc")), documents, principal)

    def check_presentation(**arguments: Any) -> Any:
        return _check(arguments)

    def detect_discrepancies(**arguments: Any) -> Any:
        return _check(arguments).discrepancies

    def extract_document(**arguments: Any) -> Any:
        return deps.get_trade_check_service().extract(
            _document(arguments.get("document")), principal
        )

    return {
        "check_presentation": check_presentation,
        "detect_discrepancies": detect_discrepancies,
        "extract_document": extract_document,
    }


def build_server(actor: str, *, with_audit_tools: bool = True) -> Any:
    """Build the MCP server for Fin2's catalog, refusing on any catalog/handler mismatch."""
    container = deps.get_container()
    return mcpserve.build_server(
        name="trade-finance-checker",
        version=str(getattr(container.settings, "version", "") or "0.0.1"),
        catalog=container.tool_catalog,
        handlers=build_handlers(actor),
        audit_store=getattr(container, "audit", None) if with_audit_tools else None,
    )
