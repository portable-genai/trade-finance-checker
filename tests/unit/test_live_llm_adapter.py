"""The ``live`` profile's model adapter, driven offline through a fake transport.

The laptop ``live`` lane reaches the fleet's shared local model through the kit client
(:mod:`hex_service_kit.localmodel`). These tests hand that client a fake transport, so they
exercise the real message assembly, schema retry and response mapping with no model server,
and they pin the other half of the lane: every port builds under ``live``.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

import pytest
from hex_service_kit.localmodel import (
    LocalModelClient,
    LocalModelOutputError,
    LocalModelSettings,
    LocalModelUnavailable,
)

from trade_finance_checker import config
from trade_finance_checker.adapters.live.llm import LocalModelLLMAdapter
from trade_finance_checker.config import LocalSettings, Settings, build_container
from trade_finance_checker.domain.models import LlmMessage, LlmRequest, TokenUsage

CONFIG_PATH = "config/settings.yaml"

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"narrative": {"type": "string"}},
    "required": ["narrative"],
}


class _FakeTransport:
    """Answers each POST with the next scripted reply and records every request body."""

    def __init__(self, *replies: str, model: str = "fake/answering-model", usage: Any = None):
        self._replies = list(replies)
        self._model = model
        self._usage = usage
        self.bodies: list[dict[str, Any]] = []

    def __call__(self, url: str, body: bytes | None, timeout: float) -> bytes:
        assert body is not None
        self.bodies.append(json.loads(body))
        content = self._replies.pop(0)
        answer: dict[str, Any] = {
            "model": self._model,
            "choices": [{"message": {"role": "assistant", "content": content}}],
        }
        if self._usage is not None:
            answer["usage"] = self._usage
        return json.dumps(answer).encode()


def _adapter(transport: Any) -> LocalModelLLMAdapter:
    client = LocalModelClient(LocalModelSettings(), transport=transport)
    return LocalModelLLMAdapter(Settings(profile="live"), client=client)


def _request(**overrides: Any) -> LlmRequest:
    fields: dict[str, Any] = {
        "messages": (LlmMessage(role="user", content="Draft the examiner narrative."),),
        "system_instruction": "You are a documentary-credit examiner.",
        "temperature": 0.0,
        "max_output_tokens": 512,
        "response_schema": _SCHEMA,
    }
    fields.update(overrides)
    return LlmRequest(**fields)


def test_a_fenced_invalid_first_answer_is_retried_and_the_valid_one_returned() -> None:
    transport = _FakeTransport(
        '```json\n{"summary": "wrong field"}\n```',
        '```json\n{"narrative": "Two discrepancies under Article 14."}\n```',
    )
    response = _adapter(transport).generate(_request())

    assert json.loads(response.text) == {"narrative": "Two discrepancies under Article 14."}
    assert response.model == "fake/answering-model"
    assert len(transport.bodies) == 2
    retry_turn = transport.bodies[1]["messages"][-1]["content"]
    assert "narrative" in retry_turn, "the schema problem must be fed back to the model"
    # The system instruction and the schema share the one system turn.
    system = transport.bodies[0]["messages"][0]
    assert system["role"] == "system"
    assert "documentary-credit examiner" in system["content"]
    assert '"required": ["narrative"]' in system["content"]


def test_an_answer_that_never_validates_raises_the_kit_output_error() -> None:
    transport = _FakeTransport("not json", "still not json", "{}")
    with pytest.raises(LocalModelOutputError):
        _adapter(transport).generate(_request())
    assert len(transport.bodies) == 3


def test_the_request_temperature_and_token_budget_pass_through_unchanged() -> None:
    transport = _FakeTransport("A plain narrative.")
    response = _adapter(transport).generate(
        _request(response_schema=None, temperature=0.7, max_output_tokens=321)
    )

    assert response.text == "A plain narrative."
    body = transport.bodies[0]
    assert body["temperature"] == 0.7
    assert body["max_tokens"] == 321
    assert [m["role"] for m in body["messages"]] == ["system", "user"]


def test_model_turns_become_assistant_turns() -> None:
    transport = _FakeTransport("ok")
    _adapter(transport).generate(
        _request(
            response_schema=None,
            messages=(
                LlmMessage(role="user", content="first"),
                LlmMessage(role="model", content="reply"),
                LlmMessage(role="user", content="second"),
            ),
        )
    )
    roles = [m["role"] for m in transport.bodies[0]["messages"]]
    assert roles == ["system", "user", "assistant", "user"]


def test_usage_is_carried_when_reported_and_zero_only_because_the_type_requires_one() -> None:
    reported = _FakeTransport("ok", usage={"input_tokens": 11, "output_tokens": 7})
    assert _adapter(reported).generate(_request(response_schema=None)).usage == TokenUsage(11, 7)

    silent = _FakeTransport("ok")
    assert _adapter(silent).generate(_request(response_schema=None)).usage == TokenUsage()


def test_classify_coerces_the_answer_onto_a_label() -> None:
    transport = _FakeTransport("The label is invoice.")
    assert _adapter(transport).classify("Commercial invoice no. 1", ["transport", "invoice"]) == (
        "invoice"
    )
    assert transport.bodies[0]["temperature"] == 0.0


def test_an_unreachable_server_raises_the_kit_unavailable_error() -> None:
    def refuse(url: str, body: bytes | None, timeout: float) -> bytes:
        raise OSError("connection refused")

    with pytest.raises(LocalModelUnavailable, match="Start a local model server"):
        _adapter(refuse).generate(_request())


def test_the_container_builds_every_port_under_live() -> None:
    base = Settings.load(CONFIG_PATH)
    settings = dataclasses.replace(
        base,
        profile="live",
        profile_explicit=True,
        local=LocalSettings(rules_db_path=":memory:", audit_path=":memory:"),
    )
    container = build_container(settings)

    for port_name in settings.adapters:
        assert getattr(container, port_name) is not None, port_name
    assert isinstance(container.llm, LocalModelLLMAdapter)
    assert "live" in config.RUNTIME_PROFILES
