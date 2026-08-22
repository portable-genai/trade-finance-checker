"""Unit tests for DiscrepancyDetector : the deterministic heart of B4.

These tests assert the detector finds the planted discrepancies on a discrepant
presentation, finds none on a clean one, and tags each finding with the right UCP600
article and severity. No Google Cloud SDK, no LLM : the detector is pure.
"""

from __future__ import annotations

from datetime import date

import pytest
from tests.fixtures import sample_trade

from trade_finance_checker.domain.detector import DiscrepancyDetector
from trade_finance_checker.domain.models import (
    CitationType,
    DiscrepancyKind,
    Severity,
    TradeDocType,
)


def _extracts(documents):
    """Project presented documents to extracts (the detector takes extracts)."""
    from trade_finance_checker.domain.models import DocumentExtract

    return [
        DocumentExtract(
            doc_type=d.doc_type,
            fields=dict(d.fields),
            pages=d.pages,
            document_id=d.document_id,
        )
        for d in documents
    ]


def test_clean_presentation_has_no_discrepancies():
    detector = DiscrepancyDetector()
    found = detector.detect(
        sample_trade.CLEAN_LC,
        _extracts(sample_trade.CLEAN_DOCUMENTS),
        list(sample_trade.SAMPLE_RULES),
    )
    assert found == [], f"clean presentation produced discrepancies: {found}"


def test_discrepant_presentation_finds_all_planted_kinds():
    detector = DiscrepancyDetector()
    found = detector.detect(
        sample_trade.DISCREPANT_LC,
        _extracts(sample_trade.DISCREPANT_DOCUMENTS),
        list(sample_trade.SAMPLE_RULES),
    )
    kinds = {d.kind for d in found}
    assert DiscrepancyKind.AMOUNT_MISMATCH in kinds
    assert DiscrepancyKind.INCONSISTENT_DATA in kinds  # currency mismatch
    assert DiscrepancyKind.LATE_SHIPMENT in kinds
    assert DiscrepancyKind.DESCRIPTION_MISMATCH in kinds
    assert DiscrepancyKind.MISSING_DOCUMENT in kinds  # insurance required for CIF


def test_every_discrepancy_is_cited_to_ucp600_and_lc():
    detector = DiscrepancyDetector()
    found = detector.detect(
        sample_trade.DISCREPANT_LC,
        _extracts(sample_trade.DISCREPANT_DOCUMENTS),
        list(sample_trade.SAMPLE_RULES),
    )
    assert found
    for disc in found:
        assert disc.ucp600_article.startswith("UCP600"), disc
        types = {c.source_type for c in disc.citations}
        # Every finding cites at least the UCP600 article authority.
        assert CitationType.UCP600 in types, disc


def test_amount_mismatch_is_high_severity():
    detector = DiscrepancyDetector()
    found = detector.detect(
        sample_trade.DISCREPANT_LC,
        _extracts(sample_trade.DISCREPANT_DOCUMENTS),
        list(sample_trade.SAMPLE_RULES),
    )
    amount = next(d for d in found if d.kind is DiscrepancyKind.AMOUNT_MISMATCH)
    assert amount.severity is Severity.HIGH
    assert amount.doc_type is TradeDocType.INVOICE
    assert amount.ucp600_article == "UCP600 Art. 18"


def test_expired_presentation_is_detected_with_as_of():
    detector = DiscrepancyDetector(as_of=date(2026, 3, 10))
    found = detector.detect(
        sample_trade.EXPIRED_LC,
        _extracts(sample_trade.EXPIRED_DOCUMENTS),
        list(sample_trade.SAMPLE_RULES),
    )
    expired = [d for d in found if d.kind is DiscrepancyKind.DATE_EXPIRED]
    assert expired, "presentation after expiry must be flagged DATE_EXPIRED"
    assert expired[0].severity is Severity.CRITICAL
    assert expired[0].ucp600_article == "UCP600 Art. 6"


def test_missing_required_document_is_critical():
    detector = DiscrepancyDetector()
    # CLEAN_LC requires invoice + bill_of_lading; present only the invoice.
    only_invoice = [d for d in sample_trade.CLEAN_DOCUMENTS if d.doc_type is TradeDocType.INVOICE]
    found = detector.detect(
        sample_trade.CLEAN_LC, _extracts(only_invoice), list(sample_trade.SAMPLE_RULES)
    )
    missing = [d for d in found if d.kind is DiscrepancyKind.MISSING_DOCUMENT]
    assert missing, "a required-but-absent document must be flagged MISSING_DOCUMENT"
    assert any(d.severity is Severity.CRITICAL for d in missing)


def test_amount_tolerance_band_suppresses_small_overage():
    detector = DiscrepancyDetector(amount_tolerance_pct=0.05)
    # Invoice 102000 vs LC 100000 is within +5%, so no amount discrepancy.
    from trade_finance_checker.domain.models import DocumentExtract

    extracts = [
        DocumentExtract(
            doc_type=TradeDocType.INVOICE,
            fields={"amount": "102000.00", "currency": "USD"},
        ),
        DocumentExtract(
            doc_type=TradeDocType.BILL_OF_LADING, fields={"shipment_date": "2026-05-01"}
        ),
    ]
    found = detector.detect(sample_trade.CLEAN_LC, extracts, list(sample_trade.SAMPLE_RULES))
    assert not any(d.kind is DiscrepancyKind.AMOUNT_MISMATCH for d in found)


def test_detector_runs_without_a_rule_set():
    """LC-vs-document checks must still run when the governed rule set is empty."""
    detector = DiscrepancyDetector()
    found = detector.detect(
        sample_trade.DISCREPANT_LC, _extracts(sample_trade.DISCREPANT_DOCUMENTS), []
    )
    assert any(d.kind is DiscrepancyKind.AMOUNT_MISMATCH for d in found)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
