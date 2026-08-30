"""The banner's server half: this service names its runtime and its model.

Every served UI in the fleet states, at the top of every page, where it is running and
which model answers (org decision, 2026-08-30). The console must never infer either. A
page that read its runtime from ``window.location`` would be right until the deployment
served through a proxy, and wrong silently after that; a page that hard-coded a model name
would keep printing it after the binding changed.

So the service answers, and the answer is DERIVED rather than kept as a second field
someone has to remember to update. That is what these tests pin.
"""

from __future__ import annotations

import dataclasses

import pytest

from trade_finance_checker.config import Settings

CONFIG_PATH = "config/settings.yaml"


@pytest.fixture
def settings() -> Settings:
    return Settings.load(CONFIG_PATH)


@pytest.mark.parametrize(
    ("profile", "expected"),
    [
        ("local", "local"),
        ("live", "local"),
        ("gcp", "gcp"),
        ("platform", "gcp"),
        ("onprem", "local"),
    ],
)
def test_the_runtime_says_where_the_process_runs_not_whose_model_it_calls(
    settings: Settings, profile: str, expected: str
) -> None:
    """``onprem`` reads ``local``, and there that is the whole selling point.

    The banner states WHERE the process runs, and the model half states WHOSE model
    answers, precisely so the two facts cannot be collapsed into one misleading sentence.
    """
    assert dataclasses.replace(settings, profile=profile).runtime == expected


@pytest.mark.parametrize(
    ("profile", "expected"),
    [
        ("local", "deterministic-offline-stub"),
        ("gcp", "gemini-3.5-flash"),
        ("platform", "gemini-3.5-flash"),
        ("onprem", "onprem-not-implemented"),
    ],
)
def test_the_model_answers_what_the_profile_actually_binds(
    settings: Settings, profile: str, expected: str
) -> None:
    assert dataclasses.replace(settings, profile=profile).generator_model == expected


def test_the_one_tree_that_kept_its_local_model_names_the_build_that_answered(
    settings: Settings,
) -> None:
    """This checker is the exception to the 2026-08-30 Gemini-only sweep, on purpose.

    The five outbound-grounded systems dropped their local models because a use case that
    needs internet research is only ever implemented for customers who permit leaving the
    data centre. On-prem is THIS system's entire point, so it keeps its Gemma build and
    the banner has to say so: the whole value of the banner here is that a viewer looking
    at a checked presentation learns the answer came from a model on this machine.

    It names the configured BUILD, not the word "local". An operator who pointed
    TRADE_FINANCE_LIVE_LLM_URL at a different model needs the page to say which one
    answered, and a banner reading "model local" would hide exactly that.
    """
    live = dataclasses.replace(settings, profile="live")

    assert live.runtime == "local"
    assert live.generator_model == settings.live.llm_model
    assert "gemma" in live.generator_model.lower()
