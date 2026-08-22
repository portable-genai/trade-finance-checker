"""Pytest fixtures: the ``local`` adapters (seeded) + the assembled domain service.

The unit suite is driven by the **real** ``local`` adapter family
(``src/trade_finance_checker/adapters/local``) rather than bespoke in-memory fakes, so the
offline implementation lives in exactly one place and the tests exercise the same code the
offline CLI runs. Every adapter constructs with a single ``Settings`` (the adapter
convention) pointed at ``:memory:`` SQLite, and the rules index is seeded with the
synthetic ``tests/fixtures/sample_trade.SAMPLE_RULES`` set for determinism.

A few fixtures wrap the local adapter in a thin **recording** subclass that captures call
arguments for assertions (``.calls`` / ``.requests`` / ``.spans`` / ``.events``). These add
no behaviour: every method delegates to the real local adapter, so the in-memory
implementation is still the one under ``adapters/local``. The recorders are the test
instrumentation the previous bespoke fakes used to bundle.

``BlockingGuardrail`` is retained as a tiny test double (not a registered adapter) for the
two blocked-path tests that force a block on a specific direction; the default
``guardrail`` fixture is the real local heuristic, which blocks malicious text and allows
benign text deterministically.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest

from tests.fixtures import sample_trade
from trade_finance_checker.adapters.local.audit import LocalAppendOnlyAuditAdapter
from trade_finance_checker.adapters.local.entitlements import LocalAclAdapter
from trade_finance_checker.adapters.local.evaluation import LocalOfflineEvalAdapter
from trade_finance_checker.adapters.local.extraction import LocalDocumentExtractionAdapter
from trade_finance_checker.adapters.local.guardrail import LocalHeuristicGuardrailAdapter
from trade_finance_checker.adapters.local.llm import LocalDeterministicLLMAdapter
from trade_finance_checker.adapters.local.memory import LocalMemoryAdapter
from trade_finance_checker.adapters.local.redaction import LocalRegexRedactionAdapter
from trade_finance_checker.adapters.local.registry import LocalRegistryAdapter
from trade_finance_checker.adapters.local.rules import LocalFtsRulesAdapter
from trade_finance_checker.adapters.local.runtime import LocalAgentRuntimeAdapter
from trade_finance_checker.adapters.local.session import LocalSessionAdapter
from trade_finance_checker.adapters.local.tool_catalog import LocalToolCatalogAdapter
from trade_finance_checker.adapters.local.tracer import LocalNoopTracerAdapter
from trade_finance_checker.config import LocalSettings, Settings
from trade_finance_checker.domain.models import (
    AuditEvent,
    Direction,
    DocumentExtract,
    GuardrailCategory,
    GuardrailFinding,
    GuardrailVerdict,
    LlmRequest,
    LlmResponse,
    PresentedDocument,
    Ucp600Rule,
)

#: A loopback peer for every ``TestClient`` in the suite. The app-object exposure guard
#: refuses a posture that authenticates no end user to any non-loopback peer, and
#: ``TestClient``'s DEFAULT peer is the literal host ``"testclient"``, which is not a loopback
#: address and is refused with a 503. Passing this is how a test says "this request came from
#: the developer's own machine", which is what every one of these tests is really modelling;
#: it is NOT a way to opt out of the guard (``tests/unit/test_serving_path_exposure.py`` holds
#: the guard to both directions).
LOOPBACK_PEER = ("127.0.0.1", 50000)


def _settings() -> Settings:
    """Settings whose local stores are ephemeral in-memory SQLite (deterministic)."""
    return Settings(
        profile="local",
        local=LocalSettings(rules_db_path=":memory:", audit_path=":memory:"),
    )


# --------------------------------------------------------------------------- #
# Recording wrappers : thin subclasses of the local adapters that capture call
# arguments for assertions. Every method delegates to the real local adapter.
# --------------------------------------------------------------------------- #
class RecordingExtraction(LocalDocumentExtractionAdapter):
    """Local document extraction that records the documents it received."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.calls: list[PresentedDocument] = []

    def extract(self, document: PresentedDocument) -> DocumentExtract:
        self.calls.append(document)
        return super().extract(document)


class RecordingRules(LocalFtsRulesAdapter):
    """Local FTS5 rules retrieval that records the queries it received."""

    def __init__(self, settings: Settings, rules: list[Ucp600Rule] | None = None) -> None:
        super().__init__(settings)
        # Re-seed the in-memory index with the test rule set for determinism.
        self.seed(list(sample_trade.SAMPLE_RULES) if rules is None else list(rules))
        self.calls: list[str] = []

    def retrieve_rules(self, query: str, top_k: int = 8) -> list[Ucp600Rule]:
        self.calls.append(query)
        return super().retrieve_rules(query, top_k=top_k)


class RecordingLLM(LocalDeterministicLLMAdapter):
    """Local deterministic LLM that records the requests it received."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.requests: list[LlmRequest] = []
        self.classify_calls: list[tuple[str, list[str]]] = []

    def generate(self, request: LlmRequest) -> LlmResponse:
        self.requests.append(request)
        return super().generate(request)

    def classify(self, text: str, labels: list[str]) -> str:
        self.classify_calls.append((text, labels))
        return super().classify(text, labels)


class RecordingRedaction(LocalRegexRedactionAdapter):
    """Local regex redaction that records the raw text it was asked to redact."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.calls: list[str] = []

    def redact(self, text: str):  # type: ignore[no-untyped-def]
        self.calls.append(text)
        return super().redact(text)


