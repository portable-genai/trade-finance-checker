"""Unit tests for TradeCheckService : the SPEC §5 check pipeline.

Pipeline (SPEC §5, full R1 safety):
    redact(LC + docs) -> guardrail.screen(INPUT)
      -> [if blocked: audit + return blocked report]
      -> extraction.extract(each) (+ redact) -> rules.retrieve_rules (A2)
      -> DiscrepancyDetector.detect (deterministic) -> verdict
      -> llm draft narrative -> guardrail.screen(OUTPUT)
      -> review (always) -> audit.record(redacted)

These tests use only in-memory fakes (no Google Cloud SDK).
"""

from __future__ import annotations

from datetime import date

import pytest
from tests.conftest import BlockingGuardrail, load_service
from tests.fixtures import sample_trade

from trade_finance_checker.adapters.local.entitlements import LocalAclAdapter
from trade_finance_checker.config import LocalSettings, Settings
from trade_finance_checker.domain.detector import DiscrepancyDetector
from trade_finance_checker.domain.errors import AccessDenied, RulesUnavailableError
from trade_finance_checker.domain.identity import Principal
from trade_finance_checker.domain.models import (
    ComplianceVerdict,
    Decision,
    Direction,
    DiscrepancyReport,
    LetterOfCredit,
)

ACTOR = "officer@bank.test"
# A verified, entitled demo-bank principal (the sample-trade fixture LCs are demo-bank
# owned). ``actor`` is derived from ``PRINCIPAL.subject`` inside the service.
PRINCIPAL = Principal(
    subject=ACTOR,
    principals=("group:trade-analyst",),
    tenant="demo-bank",
)


def _acl() -> LocalAclAdapter:
    """The real local seeded owner registry (demo-bank owns the sample-trade LC ids)."""
    return LocalAclAdapter(
        Settings(
            profile="local", local=LocalSettings(rules_db_path=":memory:", audit_path=":memory:")
        )
    )


def _service(extraction, rules, llm, guardrail, redaction, tracer, audit, detector=None):
    cls = load_service("TradeCheckService")
    return cls(
        extraction, rules, llm, guardrail, redaction, tracer, audit, _acl(), detector=detector
    )


# --------------------------------------------------------------------------- #
# Redaction happens BEFORE anything (P-04).
# --------------------------------------------------------------------------- #
def test_redaction_runs_before_extraction_and_strips_pii(trade_check_service, redaction, audit):
    trade_check_service.check(sample_trade.PII_LC, sample_trade.PII_DOCUMENTS, principal=PRINCIPAL)

    assert redaction.calls, "redaction.redact was never called"
    # The raw NRIC / email must never survive into the audited prompt.
    assert audit.events
    event = audit.events[-1]
    assert "S1234567A" not in event.redacted_prompt
    assert "jane.doe@example.com" not in event.redacted_prompt


# --------------------------------------------------------------------------- #
# Blocked input: blocked report + audit BLOCKED + requires_human_review.
# --------------------------------------------------------------------------- #
def test_blocked_input_returns_blocked_report_and_audits(
    extraction, rules, llm, redaction, tracer, audit
):
    blocking = BlockingGuardrail(block_input=True)
    service = _service(extraction, rules, llm, blocking, redaction, tracer, audit)

    report = service.check(
        sample_trade.MALICIOUS_LC, sample_trade.CLEAN_DOCUMENTS, principal=PRINCIPAL
    )

    assert isinstance(report, DiscrepancyReport)
    assert report.requires_human_review is True
    assert report.discrepancies == ()  # no findings leaked on a block
    assert llm.requests == []  # the LLM must never run once blocked
    assert extraction.calls == []  # extraction must not run on a blocked input

    blocked = [e for e in audit.events if e.decision is Decision.BLOCKED]
    assert blocked, "expected an audit event with decision=BLOCKED"
    assert blocked[0].actor == ACTOR
    assert blocked[0].action == "check"


def test_blocked_input_screens_input_direction_only(
    extraction, rules, llm, redaction, tracer, audit
):
    blocking = BlockingGuardrail(block_input=True)
    _service(extraction, rules, llm, blocking, redaction, tracer, audit).check(
        sample_trade.MALICIOUS_LC, sample_trade.CLEAN_DOCUMENTS, principal=PRINCIPAL
    )
    directions = [d for _, d in blocking.calls]
    assert Direction.INPUT in directions
    assert Direction.OUTPUT not in directions


# --------------------------------------------------------------------------- #
# Clean presentation -> COMPLIANT, zero discrepancies, still human-reviewed.
# --------------------------------------------------------------------------- #
def test_clean_presentation_is_compliant_but_human_reviewed(trade_check_service, audit):
    report = trade_check_service.check(
        sample_trade.CLEAN_LC, sample_trade.CLEAN_DOCUMENTS, principal=PRINCIPAL
    )

    assert report.verdict is ComplianceVerdict.COMPLIANT
    assert report.discrepancy_count == 0
    # A discrepancy report is consequential and ALWAYS requires human review (P-06).
    assert report.requires_human_review is True
    # A clean (compliant) check is audited as ALLOWED.
    assert any(e.decision is Decision.ALLOWED for e in audit.events)


