"""Unit tests for serialization, Settings.load, and Container wiring.

* domain/serialization.to_jsonable round-trips enums (-> .value) and datetimes.
* Settings.load parses config/settings.yaml.
* Container under profile=onprem binds the on-prem placeholder adapters, and each bound
  adapter satisfies its runtime_checkable Protocol (structural parity).
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from trade_finance_checker import ports
from trade_finance_checker.config import CheckSettings, Container, LocalSettings, Settings
from trade_finance_checker.domain.models import (
    AuditEvent,
    Citation,
    CitationType,
    ComplianceVerdict,
    Decision,
    DiscrepancyKind,
    Severity,
    TradeDocType,
)
from trade_finance_checker.envread import ConfiguredEmptyError

CONFIG_PATH = "config/settings.yaml"

PORT_PROTOCOLS = {
    "extraction": ports.DocumentExtractionPort,
    "rules": ports.RulesRetrievalPort,
    "llm": ports.LLMPort,
    "guardrail": ports.GuardrailPort,
    "redaction": ports.PIIRedactionPort,
    "agent_runtime": ports.AgentRuntimePort,
    "session": ports.SessionPort,
    "memory": ports.MemoryPort,
    "audit": ports.AuditSinkPort,
    "tracer": ports.ObservabilityTracerPort,
    "evaluation": ports.EvaluationGatePort,
    "registry": ports.AgentRegistryPort,
    "tool_catalog": ports.ToolCatalogPort,
}


# --------------------------------------------------------------------------- #
# to_jsonable
# --------------------------------------------------------------------------- #
def _to_jsonable():
    from trade_finance_checker.domain.serialization import to_jsonable

    return to_jsonable


def test_to_jsonable_enum_becomes_value():
    to_jsonable = _to_jsonable()
    assert to_jsonable(ComplianceVerdict.DISCREPANT) == "discrepant"
    assert to_jsonable(Severity.HIGH) == "high"
    assert to_jsonable(Decision.BLOCKED) == "blocked"
    assert to_jsonable(DiscrepancyKind.AMOUNT_MISMATCH) == "amount_mismatch"


def test_to_jsonable_datetime_is_json_safe_string():
    to_jsonable = _to_jsonable()
    dt = datetime(2026, 6, 20, 8, 30, tzinfo=UTC)
    out = to_jsonable(dt)
    assert isinstance(out, str)
    assert json.loads(json.dumps(out)) == out
    assert "2026-06-20" in out


def test_to_jsonable_citation_roundtrips_through_json():
    to_jsonable = _to_jsonable()
    citation = Citation(
        source_id="UCP600 Art. 18",
        source_type=CitationType.UCP600,
        title="Commercial invoice",
        url="https://example.test/ucp600/art18",
    )
    out = to_jsonable(citation)
    assert isinstance(out, dict)
    assert out["source_type"] == "UCP600"
    text = json.dumps(out)
    assert json.loads(text)["source_id"] == "UCP600 Art. 18"


def test_to_jsonable_audit_event_is_worm_serialisable():
    to_jsonable = _to_jsonable()
    event = AuditEvent(
        action="check",
        actor="officer",
        decision=Decision.ESCALATED,
        redacted_prompt="LC [NRIC]",
        redacted_response="discrepant",
        citations=(Citation(source_id="LC-1", source_type=CitationType.LC, title="LC term"),),
    )
    out = to_jsonable(event)
    reloaded = json.loads(json.dumps(out))
    assert reloaded["decision"] == "escalated"
    assert reloaded["action"] == "check"
    assert reloaded["citations"][0]["source_type"] == "LC"


# --------------------------------------------------------------------------- #
# Settings.load parses config/settings.yaml
# --------------------------------------------------------------------------- #
def test_settings_load_parses_yaml():
    settings = Settings.load(CONFIG_PATH)
    assert settings.region == "asia-southeast1"
    assert settings.models.reasoning == "gemini-3.5-flash"
    assert settings.models.triage == "gemini-3.1-flash-lite"
    assert settings.rules_kb.collection == "ucp600-rules"
    assert set(PORT_PROTOCOLS) <= set(settings.adapters)


def test_settings_pins_models_to_allowed_ids():
    settings = Settings.load(CONFIG_PATH)
    assert settings.models.reasoning != "gemini-2.0-flash"
    assert settings.models.triage != "gemini-2.0-flash"
    assert settings.models.reasoning.startswith("gemini-3")


def test_logging_retention_is_seven_years():
    settings = Settings.load(CONFIG_PATH)
    assert settings.logging.retention_days == 2557


def test_composition_root_threads_detector_policy(monkeypatch):
    from trade_finance_checker.api.deps import build_trade_check_service

    monkeypatch.setenv("TRADE_FINANCE_PROFILE", "local")
    settings = replace(
        Settings.load(CONFIG_PATH),
        profile="local",
        profile_explicit=True,
        local=LocalSettings(rules_db_path=":memory:", audit_path=":memory:"),
        check=CheckSettings(amount_tolerance_pct=0.17, description_min_overlap=0.81),
    )
    service = build_trade_check_service(Container(settings))
    assert service._detector.amount_tolerance_pct == 0.17
    assert service._detector.description_min_overlap == 0.81


# --------------------------------------------------------------------------- #
# Container binds on-prem adapters under profile=onprem, with structural parity.
# --------------------------------------------------------------------------- #
def _onprem_settings() -> Settings:
    settings = Settings.load(CONFIG_PATH)
    return Settings(
        project_id=settings.project_id,
        region=settings.region,
        profile="onprem",
        kms_key=settings.kms_key,
        models=settings.models,
        document_ai=settings.document_ai,
        rules_kb=settings.rules_kb,
        model_armor=settings.model_armor,
        dlp=settings.dlp,
        logging=settings.logging,
        agent_engine=settings.agent_engine,
        check=settings.check,
        adapters=settings.adapters,
    )


def test_container_binds_onprem_adapters_with_protocol_parity():
    container = Container(_onprem_settings())
    for port_name, protocol in PORT_PROTOCOLS.items():
        adapter = getattr(container, port_name)
        assert isinstance(adapter, protocol), (
            f"on-prem adapter for '{port_name}' is not structurally a {protocol.__name__}"
        )


def test_container_refuses_a_missing_profile_binding():
    settings = _onprem_settings()
    adapters = {name: dict(binding) for name, binding in settings.adapters.items()}
    adapters["guardrail"].pop("onprem")
    incomplete = Settings(
        project_id=settings.project_id,
        region=settings.region,
        profile="onprem",
        kms_key=settings.kms_key,
        models=settings.models,
        document_ai=settings.document_ai,
        rules_kb=settings.rules_kb,
        model_armor=settings.model_armor,
        dlp=settings.dlp,
        logging=settings.logging,
        agent_engine=settings.agent_engine,
        check=settings.check,
        adapters=adapters,
    )
    with pytest.raises(KeyError, match="under profile 'onprem'"):
        _ = Container(incomplete).guardrail


def test_doc_type_enum_covers_all_brief_kinds():
    values = {d.value for d in TradeDocType}
    assert {
        "invoice",
        "bill_of_lading",
        "insurance",
        "packing_list",
        "cert_origin",
        "draft",
        "other",
    } <= values


def test_env_default_applies_only_when_the_variable_is_unset(monkeypatch) -> None:
    from trade_finance_checker.config import _interpolate

    monkeypatch.setenv("TFC_TEST_VAR", "")
    with pytest.raises(ConfiguredEmptyError, match="TFC_TEST_VAR"):
        _interpolate("${TFC_TEST_VAR:-fallback}")
    with pytest.raises(ConfiguredEmptyError, match="TFC_TEST_VAR"):
        _interpolate("${TFC_TEST_VAR}")

    monkeypatch.setenv("TFC_TEST_VAR", "real")
    assert _interpolate("${TFC_TEST_VAR:-fallback}") == "real"

    monkeypatch.delenv("TFC_TEST_VAR")
    assert _interpolate("${TFC_TEST_VAR:-fallback}") == "fallback"


def test_empty_pii_jurisdictions_env_is_refused_end_to_end(monkeypatch, tmp_path) -> None:
    """The end-to-end consequence, on the setting that motivated the rule above.

    Was: an emptied variable quietly inherited the shipped pack. Now it refuses, so the two
    ways of naming no jurisdiction (`""` and `","`) land in the same place instead of one
    inheriting the default and the other silently disabling every national-id row.
    """
    from hex_service_kit import ConfiguredEmptyError

    from trade_finance_checker.config import Settings

    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text(
        "pii:\n  jurisdictions: ${TRADE_FINANCE_PII_JURISDICTIONS:-SG,HK,JP,AU}\n"
    )
    monkeypatch.setenv("TRADE_FINANCE_PII_JURISDICTIONS", "")
    with pytest.raises(ConfiguredEmptyError):
        Settings.load(settings_file)

    monkeypatch.setenv("TRADE_FINANCE_PII_JURISDICTIONS", ",")
    with pytest.raises(ConfiguredEmptyError):
        Settings.load(settings_file)

    monkeypatch.delenv("TRADE_FINANCE_PII_JURISDICTIONS")
    assert Settings.load(settings_file).pii.jurisdictions == ("SG", "HK", "JP", "AU")

    monkeypatch.setenv("TRADE_FINANCE_PII_JURISDICTIONS", "JP")
    assert Settings.load(settings_file).pii.jurisdictions == ("JP",)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("amount_tolerance_pct", -0.01),
        ("amount_tolerance_pct", 1.01),
        ("description_min_overlap", -0.01),
        ("description_min_overlap", 1.01),
    ],
)
def test_check_policy_refuses_out_of_range_values(field: str, value: float) -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        CheckSettings(**{field: value})


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
