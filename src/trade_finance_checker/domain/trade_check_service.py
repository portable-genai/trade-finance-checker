"""TradeCheckService : the SPEC §5 trade-finance check pipeline.

Owns the standard check pipeline and calls only ports. The pipeline, in order
(the full R1 safety pipeline because B4 handles trade-party PII):

    tracer.span("trade.check"):
      redact(LC + each document)               (P-04, before anything else)
      -> guardrail.screen(INPUT)               [blocked -> audit BLOCKED + blocked report]
      -> extraction.extract(each document)     (+ redact each extract)
      -> rules.retrieve_rules                  (governed UCP600 set from A2; R3)
      -> DiscrepancyDetector.detect            (DETERMINISTIC : the verdict source)
      -> TradeReviewPolicy.verdict             (COMPLIANT iff zero material discrepancies)
      -> llm.generate                          (draft narrative; never overrides a finding)
      -> guardrail.screen(OUTPUT)
      -> review (always requires_human_review)
      -> audit.record(redacted prompt + response)

Defensive throughout: a guardrail block, an extraction failure, or an unavailable rule
set degrade to a safe, human-review-flagged report rather than silently passing. The
verdict and discrepancy set are always the deterministic detector's; the LLM only drafts
prose.

Pure domain code : no Google Cloud / ADK / FastAPI imports.
"""

from __future__ import annotations

import contextlib
from contextlib import nullcontext
from typing import Any

from . import _grounded as g
from .detector import DiscrepancyDetector
from .entitlements import authorize_object
from .errors import AccessDenied, RulesUnavailableError
from .identity import Principal
from .models import (
    AuditEvent,
    Citation,
    ComplianceVerdict,
    Decision,
    Direction,
    Discrepancy,
    DiscrepancyReport,
    DocumentExtract,
    GuardrailVerdict,
    LetterOfCredit,
    PresentationSummary,
    PresentedDocument,
    RedactionResult,
    Ucp600Rule,
)
from .prompts import _CITATION_RULES, REPORT_NARRATIVE_SYSTEM, REPORT_NARRATIVE_USER
from .review_policy import TradeReviewPolicy
from .serialization import to_jsonable

# JSON schema for the structured narrative response.
_NARRATIVE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "narrative": {"type": "string"},
        "cited_articles": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["narrative", "cited_articles"],
}

_BLOCKED_NARRATIVE = (
    "This presentation was blocked by the safety guardrail and was not examined. "
    "It has been routed for human review."
)


