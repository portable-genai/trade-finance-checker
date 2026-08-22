"""Prove every eval metric can go RED: a degraded report must score below its threshold.

A metric that cannot fail proves nothing. Each scorer in ``eval/run_eval.py`` is fed the SAME
discrepancy report twice: once as the checker produced it (green) and once carrying exactly the
defect the metric exists to catch (red). The scorers are imported rather than re-implemented,
so a scorer that silently became a constant 1.0 breaks this build.

Two golden cases are used deliberately. The recall, precision and citation proofs need a
presentation that RAISES discrepancies, because a clean one scores a vacuous 1.0 on all three;
the pii_safety proof needs the case that carries a planted identifier.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from agent_eval_kit import assert_can_go_red
from eval.run_eval import (
    DEFAULT_DATASET,
    THRESHOLDS,
    GoldenExample,
    _build_adapters,
    _make_service,
    check_example,
    load_golden,
    score_citation_accuracy,
    score_pii_safety,
    score_precision,
    score_recall,
)

from trade_finance_checker.domain.models import DiscrepancyKind, DiscrepancyReport

_GOLDEN = load_golden(DEFAULT_DATASET)
#: A presentation with real discrepancies, so recall / precision / citations score something.
_DISCREPANT = next(e for e in _GOLDEN if e.expected_discrepancy_kinds)
#: A presentation carrying a planted identifier, so pii_safety has a target to miss.
_WITH_PII = next(e for e in _GOLDEN if e.pii_in_inputs)


def _run(example: GoldenExample) -> tuple[DiscrepancyReport, list]:
    """Drive the real checker over one golden case; return its report and what it audited."""
    adapters = _build_adapters()
    service = _make_service(adapters)
    before = len(adapters.audit.events)
    report = check_example(service, adapters, example)
    return report, adapters.audit.events[before:]


@pytest.fixture(scope="module")
def discrepant() -> DiscrepancyReport:
    report, _ = _run(_DISCREPANT)
    assert report.discrepancies, "the proof needs a case that actually raises discrepancies"
    return report


def test_discrepancy_recall_can_go_red(discrepant: DiscrepancyReport) -> None:
    assert_can_go_red(
        lambda report: score_recall(report, _DISCREPANT),
        green=discrepant,
        red=replace(discrepant, discrepancies=()),  # the detector stopped detecting
        threshold=THRESHOLDS["discrepancy_recall"],
        metric="discrepancy_recall",
    )


def test_discrepancy_precision_can_go_red(discrepant: DiscrepancyReport) -> None:
    unexpected = next(
        k for k in DiscrepancyKind if k.value not in _DISCREPANT.expected_discrepancy_kinds
    )
    assert_can_go_red(
        lambda report: score_precision(report, _DISCREPANT),
        green=discrepant,
        red=replace(
            discrepant, discrepancies=(replace(discrepant.discrepancies[0], kind=unexpected),)
        ),  # a discrepancy the presentation does not contain
        threshold=THRESHOLDS["discrepancy_precision"],
        metric="discrepancy_precision",
    )


def test_citation_accuracy_can_go_red(discrepant: DiscrepancyReport) -> None:
    assert_can_go_red(
        score_citation_accuracy,
        green=discrepant,
        red=replace(
            discrepant,
            discrepancies=tuple(
                replace(d, citations=(), ucp600_article=None) for d in discrepant.discrepancies
            ),
        ),  # a refusal with no UCP600 article behind it
        threshold=THRESHOLDS["citation_accuracy"],
        metric="citation_accuracy",
    )


def test_pii_safety_can_go_red() -> None:
    """The red case re-introduces a raw identifier into the narrative AFTER redaction ran."""
    report, events = _run(_WITH_PII)
    assert_can_go_red(
        lambda rep: score_pii_safety(rep, _WITH_PII, events),
        green=report,
        red=replace(report, narrative=f"{report.narrative} Applicant NRIC S1234567D on file."),
        threshold=THRESHOLDS["pii_safety"],
        metric="pii_safety",
    )
