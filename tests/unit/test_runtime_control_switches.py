"""The cheap runtime controls each have a switch, default on, and behave as a user expects.

The fleet's runtime-control contract (2026-09-24): the guardrail, PII redaction and review
routing are each switched by one environment variable read in three states; off binds a
disabled adapter and says so at startup; on under a networked profile refuses to boot without
the configuration it needs; every caller that hands a report to the router reports what
happened to the hand-off; and a response built from a presentation that redaction changed
says so.
"""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tests.conftest import LOOPBACK_PEER
from typer.testing import CliRunner

from trade_finance_checker.adapters.controls import (
    DisabledGuardrail,
    DisabledRedaction,
    DisabledReviewRouter,
    DisclosingRedaction,
    RecordingReviewRouter,
    ReviewRouting,
)
from trade_finance_checker.adapters.gcp.dlp_redaction import DlpRedactionAdapter
from trade_finance_checker.adapters.local.redaction import LocalRegexRedactionAdapter
from trade_finance_checker.agent import tools as agent_tools
from trade_finance_checker.api import deps
from trade_finance_checker.api.app import app
from trade_finance_checker.cli.main import app as cli_app
from trade_finance_checker.config import (
    GUARDRAIL_ENV,
    HUMAN_REVIEW_URL_ENV,
    PII_REDACTION_ENV,
    REVIEW_ROUTING_ENV,
    Container,
    ControlSwitches,
    LocalSettings,
    Settings,
    build_container,
    warn_switched_off,
)
from trade_finance_checker.envread import ConfiguredEmptyError
from trade_finance_checker.mcp.server import build_handlers

_SWITCHES = (GUARDRAIL_ENV, PII_REDACTION_ENV, REVIEW_ROUTING_ENV)
_PROFILE_ENV = "TRADE_FINANCE_PROFILE"

