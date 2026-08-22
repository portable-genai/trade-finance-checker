"""``TRADE_FINANCE_PII_JURISDICTIONS`` resolved in THREE states, never two.

The jurisdiction list is an allowlist whose EMPTY value is the permissive one:
``patterns_for`` keeps the universal email / phone / bank-account rows but contributes no
national-ID row for a jurisdiction that is not listed, so an empty list means an NRIC, HKID,
My Number or TFN in a presented document stops being redacted, in the local redactor and in
the DLP custom info types alike.

The interpolation layer now follows the fleet contract too: only UNSET inherits a default;
configured-empty refuses instead of manufacturing a value the operator did not choose.

Green after: unset keeps the shipped pack, anything that names no jurisdiction is REFUSED at
settings load, and a named list is used. The refusal replaces the earlier posture of quietly
substituting the shipped default for an emptied variable: substituting a value the operator
did not choose is the same two-state collapse, and it left the ``","`` spelling open.
"""

from __future__ import annotations

import pytest
from hex_service_kit import ConfiguredEmptyError

from trade_finance_checker.config import Settings, _interpolate, _pii_settings

_ENV = "TRADE_FINANCE_PII_JURISDICTIONS"


def test_unset_keeps_the_shipped_pack(monkeypatch: pytest.MonkeyPatch) -> None:
    """No intent was expressed, so the settings-file default stands."""
    monkeypatch.delenv(_ENV, raising=False)
    assert Settings.load().pii.jurisdictions == ("SG", "HK", "JP", "AU")


@pytest.mark.parametrize("names_nothing", ["", "   ", "\t", ",", " , , "])
def test_a_value_naming_no_jurisdiction_is_refused(
    monkeypatch: pytest.MonkeyPatch, names_nothing: str
) -> None:
    """The load-bearing assertion: no spelling of "nothing" may silently disable the pack.

    Red before: ``","`` and its variants resolved to ``()``, dropping the national-ID rows
    with no signal. Green after: settings load refuses, so the service cannot come up
    believing it is redacting when it is not.
    """
    monkeypatch.setenv(_ENV, names_nothing)
    with pytest.raises(ConfiguredEmptyError) as excinfo:
        Settings.load()
    assert _ENV in str(excinfo.value)


def test_a_named_list_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV, "gb, in ")
    assert Settings.load().pii.jurisdictions == ("GB", "IN")
    assert _pii_settings({}).jurisdictions == ("GB", "IN")


def test_interpolation_refuses_empty_and_defaults_only_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TFC_TEST_VAR", "")
    with pytest.raises(ConfiguredEmptyError, match="TFC_TEST_VAR"):
        _interpolate("${TFC_TEST_VAR:-fallback}")
    with pytest.raises(ConfiguredEmptyError, match="TFC_TEST_VAR"):
        _interpolate("${TFC_TEST_VAR}")

    monkeypatch.setenv("TFC_TEST_VAR", "real")
    assert _interpolate("${TFC_TEST_VAR:-fallback}") == "real"
    monkeypatch.delenv("TFC_TEST_VAR")
    assert _interpolate("${TFC_TEST_VAR:-fallback}") == "fallback"


def test_an_unlisted_jurisdiction_still_degrades_safely() -> None:
    """Refusing an EMPTY list does not change how an unknown CODE behaves.

    A code with no pack contributes no national-ID row and raises nothing; only naming no
    jurisdiction at all is a refusal.
    """
    assert _pii_settings({"jurisdictions": ["zz"]}).jurisdictions == ("ZZ",)
