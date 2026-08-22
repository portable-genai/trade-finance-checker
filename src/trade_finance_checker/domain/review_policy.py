"""Maker-checker review policy : General Principle P-06.

B4 is a *decision-support* checker, never an autonomous approver of a documentary
presentation. P-06 (maker-checker) requires that a qualified trade-finance officer
reviews the discrepancy report before the bank acts on it (pay, refuse, or seek a
waiver). This module centralises that gate so the rule is auditable in one place.

Policy (SPEC §5):
* A discrepancy report is **always** consequential, so ``requires_human_review`` is
  always ``True`` : the maker (the checker service) proposes, the checker (a human
  officer) disposes.
* Any HIGH / CRITICAL discrepancy *escalates* (raises the audit decision to
  ESCALATED) so high-stakes findings are surfaced for urgent attention.
* The verdict is COMPLIANT iff zero **material** discrepancies were found; a single
  material discrepancy makes the presentation DISCREPANT.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import ComplianceVerdict, Discrepancy, Severity

#: Severities considered high-stakes enough to escalate a report.
_ESCALATING: frozenset[Severity] = frozenset({Severity.HIGH, Severity.CRITICAL})


@dataclass(frozen=True, slots=True)
class TradeReviewPolicy:
    """Maker-checker gate (P-06) for trade-finance discrepancy reports.

    Pure decision logic; no side effects. A discrepancy report is consequential and
    therefore always requires human review.
    """

    def requires_review(self, discrepancies: tuple[Discrepancy, ...]) -> bool:
        """A discrepancy report is consequential and always requires human review."""
        return True

    def verdict(self, discrepancies: tuple[Discrepancy, ...]) -> ComplianceVerdict:
        """COMPLIANT iff there are zero material discrepancies, else DISCREPANT."""
        if any(d.is_material for d in discrepancies):
            return ComplianceVerdict.DISCREPANT
        return ComplianceVerdict.COMPLIANT

    def escalates(self, discrepancies: tuple[Discrepancy, ...]) -> bool:
        """Whether any discrepancy is severe enough to escalate (HIGH / CRITICAL)."""
        return any(d.severity in _ESCALATING for d in discrepancies)