_LC = {
    "lc_number": "LC-TEST-0001",
    "amount": 50000.0,
    "currency": "USD",
    "expiry_date": "2026-07-31",
    "latest_shipment": "2026-06-30",
    "incoterm": "CIF",
    "terms": {"goods_description": "500 cartons organic green tea"},
}
_CLEAN_DOCS = [{"doc_type": "invoice", "fields": {"amount": "50000.00", "currency": "USD"}}]
_PII_DOCS = [
    {
        "doc_type": "invoice",
        "fields": {"amount": "50000.00", "currency": "USD", "contact": "jane.tan@example.com"},
    }
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (*_SWITCHES, HUMAN_REVIEW_URL_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(_PROFILE_ENV, "local")


def _local(controls: ControlSwitches | None = None) -> Settings:
    base = Settings.load("config/settings.yaml")
    return replace(
        base,
        local=LocalSettings(rules_db_path=":memory:", audit_path=":memory:"),
        controls=controls or ControlSwitches(),
    )


# --------------------------------------------------------------------------- #
# Three states
# --------------------------------------------------------------------------- #
def test_every_control_is_on_when_nothing_is_said() -> None:
    assert Settings.load().controls == ControlSwitches(True, True, True)


@pytest.mark.parametrize("name", _SWITCHES)
def test_a_control_switched_off_is_off(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setenv(name, "false")
    assert Settings.load().controls.switched_off() == (name,)


@pytest.mark.parametrize("name", _SWITCHES)
def test_an_emptied_switch_refuses_at_load(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setenv(name, "")
    with pytest.raises(ConfiguredEmptyError, match=name):
        Settings.load()


@pytest.mark.parametrize("name", _SWITCHES)
def test_an_unrecognised_switch_refuses_at_load(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setenv(name, "sometimes")
    with pytest.raises(ValueError, match=name):
        Settings.load()


# --------------------------------------------------------------------------- #
# Off binds the disabled adapter, and says so once
# --------------------------------------------------------------------------- #
def test_off_binds_the_disabled_adapters() -> None:
    container = Container(_local(ControlSwitches(False, False, False)))
    assert isinstance(container.guardrail, DisabledGuardrail)
    assert isinstance(container.redaction, DisabledRedaction)
    assert isinstance(container.review_router, DisabledReviewRouter)


def test_on_binds_the_profile_adapters() -> None:
    container = Container(_local())
    assert not isinstance(container.guardrail, DisabledGuardrail)
    assert not isinstance(container.redaction, DisabledRedaction)
    assert not isinstance(container.review_router, DisabledReviewRouter)


def test_a_process_with_a_control_off_says_so_once(caplog: pytest.LogCaptureFixture) -> None:
    warn_switched_off.cache_clear()
    settings = _local(ControlSwitches(pii_redaction=False))
    with caplog.at_level(logging.WARNING, logger="trade_finance_checker.config"):
        build_container(settings)
        build_container(settings)
    assert len([r for r in caplog.records if PII_REDACTION_ENV in r.getMessage()]) == 1


# --------------------------------------------------------------------------- #
# On has to work: checked at boot under a networked profile
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("profile", ["gcp", "platform"])
def test_routing_on_without_a_console_refuses_at_boot(
    monkeypatch: pytest.MonkeyPatch, profile: str
) -> None:
    monkeypatch.setenv(_PROFILE_ENV, profile)
    with pytest.raises(ConfiguredEmptyError, match=HUMAN_REVIEW_URL_ENV):
        Settings.load()


def test_routing_on_under_gcp_with_a_console_loads(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_PROFILE_ENV, "gcp")
    monkeypatch.setenv(HUMAN_REVIEW_URL_ENV, "https://review.example.test")
    assert Settings.load().controls.review_routing is True


def test_routing_stated_off_under_gcp_needs_no_console(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_PROFILE_ENV, "gcp")
    monkeypatch.setenv(REVIEW_ROUTING_ENV, "off")
    assert Settings.load().controls.review_routing is False


def test_the_local_profile_needs_no_console() -> None:
    assert Settings.load().controls.review_routing is True


def test_the_model_armor_guardrail_on_without_a_template_refuses_at_boot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(_PROFILE_ENV, "gcp")
    monkeypatch.setenv(HUMAN_REVIEW_URL_ENV, "https://review.example.test")
    shipped = Path("config/settings.yaml").read_text(encoding="utf-8")
    emptied = shipped.replace("template_id: trade-finance-guardrail", 'template_id: ""')
    assert emptied != shipped
    path = tmp_path / "settings.yaml"
    path.write_text(emptied, encoding="utf-8")
    with pytest.raises(ConfiguredEmptyError, match=GUARDRAIL_ENV):
        Settings.load(path)
    monkeypatch.setenv(GUARDRAIL_ENV, "false")
    assert Settings.load(path).controls.guardrail is False


# --------------------------------------------------------------------------- #
# The four routing outcomes
# --------------------------------------------------------------------------- #
class _Accepting:
    def route(self, report: object, *, maker: str, tenant: str = "") -> None:
        return None


class _Refusing:
    def route(self, report: object, *, maker: str, tenant: str = "") -> None:
        raise ConnectionError("console unreachable")


def test_routing_outcomes_take_each_of_their_four_values() -> None:
    assert RecordingReviewRouter(_Accepting()).outcome is ReviewRouting.NOT_REQUIRED

    routed = RecordingReviewRouter(_Accepting())
    routed.route(object(), maker="m")  # type: ignore[arg-type]
    assert routed.outcome is ReviewRouting.ROUTED

    off = RecordingReviewRouter(DisabledReviewRouter(Settings()))
    off.route(object(), maker="m")  # type: ignore[arg-type]
    assert off.outcome is ReviewRouting.OFF

    failed = RecordingReviewRouter(_Refusing())
    failed.route(object(), maker="m")  # type: ignore[arg-type]
    assert failed.outcome is ReviewRouting.FAILED


def test_a_failed_hand_off_is_reported_and_logged_never_raised(
    caplog: pytest.LogCaptureFixture,
) -> None:
    failed = RecordingReviewRouter(_Refusing())
    with caplog.at_level(logging.WARNING, logger="trade_finance_checker.adapters.controls"):
        failed.route(object(), maker="m")  # type: ignore[arg-type]
    assert failed.outcome is ReviewRouting.FAILED
    assert "ConnectionError" in caplog.text


# --------------------------------------------------------------------------- #
# Through every caller: the user sees what the controls did
# --------------------------------------------------------------------------- #
@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> dict[str, Container]:
    holder = {"container": Container(_local())}
    monkeypatch.setattr(deps, "get_container", lambda: holder["container"])
    return holder


def _check(documents: list[dict[str, Any]]) -> dict[str, Any]:
    response = TestClient(app, client=LOOPBACK_PEER).post(
        "/v1/check", json={"lc": _LC, "documents": documents}
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_a_report_says_it_was_routed_and_the_presentation_unchanged(
    served: dict[str, Container],
) -> None:
    body = _check(_CLEAN_DOCS)
    assert body["requires_human_review"] is True
    assert body["review_routing"] == "routed"
    assert body["input_redacted"] is False


def test_a_report_discloses_that_the_presentation_was_masked(
    served: dict[str, Container],
) -> None:
    assert _check(_PII_DOCS)["input_redacted"] is True


def test_a_report_says_routing_is_off_when_it_is(served: dict[str, Container]) -> None:
    served["container"] = Container(_local(ControlSwitches(review_routing=False)))
    assert _check(_CLEAN_DOCS)["review_routing"] == "off"


def test_a_report_says_the_hand_off_failed_instead_of_hiding_it(
    served: dict[str, Container],
) -> None:
    served["container"].__dict__["review_router"] = _Refusing()
    body = _check(_CLEAN_DOCS)
    assert body["review_routing"] == "failed"
    assert body["requires_human_review"] is True


def test_an_extract_discloses_that_the_document_was_masked(served: dict[str, Container]) -> None:
    document = {"doc_type": "invoice", "fields": {"beneficiary": "jane.tan@example.com"}}
    response = TestClient(app, client=LOOPBACK_PEER).post(
        "/v1/extract", json={"document": document}
    )
    assert response.status_code == 200, response.text
    assert response.json()["input_redacted"] is True


def test_the_agent_tools_report_the_hand_off() -> None:
    off = _local(ControlSwitches(review_routing=False))
    assert agent_tools.check_presentation(_LC, _CLEAN_DOCS, settings=off)["review_routing"] == (
        "off"
    )
    assert agent_tools.detect_discrepancies(_LC, _CLEAN_DOCS, settings=_local())[
        "review_routing"
    ] == ("routed")


def test_the_mcp_tools_report_the_hand_off(
    served: dict[str, Container], monkeypatch: pytest.MonkeyPatch
) -> None:
    # MCP stdio verifies no end user, so its principal carries no tenant and a real LC is
    # refused before any hand-off (mcp/server.py). What is under test is that each handler
    # reports the router it handed the report to, so the service is a stand-in that routes a
    # real, locally assembled report.
    report = deps.build_trade_check_service(served["container"]).check(
        agent_tools._to_lc(_LC),
        agent_tools._to_documents(_CLEAN_DOCS),
        principal=agent_tools._principal("t"),
    )

    class _Routes:
        def __init__(self, review_router: Any) -> None:
            self._router = review_router

        def check(self, lc: object, documents: object, principal: object) -> Any:
            self._router.route(report, maker="mcp:test")
            return report

    monkeypatch.setattr(
        deps,
        "get_trade_check_service",
        lambda redaction=None, review_router=None: _Routes(review_router),
    )
    served["container"].__dict__["review_router"] = _Refusing()
    handlers = build_handlers("mcp:test")
    arguments = {"lc": _LC, "documents": _CLEAN_DOCS}
    assert handlers["check_presentation"](**arguments)["review_routing"] == "failed"
    assert handlers["detect_discrepancies"](**arguments)["review_routing"] == "failed"


def test_the_cli_states_the_hand_off_in_plain_words(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(REVIEW_ROUTING_ENV, "off")
    monkeypatch.setenv("TRADE_FINANCE_LOCAL_AUDIT", ":memory:")
    presentation = tmp_path / "presentation.json"
    presentation.write_text(json.dumps({"lc": _LC, "documents": _CLEAN_DOCS}), encoding="utf-8")
    result = CliRunner().invoke(cli_app, ["check", str(presentation)])
    assert result.exit_code == 0, result.output
    assert "Review routing: off" in result.output
    assert "not queued for review" in result.output


def test_the_disclosure_wrapper_notices_only_a_change() -> None:
    wrapper = DisclosingRedaction(LocalRegexRedactionAdapter(_local()))
    wrapper.redact("LC-TEST-0001 invoice USD 50000.00")
    assert wrapper.changed is False
    wrapper.redact("contact jane.tan@example.com")
    assert wrapper.changed is True


# --------------------------------------------------------------------------- #
# Redaction tuned against false positives
# --------------------------------------------------------------------------- #
_BENIGN = (
    "LC number LC-SG-2026-00123 issued under UCP600 article 14(c)",
    "Invoice amount USD 1250000.00 against credit amount USD 1,250,000.00",
    "Latest shipment date 2026-06-15, expiry 2026-07-15 at Singapore",
    "Bill of lading MAEU240512345 shipped on board from Port Klang to Rotterdam",
    "Port of loading Singapore, HS code 8471300000, incoterms CIF Rotterdam",
    "Transfer of SGD 90000000 under the documentary credit",
    "Credit amount USD 125000000 with 10% tolerance per UCP600 article 30(a)",
    "Presentation within 21 days after shipment per ISBP 821 paragraph A19",
)


@pytest.mark.parametrize("text", _BENIGN)
def test_benign_trade_text_passes_the_redactor_unchanged(text: str) -> None:
    assert LocalRegexRedactionAdapter(_local()).redact(text).text == text


@pytest.mark.parametrize(
    ("text", "masked"),
    [
        ("NRIC S1234567D on file", "[SG_NRIC_FIN]"),
        ("write to jane.tan@example.com", "[EMAIL_ADDRESS]"),
        ("call +65 9123 4567 today", "[PHONE_NUMBER]"),
        ("call 91234567 today", "[SG_PHONE]"),
        ("settle to account 123456789012", "[BANK_ACCOUNT_NUMBER]"),
    ],
)
def test_true_personal_data_is_still_masked(text: str, masked: str) -> None:
    assert masked in LocalRegexRedactionAdapter(_local()).redact(text).text


def test_the_inline_dlp_config_is_tuned_against_false_positives() -> None:
    adapter = DlpRedactionAdapter(_local())
    inspect = adapter._inline_inspect_config()
    assert inspect["min_likelihood"] == "LIKELY"
    assert all(c["likelihood"] == "VERY_LIKELY" for c in inspect["custom_info_types"])
    exclusion = inspect["rule_set"][0]
    assert exclusion["info_types"] == [{"name": "PERSON_NAME"}]
    assert "Bill of Lading" in exclusion["rules"][0]["exclusion_rule"]["regex"]["pattern"]
    transformation = adapter._inline_deidentify_config()["info_type_transformations"][
        "transformations"
    ][0]
    assert transformation["primitive_transformation"] == {"replace_with_info_type_config": {}}


def test_the_terraform_dlp_templates_carry_the_same_tuning() -> None:
    dlp_tf = Path("infra/terraform/dlp.tf").read_text(encoding="utf-8")
    assert 'min_likelihood = "LIKELY"' in dlp_tf
    assert '"POSSIBLE"' not in dlp_tf
    assert "replace_with_info_type_config = true" in dlp_tf
    assert "character_mask_config" not in dlp_tf
    assert "Bill of Lading" in dlp_tf
    # The hyphen-tolerant account shape matched every ISO date.
    assert "[\\\\d-]" not in dlp_tf