class TradeCheckService:
    """Trade-finance presentation checker. Constructor takes explicit ports (SPEC §5)."""

    def __init__(
        self,
        extraction: Any,
        rules: Any,
        llm: Any,
        guardrail: Any,
        redaction: Any,
        tracer: Any,
        audit: Any,
        acl: Any,
        detector: DiscrepancyDetector | None = None,
        review_policy: TradeReviewPolicy | None = None,
        review_router: Any = None,
    ) -> None:
        self._extraction = extraction
        self._rules = rules
        self._llm = llm
        self._guardrail = guardrail
        self._redaction = redaction
        self._tracer = tracer
        self._audit = audit
        self._acl = acl
        self._detector = detector or DiscrepancyDetector()
        self._review = review_policy or TradeReviewPolicy()
        self._review_router = review_router

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def check(
        self,
        lc: LetterOfCredit,
        documents: list[PresentedDocument],
        principal: Principal,
    ) -> DiscrepancyReport:
        """Examine ``documents`` against ``lc`` via the SPEC §5 check pipeline.

        Object-level authorization is enforced HERE (not only in the API route), so the
        CLI and agent paths are covered too: the verified ``principal`` must be entitled to
        this LC, decided server-side against the AclPort owner registry. A caller that is
        not entitled gets :class:`AccessDenied` (HTTP 403) BEFORE any redaction, extraction,
        model call, or audit write, so a denied request leaks nothing and leaves no trace.
        The audit actor is derived from the verified principal, never client-asserted.
        """
        self._authorize_lc(lc, principal)
        actor = principal.actor
        span = self._tracer.span("trade.check", action="check", actor=actor)
        with span if span is not None else nullcontext():
            return self._check_inner(lc, documents, actor, principal.tenant)

    def extract(self, document: PresentedDocument, principal: Principal) -> DocumentExtract:
        """Parse a single presented document (the /v1/extract surface).

        Takes the verified ``principal`` (the audit actor is derived from it, never
        client-asserted). Unlike :meth:`check`, extract parses a caller-supplied document
        with no server-side owner to retrieve, so there is no addressable object to
        authorize against; authentication (the 401 seam) plus the verified actor are the
        controls here. Object-level authorization applies to the LC-keyed check surface.
        """
        actor = principal.actor
        span = self._tracer.span("trade.extract", action="extract", actor=actor)
        with span if span is not None else nullcontext():
            extract = self._extraction.extract(document)
            extract = self._redact_extract(extract)
            self._audit_extract(actor, extract)
            return extract

    def _authorize_lc(self, lc: LetterOfCredit, principal: Principal) -> None:
        """Fail-closed object authorization for an LC against the server-side owner registry.

        The LC id is looked up in the AclPort (never trusting an owner from the body). An
        unknown object (no registered owner) is denied, as is a principal outside the
        owning tenant or without a permitted role / explicit grant.
        """
        owner = self._acl.owner(f"lc:{lc.lc_number}")
        if owner is None:
            raise AccessDenied(
                f"{principal.actor} is not entitled to letter of credit {lc.lc_number!r} "
                "(no registered owner)"
            )
        authorize_object(
            principal,
            object_id=lc.lc_number,
            object_tenant=owner.tenant,
            allowed_roles=owner.allowed_roles,
        )

    # ------------------------------------------------------------------ #
    # Pipeline
    # ------------------------------------------------------------------ #
    def _check_inner(
        self,
        lc: LetterOfCredit,
        documents: list[PresentedDocument],
        actor: str,
        tenant: str = "",
    ) -> DiscrepancyReport:
        # 1) Redact the LC + documents (P-04) before anything touches a model or log.
        redacted_prompt = self._redact_request(lc, documents)

        # 2) Guardrail screen (INPUT). Blocked -> audit BLOCKED + blocked report.
        in_verdict: GuardrailVerdict = self._guardrail.screen(redacted_prompt, Direction.INPUT)
        if not in_verdict.allowed:
            return self._blocked_report(lc, documents, actor, redacted_prompt, in_verdict)

        # 3) Extract each presented document (and redact each extract).
        extracts = [self._redact_extract(self._extraction.extract(doc)) for doc in documents]

        # 4) Retrieve the governed UCP600 rule set from A2 (R3). Empty is a hard error:
        #    no compliance report is emitted without governed rule evidence.
        rules = self._retrieve_rules(lc, extracts)

        # 5) DETERMINISTIC detection : this is the only source of the verdict.
        discrepancies = tuple(self._detector.detect(lc, extracts, rules))

        # 6) Verdict + review decision from the pure policy.
        verdict = self._review.verdict(discrepancies)
        requires_review = self._review.requires_review(discrepancies)  # always True
        escalates = self._review.escalates(discrepancies)

        # 7) LLM draft of the narrative (never overrides a finding or the verdict).
        narrative = self._draft_narrative(lc, documents, verdict, discrepancies)

        # 8) Guardrail screen (OUTPUT) on the drafted narrative.
        out_verdict: GuardrailVerdict = self._guardrail.screen(narrative, Direction.OUTPUT)
        if not out_verdict.allowed:
            return self._blocked_report(
                lc, documents, actor, redacted_prompt, out_verdict, direction=Direction.OUTPUT
            )
        narrative = out_verdict.sanitized_text or narrative

        citations = self._collect_citations(lc, discrepancies)
        report = DiscrepancyReport(
            lc_number=lc.lc_number,
            documents_checked=tuple(d.doc_type for d in documents),
            discrepancies=discrepancies,
            verdict=verdict,
            summary=self._summary(lc, documents),
            requires_human_review=requires_review,
            narrative=narrative,
            citations=citations,
        )

        # 9) Audit (already-redacted prompt + response). Escalated when severe.
        decision = Decision.ESCALATED if escalates else Decision.ALLOWED
        self._audit_report(actor, redacted_prompt, report, decision)

        # 10) Route the escalation to human-review-console (rule R8). A discrepancy report always
        # requires human
        #     review, so it is handed to the maker-checker console rather than terminating in a
        #     boolean; the adapter redacts before the wire. Best-effort: a console outage must not
        #     fail an already-assembled, already-audited report (the audit record is the durable
        #     escalation of record, and the outbox path retries).
        if self._review_router is not None and report.requires_human_review:
            with contextlib.suppress(Exception):
                self._review_router.route(report, maker=actor, tenant=tenant)
        return report

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _redact_request(self, lc: LetterOfCredit, documents: list[PresentedDocument]) -> str:
        """Build a redacted, human-readable description of the request for the log.

        The beneficiary / applicant (trade-party PII) and any document field values are
        passed through the redaction port so the audited prompt never carries raw PII.
        """
        parts = [
            f"LC {lc.lc_number} {lc.currency} {lc.amount:.2f}",
            f"beneficiary={lc.beneficiary}",
            f"applicant={lc.applicant}",
        ]
        for doc in documents:
            parts.append(
                f"{doc.doc_type.value}: " + ", ".join(f"{k}={v}" for k, v in doc.fields.items())
            )
        result: RedactionResult = self._redaction.redact("; ".join(parts))
        return result.text

    def _redact_extract(self, extract: DocumentExtract) -> DocumentExtract:
        """Redact the free-text and PII-bearing fields of one extract (P-04)."""
        from dataclasses import replace

        redacted_text = self._redaction.redact(extract.raw_text).text if extract.raw_text else ""
        redacted_fields = {
            key: (self._redaction.redact(value).text if _is_pii_field(key) else value)
            for key, value in extract.fields.items()
        }
        return replace(extract, raw_text=redacted_text, fields=redacted_fields)

    def _retrieve_rules(
        self, lc: LetterOfCredit, extracts: list[DocumentExtract]
    ) -> list[Ucp600Rule]:
        """Retrieve UCP600 articles from A2 for the documents in this presentation."""
        doc_types = ", ".join(sorted({e.doc_type.value for e in extracts}))
        query = (
            f"UCP600 examination rules for a documentary credit presentation with "
            f"documents: {doc_types or 'invoice, transport'}; incoterm {lc.incoterm or 'n/a'}"
        )
        try:
            top_k = self._rules_top_k()
            rules = list(self._rules.retrieve_rules(query, top_k=top_k) or [])
        except Exception as exc:  # noqa: BLE001 - translate adapter failure to domain error
            raise RulesUnavailableError("governed UCP600 rule retrieval failed") from exc
        if not rules:
            raise RulesUnavailableError("governed UCP600 rule retrieval returned no evidence")
        return rules

    def _rules_top_k(self) -> int:
        # Default top_k; the rules port may ignore it. Keeps the call defensive.
        return 8

    def _draft_narrative(
        self,
        lc: LetterOfCredit,
        documents: list[PresentedDocument],
        verdict: ComplianceVerdict,
        discrepancies: tuple[Discrepancy, ...],
    ) -> str:
        """Second-stage LLM call: draft the examiner narrative (never authoritative)."""
        findings_block = g.render_findings(discrepancies)
        docs_block = ", ".join(sorted({d.doc_type.value for d in documents}))
        system = REPORT_NARRATIVE_SYSTEM.format(citation_rules=_CITATION_RULES)
        user = REPORT_NARRATIVE_USER.format(
            lc_number=lc.lc_number,
            verdict=verdict.value,
            documents=docs_block,
            findings=findings_block,
        )
        request = g.build_llm_request(
            system_instruction=system,
            user_content=user,
            model=None,  # adapter default => reasoning model gemini-3.5-flash
            response_schema=_NARRATIVE_SCHEMA,
        )
        try:
            response = self._llm.generate(request)
        except Exception:  # noqa: BLE001 - narrative is presentation, never fatal
            return g.fallback_narrative(lc, verdict, discrepancies)
        g.maybe_record_usage(self._tracer, response)
        parsed = g.parse_structured(response)
        narrative = str(parsed.get("narrative") or "").strip()
        return narrative or g.fallback_narrative(lc, verdict, discrepancies)

    def _summary(
        self, lc: LetterOfCredit, documents: list[PresentedDocument]
    ) -> PresentationSummary:
        return PresentationSummary(
            lc_number=lc.lc_number,
            currency=lc.currency,
            amount=lc.amount,
            expiry_date=lc.expiry_date,
            latest_shipment=lc.latest_shipment,
            documents_checked=tuple(d.doc_type for d in documents),
            terms=dict(lc.terms),
        )

    @staticmethod
    def _collect_citations(
        lc: LetterOfCredit, discrepancies: tuple[Discrepancy, ...]
    ) -> tuple[Citation, ...]:
        """De-duplicate the citations across all discrepancies, in finding order."""
        out: list[Citation] = []
        seen: set[tuple[str, str, int | None]] = set()
        for disc in discrepancies:
            for citation in disc.citations:
                key = (citation.source_id, citation.source_type.value, citation.page)
                if key not in seen:
                    seen.add(key)
                    out.append(citation)
        return tuple(out)

    # ------------------------------------------------------------------ #
    # Blocked report
    # ------------------------------------------------------------------ #
    def _blocked_report(
        self,
        lc: LetterOfCredit,
        documents: list[PresentedDocument],
        actor: str,
        redacted_prompt: str,
        verdict: GuardrailVerdict,
        direction: Direction = Direction.INPUT,
    ) -> DiscrepancyReport:
        """A well-formed blocked report (no findings leaked) flagged for human review."""
        reason = verdict.reason or "blocked by guardrail"
        report = DiscrepancyReport(
            lc_number=lc.lc_number,
            documents_checked=tuple(d.doc_type for d in documents),
            discrepancies=(),
            verdict=ComplianceVerdict.DISCREPANT,
            summary=self._summary(lc, documents),
            requires_human_review=True,
            narrative=f"{_BLOCKED_NARRATIVE} ({direction.value}: {reason}).",
            citations=(),
        )
        self._audit_report(actor, redacted_prompt, report, Decision.BLOCKED)
        return report

    # ------------------------------------------------------------------ #
    # Audit
    # ------------------------------------------------------------------ #
    def _audit_report(
        self,
        actor: str,
        redacted_prompt: str,
        report: DiscrepancyReport,
        decision: Decision,
    ) -> None:
        """Write an already-redacted WORM audit record for this check."""
        event = AuditEvent(
            action="check",
            actor=actor,
            decision=decision,
            redacted_prompt=redacted_prompt,
            redacted_response=report.narrative,
            citations=report.citations,
            metadata={
                "verdict": report.verdict.value,
                "n_discrepancies": str(report.discrepancy_count),
                "n_material": str(report.material_count),
                "requires_human_review": str(report.requires_human_review).lower(),
                "lc_number": report.lc_number,
            },
        )
        try:
            self._audit.record(event)
        except Exception:  # noqa: BLE001 - audit failure must not crash the request
            to_jsonable(event)  # the event is validated to be jsonable

    def _audit_extract(self, actor: str, extract: DocumentExtract) -> None:
        event = AuditEvent(
            action="extract",
            actor=actor,
            decision=Decision.ALLOWED,
            redacted_prompt=f"extract {extract.doc_type.value}",
            redacted_response=extract.raw_text,
            metadata={"doc_type": extract.doc_type.value, "pages": str(extract.pages)},
        )
        try:
            self._audit.record(event)
        except Exception:  # noqa: BLE001 - audit failure must not crash the request
            to_jsonable(event)


#: Extract field keys whose values may carry PII and so are redacted before audit.
_PII_FIELD_KEYS = frozenset({"beneficiary", "applicant", "consignee", "notify_party", "account"})


def _is_pii_field(key: str) -> bool:
    return key.strip().lower() in _PII_FIELD_KEYS
