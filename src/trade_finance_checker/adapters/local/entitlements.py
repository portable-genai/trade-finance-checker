"""Local AclPort adapter: a seeded, in-process owner registry (no entitlement store).

The SDK-free ``local`` profile must run fully offline, so this adapter seeds the demo /
fixture Letter-of-Credit ids as owned by the ``demo-bank`` tenant (the tenant the seeded
dev personas in ``adapters/local/identity.py`` belong to), with the trade-finance roles
permitted to examine them. It is FAIL-CLOSED: an LC id that is not seeded has no owner, so
:meth:`owner` returns ``None`` and the ``authorize_object`` gate denies. Bound only under
the local profile; secure profiles use the managed entitlement store.

The registry is keyed by the namespaced ``lc:<lc_number>`` object id, mirroring the
explicit ``lc:<id>`` grant principals an IdP would issue for fine-grained access.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.entitlements import ObjectOwner

# The tenant the seeded local dev personas belong to (adapters/local/identity.py).
_DEMO_TENANT = "demo-bank"

# Roles permitted to examine a demo-bank LC. The analyst/approver personas hold
# ``group:trade-analyst``; the auditor persona holds ``group:trade-audit`` (read for audit).
_DEMO_ROLES: frozenset[str] = frozenset(
    {"group:trade-analyst", "group:trade-approver", "group:trade-audit"}
)

# Demo / fixture LC numbers seeded as owned by demo-bank so the offline demo, the eval
# samples, and the existing green tests (which drive the demo-bank personas) authorize.
# Any LC number NOT listed here has no owner -> the entitlement gate denies (fail-closed).
_SEEDED_LC_NUMBERS: tuple[str, ...] = (
    # unit-test + API-test fixtures (tests/fixtures/sample_trade.py, test_api_identity.py)
    "LC-TEST-0001",
    "LC-TEST-0002",
    "LC-TEST-0003",
    "LC-TEST-0004",
    "LC-TEST-EVIL",
    # offline eval golden set (eval/datasets/golden_presentations.jsonl)
    "LC-G-001",
    "LC-G-002",
    "LC-G-003",
    "LC-G-004",
    "LC-G-005",
    "LC-G-006",
    "LC-G-007",
    "LC-G-008",
    "LC-G-009",
    "LC-G-010",
    "LC-G-011",
    # CLI / demo samples (eval/samples/presentation.json, scripts/trade_finance_demo.py)
    "LC-DEMO-0002",
    "LC-DEMO-2026-0917",
)


class LocalAclAdapter:
    """Seeded in-process owner registry for the local profile (fail-closed)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        owner = ObjectOwner(tenant=_DEMO_TENANT, allowed_roles=_DEMO_ROLES)
        self._owners: dict[str, ObjectOwner] = {
            f"lc:{lc_number}": owner for lc_number in _SEEDED_LC_NUMBERS
        }

    def owner(self, object_id: str) -> ObjectOwner | None:
        """Return the seeded owner for ``object_id`` (``lc:<lc_number>``), else None."""
        return self._owners.get(object_id)

    def register(self, object_id: str, owner: ObjectOwner) -> None:
        """Record ``owner`` for ``object_id`` (an audience-entered LC claiming its tenant).

        In-process like the rest of this seeded registry: a registration lives for the
        server's lifetime, which is exactly the demo scope. The API layer has already
        verified the owner's tenant against the principal and rejected cross-tenant
        re-registration, so this is a plain write.
        """
        self._owners[object_id] = owner
