"""Local agent-runtime adapter (AgentRuntimePort) : in-process check loop.

The ``local`` profile's stand-in for **Agent Runtime** (the hosted reasoning engine):
rather than calling a deployed endpoint, it assembles the domain :class:`TradeCheckService`
from the other local adapters and checks the presentation in-process. Under ``local`` the
platform client runs the app itself (a laptop runs one app, not the whole platform).
SDK-free and unconditional.

``query`` accepts the presentation as a JSON string ``{"lc": {...}, "documents": [...]}``
(the same shape the CLI ``check`` command reads); a non-JSON or empty message yields a
well-formed, human-review-flagged report rather than raising.
"""

from __future__ import annotations

import json
from typing import Any

from ...config import Settings
from ...domain.models import (
    ComplianceVerdict,
    DiscrepancyReport,
    LetterOfCredit,
    PresentationSummary,
    PresentedDocument,
    Session,
    TradeDocType,
)


class LocalAgentRuntimeAdapter:
    """In-process agent runtime: checks presentations via the local TradeCheckService."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._service = None

    def _check_service(self):  # type: ignore[no-untyped-def]
        if self._service is None:
            from ...domain.trade_check_service import TradeCheckService
            from .audit import LocalAppendOnlyAuditAdapter
            from .extraction import LocalDocumentExtractionAdapter
            from .guardrail import LocalHeuristicGuardrailAdapter
            from .llm import LocalDeterministicLLMAdapter
            from .redaction import LocalRegexRedactionAdapter
            from .rules import LocalFtsRulesAdapter
            from .tracer import LocalNoopTracerAdapter

            self._service = TradeCheckService(
                extraction=LocalDocumentExtractionAdapter(self._settings),
                rules=LocalFtsRulesAdapter(self._settings),
                llm=LocalDeterministicLLMAdapter(self._settings),
                guardrail=LocalHeuristicGuardrailAdapter(self._settings),
                redaction=LocalRegexRedactionAdapter(self._settings),
                tracer=LocalNoopTracerAdapter(self._settings),
                audit=LocalAppendOnlyAuditAdapter(self._settings),
            )
        return self._service

    def query(self, session: Session, message: str) -> DiscrepancyReport:
        data = self._parse(message)
        if data is None:
            return self._empty_report(session)
        lc = self._to_lc(data.get("lc", {}))
        documents = self._to_documents(data.get("documents", []) or [])
        return self._check_service().check(lc, documents, actor=session.user_id)

    def health(self) -> bool:
        return True

    # ------------------------------------------------------------------ #
    # Parsing
    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse(message: str) -> dict[str, Any] | None:
        try:
            parsed = json.loads(message)
        except (TypeError, ValueError):
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _to_lc(data: dict[str, Any]) -> LetterOfCredit:
        return LetterOfCredit(
            lc_number=str(data.get("lc_number", "")),
            amount=float(data.get("amount", 0.0) or 0.0),
            currency=str(data.get("currency", "")),
            expiry_date=str(data.get("expiry_date", "")),
            latest_shipment=str(data.get("latest_shipment", "")),
            incoterm=str(data.get("incoterm", "")),
            beneficiary=str(data.get("beneficiary", "")),
            applicant=str(data.get("applicant", "")),
            terms={str(k): str(v) for k, v in (data.get("terms") or {}).items()},
        )

    @staticmethod
    def _to_documents(items: list[dict[str, Any]]) -> list[PresentedDocument]:
        return [
            PresentedDocument(
                doc_type=TradeDocType(str(item.get("doc_type", "other"))),
                fields={str(k): str(v) for k, v in (item.get("fields") or {}).items()},
                pages=int(item.get("pages", 1) or 1),
                document_id=str(item.get("document_id", "")),
            )
            for item in items
        ]

    @staticmethod
    def _empty_report(session: Session) -> DiscrepancyReport:
        lc_number = session.case_id or ""
        return DiscrepancyReport(
            lc_number=lc_number,
            documents_checked=(),
            discrepancies=(),
            verdict=ComplianceVerdict.DISCREPANT,
            summary=PresentationSummary(
                lc_number=lc_number,
                currency="",
                amount=0.0,
                expiry_date="",
                latest_shipment="",
            ),
            narrative="No presentation payload supplied; routed for human review.",
        )
