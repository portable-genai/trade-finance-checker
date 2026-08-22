"""The shared envread helpers preserve UNSET, SET-EMPTY and SET-VALUE.

This lived inside ``test_three_state_env_reads.py`` before that file adopted the byte-identical
canonical scanner. The scanner file carries no per-repo text now, so the behaviour test that
proves the helpers themselves keep all three states moved here rather than being deleted.
"""

from __future__ import annotations

import pytest

from trade_finance_checker.envread import (
    ConfiguredEmptyError,
    boolean_setting,
    optional_setting,
    required_setting,
    setting_or_default,
)


def test_shared_reader_preserves_all_three_states(monkeypatch: pytest.MonkeyPatch) -> None:
    name = "THREE_STATE_TEST_SETTING"
    monkeypatch.delenv(name, raising=False)
    assert setting_or_default(name, "documented-default") == "documented-default"
    assert optional_setting(name) is None
    assert boolean_setting(name) is False
    with pytest.raises(ConfiguredEmptyError):
        required_setting(name)

    monkeypatch.setenv(name, "")
    with pytest.raises(ConfiguredEmptyError):
        setting_or_default(name, "documented-default")
    with pytest.raises(ConfiguredEmptyError):
        optional_setting(name)
    with pytest.raises(ConfiguredEmptyError):
        boolean_setting(name)

    monkeypatch.setenv(name, "  true  ")
    assert setting_or_default(name, "documented-default") == "true"
    assert optional_setting(name) == "true"
    assert boolean_setting(name) is True


def test_boolean_setting_names_the_accepted_spellings(monkeypatch: pytest.MonkeyPatch) -> None:
    name = "THREE_STATE_TEST_SETTING"
    monkeypatch.setenv(name, "maybe")
    with pytest.raises(ValueError, match="must be one of"):
        boolean_setting(name)
