"""Span ATTRIBUTES carry structure, never presentation content, and this test can tell.

The conftest ``RecordingTracer`` records span NAMES (``self.spans.append(name)``), which is
the right shape for the test asserting the pipeline opened its span, and structurally blind
to the one defect that matters here: it discards ``**attributes``, so a span that started
carrying the LC number, the beneficiary, or a discrepancy narrative would keep every existing
test green.

A trace backend is not the WORM audit trail. It has no redaction stage, a far wider read
audience and no retention rule written against a regulator's requirement, so a span attribute
is OUTSIDE the boundary that redact-before-anything (R1 / P-04) holds. The ordering makes it
sharper still: the span opens BEFORE ``_check_inner`` redacts, so an attribute built from the
request would carry raw counterparty PII by construction.

The recorder below keeps ``dict(attributes)``, and the content case drives both request paths
with ``PII_LC`` / ``PII_DOCUMENTS``, whose beneficiary and applicant embed a planted NRIC,
account number and email, so a leak fails on a planted literal rather than on a subtlety.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from tests.fixtures import sample_trade

from trade_finance_checker.domain.identity import Principal

_ACTOR = "officer@bank.test"

#: A verified, entitled demo-bank principal: the sample-trade fixture LCs are demo-bank
#: owned, and object authorization runs before the span opens.
_PRINCIPAL = Principal(
    subject=_ACTOR,
    principals=("group:trade-analyst",),
    tenant="demo-bank",
)

#: The complete attribute key set a trade-check span may carry, per span name. Widening one
#: of these is a decision about what leaves the trust boundary, so it is made here
#: deliberately rather than by adding a keyword argument at a call site.
_ALLOWED: dict[str, set[str]] = {
    "trade.check": {"action", "actor"},
    "trade.extract": {"action", "actor"},
}

#: Planted in PII_LC's beneficiary/applicant and in PII_DOCUMENTS' invoice fields.
_PLANTED = (
    "S1234567A",
    "jane.doe@example.com",
    "Jane Tan",
    "123456789012",
)


class _AttributeRecordingTracer:
    """Keeps (name, attributes) per span, unlike the name-only conftest recorder."""

    def __init__(self) -> None:
        self.spans: list[tuple[str, dict[str, str]]] = []

    @contextmanager
    def span(self, name: str, **attributes: str):  # type: ignore[no-untyped-def]
        self.spans.append((name, dict(attributes)))
        yield

    def record_token_usage(self, usage, model):  # type: ignore[no-untyped-def]
        return None


@pytest.fixture
def tracer() -> _AttributeRecordingTracer:  # type: ignore[override]
    """Override the conftest tracer so ``trade_check_service`` assembles with THIS recorder."""
    return _AttributeRecordingTracer()


def _drive_both_paths(service, lc, documents) -> None:
    service.check(lc, documents, principal=_PRINCIPAL)
    service.extract(documents[0], principal=_PRINCIPAL)


def test_both_request_paths_open_their_named_spans_with_allowlisted_keys_only(
    trade_check_service, tracer
) -> None:
    _drive_both_paths(trade_check_service, sample_trade.CLEAN_LC, sample_trade.CLEAN_DOCUMENTS)
    assert [name for name, _ in tracer.spans] == ["trade.check", "trade.extract"]
    for name, attributes in tracer.spans:
        assert set(attributes) == _ALLOWED[name], (
            f"span {name!r} attribute keys changed; widening the set is a trust-boundary "
            "decision, so update _ALLOWED here deliberately"
        )


def test_no_span_attribute_carries_the_planted_identifiers(trade_check_service, tracer) -> None:
    """PII_LC's beneficiary and applicant embed an NRIC, an account number and an email."""
    _drive_both_paths(trade_check_service, sample_trade.PII_LC, sample_trade.PII_DOCUMENTS)
    emitted = " ".join(
        str(value) for _, attributes in tracer.spans for value in attributes.values()
    )
    for planted in _PLANTED:
        assert planted not in emitted, f"{planted!r} reached a span attribute"
        assert planted.lower() not in emitted.lower()


def test_no_span_attribute_carries_the_lc_or_document_identifier(
    trade_check_service, tracer
) -> None:
    """An LC number names a specific commercial relationship; it is content, not structure."""
    _drive_both_paths(trade_check_service, sample_trade.PII_LC, sample_trade.PII_DOCUMENTS)
    emitted = " ".join(
        str(value) for _, attributes in tracer.spans for value in attributes.values()
    )
    assert sample_trade.PII_LC.lc_number not in emitted
    for document in sample_trade.PII_DOCUMENTS:
        assert document.document_id not in emitted


def test_a_discrepant_presentation_attaches_no_findings(trade_check_service, tracer) -> None:
    """The verdict is the tempting thing to trace; the discrepancies are the private part."""
    trade_check_service.check(
        sample_trade.DISCREPANT_LC, sample_trade.DISCREPANT_DOCUMENTS, principal=_PRINCIPAL
    )
    for name, attributes in tracer.spans:
        assert set(attributes) == _ALLOWED[name], name


def test_every_attribute_value_is_a_string(trade_check_service, tracer) -> None:
    """The port declares str values; a structured object smuggles content past a grep."""
    _drive_both_paths(trade_check_service, sample_trade.CLEAN_LC, sample_trade.CLEAN_DOCUMENTS)
    for name, attributes in tracer.spans:
        for key, value in attributes.items():
            assert isinstance(value, str), f"span {name!r} attribute {key!r} is not a str"
