"""Object-level authorization: the fail-closed entitlement gate + seeded owner registry.

Covers the C2 fix at the domain level: ``authorize_object`` denies a cross-tenant
principal and a principal with no permitted role / grant, allows an entitled one, and the
local :class:`LocalAclAdapter` is fail-closed (an unknown object id has no owner).
"""

from __future__ import annotations

import pytest

from trade_finance_checker.adapters.local.entitlements import LocalAclAdapter
from trade_finance_checker.config import Settings
from trade_finance_checker.domain import entitlements
from trade_finance_checker.domain.entitlements import ObjectOwner
from trade_finance_checker.domain.errors import AccessDenied
from trade_finance_checker.domain.identity import Principal

DEMO_ROLES = frozenset({"group:trade-analyst", "group:trade-approver"})

ANALYST = Principal(
    subject="demo.analyst@bank.example",
    principals=("group:trade-analyst", "group:trade-finance"),
    tenant="demo-bank",
)
CROSS_TENANT = Principal(
    subject="user@other-tenant.example",
    principals=("group:trade-analyst",),
    tenant="other-bank",
)
NO_ROLE = Principal(
    subject="viewer@bank.example",
    principals=("group:hr",),
    tenant="demo-bank",
)
EXPLICIT_GRANT = Principal(
    subject="temp@bank.example",
    principals=("lc:LC-TEST-0001",),
    tenant="demo-bank",
)


# --------------------------------------------------------------------------- #
# authorize_object : fail-closed / default deny
# --------------------------------------------------------------------------- #
def test_authorize_object_allows_same_tenant_permitted_role() -> None:
    # No raise == allowed.
    entitlements.authorize_object(
        ANALYST, object_id="LC-TEST-0001", object_tenant="demo-bank", allowed_roles=DEMO_ROLES
    )


def test_authorize_object_allows_explicit_lc_grant() -> None:
    entitlements.authorize_object(
        EXPLICIT_GRANT,
        object_id="LC-TEST-0001",
        object_tenant="demo-bank",
        allowed_roles=frozenset(),  # no role, but an explicit lc:<id> grant
    )


def test_authorize_object_denies_cross_tenant_principal() -> None:
    with pytest.raises(AccessDenied):
        entitlements.authorize_object(
            CROSS_TENANT,
            object_id="LC-TEST-0001",
            object_tenant="demo-bank",
            allowed_roles=DEMO_ROLES,
        )


def test_authorize_object_denies_same_tenant_without_role_or_grant() -> None:
    with pytest.raises(AccessDenied):
        entitlements.authorize_object(
            NO_ROLE, object_id="LC-TEST-0001", object_tenant="demo-bank", allowed_roles=DEMO_ROLES
        )


def test_authorize_object_denies_empty_owner_tenant() -> None:
    # A missing/empty owning tenant (e.g. an unusable owner record) is default-deny.
    with pytest.raises(AccessDenied):
        entitlements.authorize_object(
            ANALYST, object_id="LC-TEST-0001", object_tenant="", allowed_roles=DEMO_ROLES
        )


# --------------------------------------------------------------------------- #
# entitlement_principals : least-privilege intersection (never widens)
# --------------------------------------------------------------------------- #
def test_entitlement_principals_narrows_to_held() -> None:
    narrowed = entitlements.entitlement_principals(
        ANALYST, ("group:trade-analyst", "group:trade-approver", "group:trade-finance")
    )
    assert narrowed == ("group:trade-analyst", "group:trade-finance")


# --------------------------------------------------------------------------- #
# LocalAclAdapter : seeded demo-bank owner registry, fail-closed on unknown ids
# --------------------------------------------------------------------------- #
def _acl() -> LocalAclAdapter:
    return LocalAclAdapter(Settings(profile="local"))


def test_local_acl_returns_demo_bank_owner_for_seeded_lc() -> None:
    owner = _acl().owner("lc:LC-TEST-0001")
    assert isinstance(owner, ObjectOwner)
    assert owner.tenant == "demo-bank"
    assert "group:trade-analyst" in owner.allowed_roles


def test_local_acl_is_fail_closed_for_unknown_object_id() -> None:
    assert _acl().owner("lc:LC-DOES-NOT-EXIST") is None
    assert _acl().owner("LC-TEST-0001") is None  # unnamespaced id is not a match either


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
