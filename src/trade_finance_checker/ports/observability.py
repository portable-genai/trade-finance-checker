"""Observability ports : the A5 (audit/trace) and A4 (eval gate) concerns.

Primary GCP adapters: **Cloud Logging locked WORM bucket** for immutable audit,
**Cloud Trace via OpenTelemetry** for reasoning-loop traces (message content capture
OFF so PII never reaches a span), and the **Gen AI evaluation service** for the
promotion gate (discrepancy recall/precision, citation accuracy, PII safety).

Two of the three ports here are NOT declared in this file, and that is the point.
``ObservabilityTracerPort`` and ``EvaluationGatePort`` were hand-copied into sixteen
repositories, and by the time anyone compared them they disagreed: one had dropped the eval
port entirely, two had dropped its ``gate`` method (the half that can refuse a promotion), one
returned ``str`` from a ``record`` that returns ``None`` everywhere else. A Protocol copied
into N repos is N Protocols, and only one of them gets fixed when a defect is found. So they
are RE-EXPORTED from the commons that own them, and ``tests/contract/test_port_parity.py``
asserts object identity rather than structural conformance, because ``isinstance`` against a
``runtime_checkable`` Protocol happily accepts a drifted copy.

``AuditSinkPort`` stays declared here, because it is typed in this repo's own vocabulary: it
takes this repo's :class:`~trade_finance_checker.domain.models.AuditEvent`, not a shared one.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agent_eval_kit import EvaluationGatePort as EvaluationGatePort
from hex_service_kit.observability import ObservabilityTracerPort as ObservabilityTracerPort
from hex_service_kit.observability import TokenUsage as TokenUsage

from ..domain.models import AuditEvent


@runtime_checkable
class AuditSinkPort(Protocol):
    def record(self, event: AuditEvent) -> None:
        """Write an immutable, already-redacted audit record (WORM)."""
        ...


__all__ = [
    "AuditSinkPort",
    "EvaluationGatePort",
    "ObservabilityTracerPort",
    "TokenUsage",
]
