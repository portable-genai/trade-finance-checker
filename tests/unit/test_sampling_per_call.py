"""Sampling is decided per call: pinned where the output is compared, free where it is prose.

This file used to assert the opposite default. On 2026-08-26 two runs of one identical case
against the `cdd-sow-research` deployment returned different scores minutes apart, because the
shared request builder defaulted to `temperature=0.2` and every grounded call sampled. The fix
pinned 0.0 on the type, which made every call reproducible and every drafted narrative flat.

The owner's rule (2026-09-23) replaces it: temperature is PINNED at 0.0 only where
reproducibility matters (extraction, classification, scoring, anything compared against a
deterministic check) and FREE elsewhere, where free means the parameter is not sent at all,
because Opus 5 and Fable 5 reject it. So the type and the builder default to `None`, and each
call site that needs a pin says so where it is made.

In this checker the verdict and the discrepancy set are the deterministic detector's. The only
generation call drafts the examiner narrative, so it runs free; the triage `classify` stays
pinned in both model adapters.

**Temperature 0 is not a promise of determinism, and nothing here asserts one.**
"""

from __future__ import annotations

import inspect

from tests.fixtures import sample_trade

from trade_finance_checker.domain import _grounded
from trade_finance_checker.domain.identity import Principal
from trade_finance_checker.domain.kernel import LlmRequest

PRINCIPAL = Principal(
    subject="officer@bank.test", principals=("group:trade-analyst",), tenant="demo-bank"
)


def test_the_request_type_and_builder_leave_sampling_free_by_default() -> None:
    assert LlmRequest.__dataclass_fields__["temperature"].default is None
    signature = inspect.signature(_grounded.build_llm_request)
    assert signature.parameters["temperature"].default is None


def test_the_narrative_draft_sends_no_temperature(trade_check_service, llm) -> None:
    """Drafting is free: the narrative is prose over findings the detector already decided."""
    trade_check_service.check(
        sample_trade.DISCREPANT_LC, sample_trade.DISCREPANT_DOCUMENTS, principal=PRINCIPAL
    )
    assert llm.requests, "the check drafted no narrative, so this asserts nothing"
    assert all(request.temperature is None for request in llm.requests)


def test_classification_stays_pinned_in_both_model_adapters() -> None:
    """Triage labels are compared against a fixed set, so they are pinned at 0.0."""
    from trade_finance_checker.adapters.gcp import gemini_llm
    from trade_finance_checker.adapters.live import llm as live_llm

    gemini = inspect.getsource(gemini_llm.GeminiLLMAdapter.classify)
    live = inspect.getsource(live_llm.LocalModelLLMAdapter.classify)
    assert "temperature=0.0" in gemini
    assert "temperature=0.0" in live
