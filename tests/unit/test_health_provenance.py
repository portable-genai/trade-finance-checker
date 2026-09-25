"""The model pill's configured state: this service names its runtime and its model.

Every served UI in the fleet shows, at the top right of every page, the model that answered
the last request; before any answer it shows the model the bound generator calls, with
where it runs in the pill's title (owner decision, 2026-09-23). The console must never
infer either. A page that read its runtime from ``window.location`` would be right until
the deployment served through a proxy, and wrong silently after that; a page that
hard-coded a model name would keep printing it after the binding changed.

So the service answers, and the answer is DERIVED rather than kept as a second field
someone has to remember to update. That is what these tests pin.
"""

from __future__ import annotations

import dataclasses

import pytest
from hex_service_kit.localmodel import DEFAULT_LOCAL_MODEL

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

    The pill's title states WHERE the process runs, and its text states WHOSE model
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


def test_live_names_the_shared_local_model_that_answers(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Under ``live`` the pill names the local model build, not the word "local".

    The laptop lane calls the fleet's one local model through the kit client, so the pill
    reads the model that client will call: ``LOCAL_MODEL`` when set, the fleet default when
    not. An operator who pointed ``LOCAL_MODEL`` at a different build needs the page to say
    which one answered, and a pill reading "local" would hide exactly that.
    """
    live = dataclasses.replace(settings, profile="live")
    assert live.runtime == "local"

    monkeypatch.delenv("LOCAL_MODEL", raising=False)
    assert live.generator_model == DEFAULT_LOCAL_MODEL
    assert "gemma" in live.generator_model.lower()

    monkeypatch.setenv("LOCAL_MODEL", "example-org/another-local-build")
    assert live.generator_model == "example-org/another-local-build"
