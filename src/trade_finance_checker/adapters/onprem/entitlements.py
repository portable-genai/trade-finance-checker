"""On-prem AclPort placeholder : integrate the client's object-ACL / entitlement store here.

In the managed profile this port binds to the central entitlement service; switching
``profile`` to ``onprem`` rebinds it here. Fill this in to look up the object owner
(owning tenant + permitted roles) from your on-premise entitlement store (LDAP groups +
an object-owner registry). Like the other on-prem placeholders it constructs with no
external dependency and structurally satisfies the same Protocol, so the contract tests
prove interface parity. It fails fast rather than inventing an owner: object-level
authorization must never fall open on the migration target.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.entitlements import ObjectOwner

_MESSAGE = (
    "On-prem AclPort adapter is a migration placeholder; implement the object-owner lookup "
    "against your on-premise entitlement store (owning tenant + permitted roles). Core "
    "domain logic is unchanged."
)


class OnPremAclAdapter:
    """Placeholder object-ownership adapter for the on-prem profile (fail-fast)."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def owner(self, object_id: str) -> ObjectOwner | None:
        raise NotImplementedError(_MESSAGE)

    def register(self, object_id: str, owner: ObjectOwner) -> None:
        raise NotImplementedError(_MESSAGE)
