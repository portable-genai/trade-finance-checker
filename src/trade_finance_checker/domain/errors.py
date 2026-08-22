"""Domain exceptions for the Trade-Finance Document Checker (system B4).

Pure-Python exception hierarchy raised by the orchestration service. The domain layer
never imports Google Cloud, ADK, or any framework : these errors let callers (API,
CLI, the Agent Runtime adapter) react to domain-level failures without coupling to any
vendor SDK error type.
"""

from __future__ import annotations


class TradeFinanceError(Exception):
    """Base class for all domain-level errors raised by B4 services."""


class GuardrailBlockedError(TradeFinanceError):
    """Raised/flagged when the A1 guardrail blocks an input or output.

    The check pipeline degrades gracefully on a guardrail block (returns a blocked,
    human-review-flagged report rather than a partial artifact), but this error lets a
    caller that requires a hard stop short-circuit a blocked unsafe presentation.
    """


class ExtractionFailedError(TradeFinanceError):
    """Raised when a presented document (or the LC) could not be parsed.

    A presentation cannot be examined without the structured fields of its documents,
    so an extraction failure is a hard error rather than a silent empty extract.
    """


class RulesUnavailableError(TradeFinanceError):
    """Raised when the governed UCP600 rule set could not be retrieved (A2).

    UCP600-article-tagged checks need the governed rule set. When it is unavailable the
    service emits no report, so an apparently compliant result can never be ungrounded.
    """


class AccessDenied(TradeFinanceError):
    """Raised when a verified principal is not entitled to the object it named.

    Object-level authorization is decided server-side against the AclPort owner registry
    (see ``domain/entitlements.py``), keyed by object id, never from the client-submitted
    Letter of Credit (which is spoofable). A failed, fail-closed check maps to HTTP 403 at
    the API layer; the CLI/agent surface it as an access error. Raised BEFORE any
    extraction, model call, or audit write, so a denied request produces no artifact.
    """
