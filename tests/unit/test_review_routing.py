"""R8 routing: an escalated discrepancy report is routed to Hrz7 via the shared review-kit.

Every discrepancy report requires human review (P-06), so rule R8 says it MUST be handed to the
Hrz7 maker-checker console rather than left as a boolean. These tests prove the producer half of
that loop end-to-end against the offline local router (an in-memory outbox), and prove the redact-
before-wire boundary so no raw trade-party identifier reaches the console.
"""

from __future__ import annotations

import pytest
from tests.conftest import load_service
from tests.fixtures import sample_trade

from trade_finance_checker.adapters._review_payload import report_to_review
from trade_finance_checker.adapters.local.entitlements import LocalAclAdapter
from trade_finance_checker.adapters.local.review_router import LocalReviewRouter
from trade_finance_checker.config import LocalSettings, Settings
from trade_finance_checker.domain.identity import Principal
from trade_finance_checker.domain.models import (
    Citation,
    CitationType,
    ComplianceVerdict,
    Discrepancy,
    DiscrepancyKind,
    DiscrepancyReport,
    PresentationSummary,
    Severity,
    TradeDocType,
)

ACTOR = "officer@bank.test"
PRINCIPAL = Principal(
    subject=ACTOR,
    principals=("group:trade-analyst",),
    tenant="demo-bank",
)


def _settings() -> Settings:
    return Settings(
        profile="local", local=LocalSettings(rules_db_path=":memory:", audit_path=":memory:")
    )


def _acl() -> LocalAclAdapter:
    """The real local seeded owner registry (demo-bank owns the sample-trade LC ids)."""
    return LocalAclAdapter(_settings())


def _service_with_router(extraction, rules, llm, guardrail, redaction, tracer, audit, router):
    cls = load_service("TradeCheckService")
    return cls(
        extraction,
        rules,
        llm,
        guardrail,
        redaction,
        tracer,
        audit,
        _acl(),
        review_router=router,
    )


def test_check_routes_escalated_report_to_outbox(
    extraction, rules, llm, guardrail, redaction, tracer, audit
):
    """A completed check enqueues exactly one review to the router's outbox (R8)."""
    router = LocalReviewRouter(_settings())
    service = _service_with_router(
        extraction, rules, llm, guardrail, redaction, tracer, audit, router
    )
    assert not router.outbox.pending()

    report = service.check(
        sample_trade.DISCREPANT_LC, sample_trade.DISCREPANT_DOCUMENTS, principal=PRINCIPAL
    )
    assert report.requires_human_review

    pending = router.outbox.pending()
    assert len(pending) == 1, "the escalated report must be routed to Hrz7 exactly once"
    review = pending[0].review
    assert review.action == f"trade_discrepancy_report:{report.verdict.value}"
    assert review.case_ref == report.lc_number
    assert review.maker == ACTOR
    assert review.tenant == "demo-bank"


def _high_risk_report_with_pii() -> DiscrepancyReport:
    # A citation snippet carrying a synthetic SG NRIC: it must be masked before the wire.
    cite = Citation(
        source_id="doc-1",
        source_type=CitationType.DOCUMENT,
        title="Bill of lading extract",
        snippet="Consignee NRIC S1234567D printed on the B/L.",
    )
    discrepancy = Discrepancy(
        kind=DiscrepancyKind.AMOUNT_MISMATCH,
        ucp600_article="UCP600 art.18",
        doc_type=TradeDocType.INVOICE,
        field="amount",
        expected="USD 100000.00",
        found="USD 250000.00",
        severity=Severity.HIGH,
        citations=(cite,),
    )
    summary = PresentationSummary(
        lc_number="LC-FICTIONAL-001",
        currency="USD",
        amount=100000.0,
        expiry_date="2026-12-31",
        latest_shipment="2026-11-30",
        documents_checked=(TradeDocType.INVOICE,),
    )
    return DiscrepancyReport(
        lc_number="LC-FICTIONAL-001",
        documents_checked=(TradeDocType.INVOICE,),
        discrepancies=(discrepancy,),
        verdict=ComplianceVerdict.DISCREPANT,
        summary=summary,
        citations=(cite,),
    )


def test_payload_is_redacted_and_carries_tenant_and_severity():
    """The wire payload masks identifiers, carries the tenant, and maps the severity (R1/R8)."""
    review = report_to_review(_high_risk_report_with_pii(), maker=ACTOR, tenant="demo-bank")

    assert review.tenant == "demo-bank"
    assert review.severity == "high"
    assert review.required_approvals == 2, "a HIGH-severity report warrants dual control"
    assert review.case_ref == "LC-FICTIONAL-001"
    # No raw NRIC survives into the payload the console receives.
    assert "S1234567D" not in review.summary
    assert "S1234567D" not in review.subject
    assert review.citations, "the report's evidence is carried for the reviewer to trace"
    for citation in review.citations:
        assert "S1234567D" not in citation.snippet
    assert any(c.title == "Bill of lading extract" for c in review.citations)


def test_no_router_still_assembles_report(
    extraction, rules, llm, guardrail, redaction, tracer, audit
):
    """Routing is optional: with no router bound, a check still returns a report needing review."""
    service = _service_with_router(
        extraction, rules, llm, guardrail, redaction, tracer, audit, None
    )
    report = service.check(
        sample_trade.DISCREPANT_LC, sample_trade.DISCREPANT_DOCUMENTS, principal=PRINCIPAL
    )
    assert report.requires_human_review


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