# --------------------------------------------------------------------------- #
# Discrepant presentation -> DISCREPANT, findings cited, escalated audit.
# --------------------------------------------------------------------------- #
def test_discrepant_presentation_is_discrepant_and_cited(
    extraction, rules, llm, guardrail, redaction, tracer, audit
):
    service = _service(extraction, rules, llm, guardrail, redaction, tracer, audit)
    report = service.check(
        sample_trade.DISCREPANT_LC, sample_trade.DISCREPANT_DOCUMENTS, principal=PRINCIPAL
    )

    assert report.verdict is ComplianceVerdict.DISCREPANT
    assert report.discrepancy_count >= 4
    assert report.requires_human_review is True
    # Every discrepancy carries citations.
    assert all(d.citations for d in report.discrepancies)
    # The report rolls up de-duplicated citations.
    assert report.citations
    # A material discrepancy escalates the audit decision.
    assert any(e.decision is Decision.ESCALATED for e in audit.events)


def test_llm_never_overrides_the_deterministic_verdict(
    extraction, rules, redaction, guardrail, tracer, audit
):
    """A misbehaving LLM cannot change the verdict or the discrepancy set."""

    class LyingLLM:
        requests: list = []

        def generate(self, request):  # noqa: ANN001
            from trade_finance_checker.domain.models import LlmResponse

            # Claims everything is fine, with no findings : must be ignored.
            return LlmResponse(text='{"narrative": "all good, no issues", "cited_articles": []}')

        def classify(self, text, labels):  # noqa: ANN001
            return labels[0] if labels else ""

    service = _service(extraction, rules, LyingLLM(), guardrail, redaction, tracer, audit)
    report = service.check(
        sample_trade.DISCREPANT_LC, sample_trade.DISCREPANT_DOCUMENTS, principal=PRINCIPAL
    )
    # Deterministic detector still drives the verdict regardless of the LLM prose.
    assert report.verdict is ComplianceVerdict.DISCREPANT
    assert report.discrepancy_count >= 4


# --------------------------------------------------------------------------- #
# Tracing + rules retrieval are exercised.
# --------------------------------------------------------------------------- #
def test_check_is_wrapped_in_a_tracer_span(trade_check_service, tracer):
    trade_check_service.check(
        sample_trade.CLEAN_LC, sample_trade.CLEAN_DOCUMENTS, principal=PRINCIPAL
    )
    assert tracer.spans, "the check pipeline must open at least one trace span"


def test_rules_are_retrieved_from_a2(trade_check_service, rules):
    trade_check_service.check(
        sample_trade.CLEAN_LC, sample_trade.CLEAN_DOCUMENTS, principal=PRINCIPAL
    )
    assert rules.calls, "the governed UCP600 rule set must be retrieved (R3 / A2)"


def test_empty_rule_retrieval_is_a_hard_error(extraction, llm, guardrail, redaction, tracer, audit):
    class EmptyRules:
        def retrieve_rules(self, query, top_k=8):  # noqa: ANN001
            return []

    service = _service(extraction, EmptyRules(), llm, guardrail, redaction, tracer, audit)
    with pytest.raises(RulesUnavailableError, match="no evidence"):
        service.check(sample_trade.CLEAN_LC, sample_trade.CLEAN_DOCUMENTS, principal=PRINCIPAL)
    assert not audit.events


def test_both_directions_screened_on_a_clean_run(trade_check_service, guardrail):
    trade_check_service.check(
        sample_trade.CLEAN_LC, sample_trade.CLEAN_DOCUMENTS, principal=PRINCIPAL
    )
    directions = [d for _, d in guardrail.calls]
    assert Direction.INPUT in directions
    assert Direction.OUTPUT in directions


# --------------------------------------------------------------------------- #
# Configurable detector is honoured by the service.
# --------------------------------------------------------------------------- #
def test_service_uses_injected_detector(
    extraction, rules, llm, guardrail, redaction, tracer, audit
):
    detector = DiscrepancyDetector(as_of=date(2026, 3, 10))
    service = _service(
        extraction, rules, llm, guardrail, redaction, tracer, audit, detector=detector
    )
    report = service.check(
        sample_trade.EXPIRED_LC, sample_trade.EXPIRED_DOCUMENTS, principal=PRINCIPAL
    )
    assert report.verdict is ComplianceVerdict.DISCREPANT


def test_extract_surface_redacts_and_audits(trade_check_service, audit):
    extract = trade_check_service.extract(sample_trade.PII_DOCUMENTS[0], principal=PRINCIPAL)
    assert extract.doc_type is sample_trade.PII_DOCUMENTS[0].doc_type
    assert any(e.action == "extract" for e in audit.events)


# --------------------------------------------------------------------------- #
# Object-level authorization (C2) is enforced in the SERVICE, not only the route.
# --------------------------------------------------------------------------- #
def test_check_denies_lc_with_no_registered_owner_fail_closed(trade_check_service, audit):
    """An LC id absent from the server-side owner registry is denied (default deny)."""
    unknown = LetterOfCredit(
        lc_number="LC-NOT-SEEDED-9999",
        amount=1000.0,
        currency="USD",
        expiry_date="2026-12-31",
        latest_shipment="2026-12-01",
    )
    with pytest.raises(AccessDenied):
        trade_check_service.check(unknown, sample_trade.CLEAN_DOCUMENTS, principal=PRINCIPAL)
    # The deny happens before the pipeline runs: nothing was examined or audited.
    assert [e for e in audit.events if e.action == "check"] == []


def test_check_denies_cross_tenant_principal_for_owned_lc(trade_check_service, audit):
    """A principal outside the LC's owning tenant is denied even with a trade role."""
    other_bank = Principal(
        subject="user@other-tenant.example",
        principals=("group:trade-analyst",),
        tenant="other-bank",
    )
    with pytest.raises(AccessDenied):
        trade_check_service.check(
            sample_trade.CLEAN_LC, sample_trade.CLEAN_DOCUMENTS, principal=other_bank
        )
    assert [e for e in audit.events if e.action == "check"] == []


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
