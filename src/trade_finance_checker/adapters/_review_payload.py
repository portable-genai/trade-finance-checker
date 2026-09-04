"""Shared conversion from an escalated discrepancy report to an ``review-kit`` Review payload.

Lives in the adapter layer (not the pure domain) because it depends on the kit. Redacts the subject
descriptor, summary and citation snippets before they leave the process (R1 / P-04 boundary), using
the same jurisdiction pattern set the redaction adapter uses (``domain/pii_patterns``), so no raw
trade-party identifier reaches human-review-console over the wire; human-review-console redacts
again before its own audit write (defense in depth). The maker (the checker service that originated
the report) and the tenant are asserted here and trusted by human-review-console because this is an
authenticated S2S caller (per-hop OBO is the deferred next layer).
"""

from __future__ import annotations

import re
from collections.abc import Callable

from review_kit import Citation as KitCitation
from review_kit import Review

from ..domain.models import Citation, DiscrepancyReport, Severity
from ..domain.pii_patterns import NATIONAL_ID_PATTERNS, patterns_for

Validator = Callable[[str], bool]

# Cap the citations carried on the wire: enough to let a reviewer trace the report without copying
# the entire evidence set into the review console.
_MAX_CITATIONS = 8

# The review console is a shared sink: a report for an SG corridor may still quote an HK id, so the
# payload is scrubbed against every jurisdiction's national ids plus universal email/phone/account,
# regardless of which market configured this producer. Rows keep the redaction adapter's shape:
# (info_type, compiled pattern, optional checksum validator).
_ALL_PATTERNS = patterns_for(tuple(NATIONAL_ID_PATTERNS.keys()))

# Ordered weakest -> strongest so ``max`` picks the report's most severe discrepancy.
_SEVERITY_ORDER: tuple[Severity, ...] = (
    Severity.LOW,
    Severity.MEDIUM,
    Severity.HIGH,
    Severity.CRITICAL,
)

# HIGH / CRITICAL findings escalate (mirrors ``TradeReviewPolicy.escalates``); those warrant
# four-eyes dual control on the console.
_ESCALATING: frozenset[Severity] = frozenset({Severity.HIGH, Severity.CRITICAL})


def _redact(text: str) -> str:
    """Mask every jurisdiction's national identifiers plus email/phone/account before the wire.

    Applies each row exactly as the local redaction adapter does: a checksum-gated row masks only
    matches its validator accepts, an ungated row masks on shape. Uses the full pattern set (not
    just the deployment's configured jurisdictions) because the console is a shared sink.
    """
    redacted = text
    for info_type, pattern, validator in _ALL_PATTERNS:
        if validator is None:
            redacted = pattern.sub(f"[{info_type}]", redacted)
        else:

            def _repl(match: re.Match[str], _it: str = info_type, _v: Validator = validator) -> str:
                return f"[{_it}]" if _v(match.group(0)) else match.group(0)

            redacted = pattern.sub(_repl, redacted)
    return re.sub(r"\s+", " ", redacted).strip()


def _overall_severity(report: DiscrepancyReport) -> Severity:
    """The report's most severe discrepancy, or LOW when it carries none."""
    present = [d.severity for d in report.discrepancies if d.severity in _SEVERITY_ORDER]
    if not present:
        return Severity.LOW
    return max(present, key=_SEVERITY_ORDER.index)


def _kit_citations(report: DiscrepancyReport) -> tuple[KitCitation, ...]:
    seen: set[str] = set()
    out: list[KitCitation] = []
    for c in _report_citations(report):
        if c.source_id in seen:
            continue
        seen.add(c.source_id)
        out.append(KitCitation(source_id=c.source_id, title=c.title, snippet=_redact(c.snippet)))
        if len(out) >= _MAX_CITATIONS:
            break
    return tuple(out)


def _report_citations(report: DiscrepancyReport) -> list[Citation]:
    out: list[Citation] = list(report.citations)
    for discrepancy in report.discrepancies:
        out.extend(discrepancy.citations)
    return out


def report_to_review(report: DiscrepancyReport, *, maker: str, tenant: str = "") -> Review:
    """Build the review a producer submits to human-review-console when a discrepancy report
    escalates.
    """
    summary_terms = report.summary
    descriptor = (
        f"Trade-finance discrepancy report for LC {report.lc_number} "
        f"({summary_terms.currency} {summary_terms.amount:.2f}); "
        f"verdict={report.verdict.value}; documents={len(report.documents_checked)}"
    )
    material = sum(1 for d in report.discrepancies if d.is_material)
    summary = (
        f"verdict={report.verdict.value}; discrepancies={len(report.discrepancies)} "
        f"(material={material}); documents_checked={len(report.documents_checked)}"
    )
    severity = _overall_severity(report)
    # Dual control for the strongest bands / any escalating finding (HIGH or CRITICAL).
    dual = severity in _ESCALATING
    return Review(
        action=f"trade_discrepancy_report:{report.verdict.value}",
        subject=_redact(descriptor),
        maker=maker,
        tenant=tenant,
        summary=_redact(summary),
        severity=severity.value,
        required_approvals=2 if dual else 1,
        sod_group="trade-maker-checker",
        case_ref=report.lc_number,
        citations=_kit_citations(report),
    )