class RecordingTracer(LocalNoopTracerAdapter):
    """Local no-op tracer that records the span names it opened."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.spans: list[str] = []

    def span(self, name: str, **attributes: str):  # type: ignore[no-untyped-def]
        self.spans.append(name)
        return super().span(name, **attributes)


class RecordingGuardrail(LocalHeuristicGuardrailAdapter):
    """Local heuristic guardrail that records the (text, direction) screen calls.

    Behaviour is the real heuristic: benign text passes, malicious text (e.g.
    ``sample_trade.MALICIOUS_LC``'s goods description) is blocked. Only the recording added.
    """

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.calls: list[tuple[str, Direction]] = []

    def screen(self, text: str, direction: Direction):  # type: ignore[no-untyped-def]
        self.calls.append((text, direction))
        return super().screen(text, direction)


class RecordingAudit(LocalAppendOnlyAuditAdapter):
    """Local append-only audit that also keeps the AuditEvent objects for assertions."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.events: list[AuditEvent] = []

    def record(self, event: AuditEvent) -> None:
        self.events.append(event)
        super().record(event)


class BlockingGuardrail:
    """Forces a block on a chosen direction; a tiny test double for the blocked-path tests.

    The real local heuristic blocks on injection text, not on an arbitrary direction, so
    the two tests that need a guaranteed INPUT (or OUTPUT) block use this double rather than
    crafting text. It is deliberately not a registered adapter (takes no ``Settings``).
    """

    def __init__(self, block_input: bool = True, block_output: bool = False) -> None:
        self.block_input = block_input
        self.block_output = block_output
        self.calls: list[tuple[str, Direction]] = []

    def screen(self, text: str, direction: Direction) -> GuardrailVerdict:
        self.calls.append((text, direction))
        blocked = (direction is Direction.INPUT and self.block_input) or (
            direction is Direction.OUTPUT and self.block_output
        )
        return GuardrailVerdict(
            allowed=not blocked,
            direction=direction,
            findings=(
                (
                    GuardrailFinding(
                        category=GuardrailCategory.PROMPT_INJECTION,
                        confidence="high",
                        detail="prompt injection detected",
                    ),
                )
                if blocked
                else ()
            ),
            sanitized_text=None if blocked else text,
            reason="blocked by guardrail" if blocked else "ok",
        )


# --------------------------------------------------------------------------- #
# Service construction : locate the domain service class wherever it lives.
# --------------------------------------------------------------------------- #
_SERVICE_MODULE_CANDIDATES = (
    "trade_finance_checker.domain.trade_check_service",
    "trade_finance_checker.domain.services",
)


def _resolve(symbol: str, candidates: tuple[str, ...]) -> Any:
    last: Exception | None = None
    for mod_name in candidates:
        try:
            module = importlib.import_module(mod_name)
        except ModuleNotFoundError as exc:  # pragma: no cover - layout fallback
            last = exc
            continue
        obj = getattr(module, symbol, None)
        if obj is not None:
            return obj
    raise ImportError(f"Could not locate domain symbol {symbol!r} in any of {candidates}") from last


def load_service(name: str) -> Any:
    return _resolve(name, _SERVICE_MODULE_CANDIDATES)


# --------------------------------------------------------------------------- #
# Pytest fixtures : construct the (seeded) local adapters.
# --------------------------------------------------------------------------- #
@pytest.fixture
def extraction() -> RecordingExtraction:
    return RecordingExtraction(_settings())


@pytest.fixture
def rules() -> RecordingRules:
    return RecordingRules(_settings())


@pytest.fixture
def llm() -> RecordingLLM:
    return RecordingLLM(_settings())


@pytest.fixture
def guardrail() -> RecordingGuardrail:
    """The real local heuristic guardrail, instrumented to record screen calls."""
    return RecordingGuardrail(_settings())


@pytest.fixture
def blocking_guardrail() -> BlockingGuardrail:
    return BlockingGuardrail()


@pytest.fixture
def redaction() -> RecordingRedaction:
    return RecordingRedaction(_settings())


@pytest.fixture
def tracer() -> RecordingTracer:
    return RecordingTracer(_settings())


@pytest.fixture
def audit() -> RecordingAudit:
    return RecordingAudit(_settings())


@pytest.fixture
def session() -> LocalSessionAdapter:
    return LocalSessionAdapter(_settings())


@pytest.fixture
def memory() -> LocalMemoryAdapter:
    return LocalMemoryAdapter(_settings())


@pytest.fixture
def agent_runtime() -> LocalAgentRuntimeAdapter:
    return LocalAgentRuntimeAdapter(_settings())


@pytest.fixture
def evaluation() -> LocalOfflineEvalAdapter:
    return LocalOfflineEvalAdapter(_settings())


@pytest.fixture
def registry() -> LocalRegistryAdapter:
    return LocalRegistryAdapter(_settings())


@pytest.fixture
def tool_catalog() -> LocalToolCatalogAdapter:
    return LocalToolCatalogAdapter(_settings())


@pytest.fixture
def acl() -> LocalAclAdapter:
    """The real local seeded owner registry (demo-bank owns the sample-trade LC ids)."""
    return LocalAclAdapter(_settings())


@pytest.fixture
def trade_check_service(extraction, rules, llm, guardrail, redaction, tracer, audit, acl):
    """TradeCheckService(extraction, rules, llm, guardrail, redaction, tracer, audit, acl)."""
    cls = load_service("TradeCheckService")
    return cls(extraction, rules, llm, guardrail, redaction, tracer, audit, acl)
