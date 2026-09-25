"""The service half of the model pills: which model ANSWERED, and whether it searched.

The console shows two pills at the top right: the model that answered the last request, and
``Search`` when that answer used an online search tool. Both come from response headers the kit
emits (``install_answer_provenance`` in ``api/app.py``) for whatever the LLM adapters NOTED as
they called. Before a request is answered the pill shows ``generator_model`` from ``/healthz``,
so that value must be the model the bound adapter calls, never one a configuration flag names
while the adapter calls another.

No adapter in this checker attaches a search tool, so the Search half is proved by standing a
noting LLM in for the real one on the real route.
"""

from __future__ import annotations

import dataclasses
import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from hex_service_kit import provenance
from tests.conftest import LOOPBACK_PEER

from trade_finance_checker.adapters.gcp.gemini_llm import GeminiLLMAdapter
from trade_finance_checker.adapters.local.llm import LocalDeterministicLLMAdapter
from trade_finance_checker.api import deps
from trade_finance_checker.api.app import app
from trade_finance_checker.config import (
    STUB_GENERATOR_MODEL,
    Container,
    LocalSettings,
    Settings,
)
from trade_finance_checker.domain.kernel import LlmMessage, LlmRequest, LlmResponse

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PRESENTATION = _REPO_ROOT / "eval" / "samples" / "presentation.json"

ANSWERED_BY = "x-answered-by"
SEARCH_USED = "x-search-used"


def _local_container() -> Container:
    base = Settings.load("config/settings.yaml")
    return Container(
        dataclasses.replace(
            base,
            profile="local",
            local=LocalSettings(rules_db_path=":memory:", audit_path=":memory:"),
        )
    )


def _check(monkeypatch: pytest.MonkeyPatch, container: Container) -> Any:
    monkeypatch.setattr(deps, "get_container", lambda: container)
    presentation = json.loads(_PRESENTATION.read_text(encoding="utf-8"))
    response = TestClient(app, client=LOOPBACK_PEER).post("/v1/check", json=presentation)
    assert response.status_code == 200, response.text
    return response


def test_the_check_route_names_the_stub_that_answered_under_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pill's answered value and its configured value are the same word offline."""
    container = _local_container()
    response = _check(monkeypatch, container)
    assert response.headers[ANSWERED_BY] == STUB_GENERATOR_MODEL
    assert container.settings.generator_model == STUB_GENERATOR_MODEL
    assert SEARCH_USED not in response.headers
    # The console calls this service cross-origin, so the two headers must be readable there.
    exposed = response.headers["access-control-expose-headers"].lower()
    assert ANSWERED_BY in exposed and SEARCH_USED in exposed


def test_a_request_no_model_answered_names_no_model() -> None:
    response = TestClient(app, client=LOOPBACK_PEER).get("/healthz")
    assert response.status_code == 200
    assert ANSWERED_BY not in response.headers
    assert SEARCH_USED not in response.headers


class _SearchingLLM(LocalDeterministicLLMAdapter):
    """The real offline generator, plus what an adapter that searched would note."""

    def generate(self, request: LlmRequest) -> LlmResponse:
        response = super().generate(request)
        provenance.note_model("fake-searching-model")
        provenance.note_search()
        return response


def test_a_call_that_searched_is_reported_and_does_not_leak_into_the_next(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = _local_container()
    container.__dict__["llm"] = _SearchingLLM(container.settings)
    response = _check(monkeypatch, container)
    assert response.headers[ANSWERED_BY] == f"{STUB_GENERATOR_MODEL}, fake-searching-model"
    assert response.headers[SEARCH_USED] == "true"

    fresh = _check(monkeypatch, _local_container())
    assert SEARCH_USED not in fresh.headers
    assert fresh.headers[ANSWERED_BY] == STUB_GENERATOR_MODEL


# --------------------------------------------------------------------------- #
# The managed adapter, against a stand-in for the lazily imported SDK.
# --------------------------------------------------------------------------- #
class _Config:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs


class _FakeModels:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def generate_content(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return types.SimpleNamespace(text='{"narrative": "x"}', usage_metadata=None)


def _fake_genai(monkeypatch: pytest.MonkeyPatch) -> None:
    sdk_types = types.SimpleNamespace(
        GenerateContentConfig=_Config,
        ThinkingConfig=lambda **kwargs: kwargs,
        ThinkingLevel=types.SimpleNamespace(LOW="LOW", HIGH="HIGH"),
        Content=lambda **kwargs: kwargs,
        Part=types.SimpleNamespace(from_text=lambda text: text),
    )
    genai = types.ModuleType("google.genai")
    genai.types = sdk_types  # type: ignore[attr-defined]
    google = types.ModuleType("google")
    google.genai = genai  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)


def _gemini(monkeypatch: pytest.MonkeyPatch) -> tuple[GeminiLLMAdapter, _FakeModels, Settings]:
    _fake_genai(monkeypatch)
    settings = dataclasses.replace(Settings.load("config/settings.yaml"), profile="gcp")
    adapter = GeminiLLMAdapter(settings)
    fake = _FakeModels()
    adapter._client = types.SimpleNamespace(models=fake)
    return adapter, fake, settings


def _request(**fields: Any) -> LlmRequest:
    return LlmRequest(messages=(LlmMessage(role="user", content="draft"),), **fields)


def test_the_gemini_adapter_notes_the_model_it_called_which_is_generator_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, fake, settings = _gemini(monkeypatch)
    with provenance.scope() as record:
        adapter.generate(_request())
    assert fake.calls[0]["model"] == settings.generator_model
    assert record.models == [settings.generator_model]
    assert record.search_used is False


def test_a_free_call_sends_no_temperature_and_a_pinned_one_sends_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Free means ABSENT: some models reject the parameter, so it is never sent as 1.0."""
    adapter, fake, _ = _gemini(monkeypatch)
    adapter.generate(_request())
    adapter.generate(_request(temperature=0.0))
    assert "temperature" not in fake.calls[0]["config"].kwargs
    assert fake.calls[1]["config"].kwargs["temperature"] == 0.0


def test_generator_model_is_the_setting_the_adapter_reads_and_no_flag_exists() -> None:
    """The latent false banner: a flag that moved the pill but not the model that answered.

    ``generator_model`` once named ``models.hard_reasoning`` when ``models.use_hard_reasoning``
    was set, while the Gemini adapter called ``request.model or models.reasoning`` and never
    read the flag. The flag is gone, from the settings file and from the source.
    """
    settings = dataclasses.replace(Settings.load("config/settings.yaml"), profile="gcp")
    assert settings.generator_model == settings.models.reasoning
    assert "use_hard_reasoning" not in (_REPO_ROOT / "config" / "settings.yaml").read_text()
    for source in sorted((_REPO_ROOT / "src").rglob("*.py")):
        assert "use_hard_reasoning" not in source.read_text(encoding="utf-8"), source
