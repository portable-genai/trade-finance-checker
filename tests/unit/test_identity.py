"""Unit tests for the IdentityPort adapters (server-side, verified identity).

The local persona adapter is the offline (no IdP/AD/LDAP) identity source used for demos
and tests; the on-prem adapter is a fail-fast placeholder. These prove the identity seam
that replaces the old client-asserted ``actor``.
"""

from __future__ import annotations

import pytest

from trade_finance_checker.adapters.local.identity import LocalPersonaIdentityAdapter
from trade_finance_checker.adapters.onprem.identity import OnPremIdentityAdapter
from trade_finance_checker.config import Settings
from trade_finance_checker.domain.identity import IdentityError, RequestContext
from trade_finance_checker.envread import ConfiguredEmptyError

_SETTINGS = Settings(profile="local")


def _adapter() -> LocalPersonaIdentityAdapter:
    return LocalPersonaIdentityAdapter(_SETTINGS)


def test_default_persona_when_no_header() -> None:
    principal = _adapter().resolve(RequestContext(headers={}))
    assert principal.subject == "demo.analyst@bank.example"
    assert principal.principals  # non-empty entitlements
    assert principal.tenant == "demo-bank"
    assert principal.actor == principal.subject  # audit actor is the verified subject


def test_persona_selected_by_header() -> None:
    principal = _adapter().resolve(RequestContext(headers={"x-dev-persona": "auditor"}))
    assert principal.subject == "demo.auditor@bank.example"
    assert principal.principals == ("group:trade-audit",)


def test_persona_header_is_case_insensitive() -> None:
    # RequestContext lower-cases lookups, so a host that sends X-Dev-Persona still resolves.
    principal = _adapter().resolve(RequestContext(headers={"x-dev-persona": "other-tenant"}))
    assert principal.tenant == "other-bank"


def test_unknown_persona_raises() -> None:
    with pytest.raises(IdentityError):
        _adapter().resolve(RequestContext(headers={"x-dev-persona": "does-not-exist"}))


def test_personas_listing_for_picker() -> None:
    ids = {p["id"] for p in _adapter().personas()}
    assert {"analyst", "approver", "auditor", "other-tenant"} <= ids


def test_onprem_identity_fails_fast() -> None:
    adapter = OnPremIdentityAdapter(_SETTINGS)
    with pytest.raises(NotImplementedError):
        adapter.resolve(RequestContext(headers={}))


# --------------------------------------------------------------------------- #
# The IAP audience is a three-state read: unset, set-and-blank, set-and-valid.
# --------------------------------------------------------------------------- #
def test_iap_unset_refuses_before_the_assertion_is_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unconfigured audience is refused first, so nothing depends on the SDK or the caller.

    Set-and-blank was the hole: ``" "`` is truthy, so a variable rendered empty by a
    deployment template reached ``id_token.verify_token`` as the expected audience. The
    refusal also moved ahead of the assertion header check, so it does not need a credential
    to be present and never reaches the lazy google-auth import.
    """
    from trade_finance_checker.adapters.gcp.iap_identity import IapIdentityAdapter

    monkeypatch.delenv("TRADE_FINANCE_IAP_AUDIENCE", raising=False)
    adapter = IapIdentityAdapter(Settings(profile="gcp"))
    with pytest.raises(IdentityError, match="TRADE_FINANCE_IAP_AUDIENCE"):
        adapter.resolve(RequestContext(headers={}))
    with pytest.raises(IdentityError, match="TRADE_FINANCE_IAP_AUDIENCE"):
        adapter.resolve(RequestContext(headers={"x-goog-iap-jwt-assertion": "forged.jwt.value"}))


@pytest.mark.parametrize("value", ["", "   "])
def test_iap_configured_empty_refuses_at_construction(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    from trade_finance_checker.adapters.gcp.iap_identity import IapIdentityAdapter

    monkeypatch.setenv("TRADE_FINANCE_IAP_AUDIENCE", value)
    with pytest.raises(ConfiguredEmptyError, match="TRADE_FINANCE_IAP_AUDIENCE"):
        IapIdentityAdapter(Settings(profile="gcp"))
