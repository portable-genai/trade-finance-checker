"""Aggregator re-exporting the orchestration service and policies.

The service lives in its own module (``trade_check_service``) so it stays focused; this
module is the single import surface the wiring layers (``api.deps``, ``agent.tools``,
``cli``) use, so they never need to know which module the service lives in.
"""

from __future__ import annotations

from .detector import DiscrepancyDetector
from .review_policy import TradeReviewPolicy
from .trade_check_service import TradeCheckService

__all__ = [
    "TradeCheckService",
    "DiscrepancyDetector",
    "TradeReviewPolicy",
]
