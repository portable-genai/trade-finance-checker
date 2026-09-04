"""ReviewRouterPort: the boundary that routes an escalated discrepancy report to
human-review-console (rule R8).

Every discrepancy report is consequential decision-support and always requires human review
(maker-checker, P-06): the checker service is the maker, a qualified trade-finance officer is the
checker. Rule R8 says a producer that sets ``requires_human_review`` MUST route the item to the
human-review-console Human-Review & Maker-Checker Console rather than terminate the escalation in a
per-repo boolean. This port is that hand-off. The domain stays pure: the adapter (not this port)
depends on the shared ``review-kit`` client and does the S2S submission.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import DiscrepancyReport


@runtime_checkable
class ReviewRouterPort(Protocol):
    def route(self, report: DiscrepancyReport, *, maker: str, tenant: str = "") -> None:
        """Route an escalated report to human-review-console for human review (idempotent per LC is
        ideal).
        """
        ...
