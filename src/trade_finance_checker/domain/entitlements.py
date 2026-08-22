"""Server-side object-level authorization for the Trade-Finance Checker (system B4).

Closes the C2 object-authorization gap. A ``/v1/check`` request names an object (the
Letter of Credit, ``lc:<lc_number>``), but the LC is submitted in the request body and is
therefore spoofable: whether the caller may examine it is decided HERE, against the
VERIFIED :class:`~trade_finance_checker.domain.identity.Principal` (resolved by the
IdentityPort, never client-asserted) and the object's SERVER-SIDE owner (looked up via the
AclPort, never derived from the body).

Access model, deliberately simple and fail-closed / default-deny:

* the caller must be in the object's owning ``tenant`` (multi-tenant isolation), AND
* the caller must hold one of the object's ``allowed_roles`` OR an explicit ``lc:<id>``
  grant (a fine-grained entitlement provisioned by the IdP / entitlement system).

Any other case - a tenant mismatch, an object with no registered owner, or a principal
with neither a permitted role nor an explicit grant - raises :class:`AccessDenied`.

Pure stdlib; nothing here imports a web framework or a cloud SDK. Raising
:class:`AccessDenied` maps to HTTP 403 at the API layer.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import AccessDenied
from .identity import Principal


@dataclass(frozen=True, slots=True)
class ObjectOwner:
    """The server-side owner record for an addressable object (a Letter of Credit).

    ``tenant`` is the owning tenant; ``allowed_roles`` are the entitlement principals
    (groups) whose members may access the object within that tenant. Returned by the
    AclPort's owner lookup; NEVER constructed from the client-submitted request body.
    """

    tenant: str
    allowed_roles: frozenset[str] = frozenset()


def authorize_object(
    principal: Principal,
    *,
    object_id: str,
    object_tenant: str,
    allowed_roles: frozenset[str] = frozenset(),
) -> None:
    """Fail-closed object authorization: raise :class:`AccessDenied` unless entitled.

    The verified ``principal`` is entitled to the object iff it is in the object's
    ``object_tenant`` AND (holds one of ``allowed_roles`` OR carries an explicit
    ``lc:<object_id>`` grant). Any other case - including an empty/unknown owning tenant
    or a tenant mismatch - denies. Returns ``None`` on success; the caller proceeds only
    if this does not raise. Default deny.
    """
    if not object_tenant or principal.tenant != object_tenant:
        raise AccessDenied(
            f"{principal.actor} (tenant {principal.tenant or 'none'!r}) is not entitled to "
            f"object {object_id!r} owned by tenant {object_tenant or 'none'!r}"
        )
    held = set(principal.principals)
    if held & set(allowed_roles):
        return
    if f"lc:{object_id}" in held:
        return
    raise AccessDenied(
        f"{principal.actor} is not entitled to object {object_id!r} "
        "(no permitted role and no explicit lc grant)"
    )


def entitlement_principals(principal: Principal, requested: tuple[str, ...]) -> tuple[str, ...]:
    """Least-privilege intersection: narrow ``requested`` principals to those held.

    Never widens. Where a caller proposes a set of retrieval principals, the server keeps
    only the ones the VERIFIED principal actually carries, so a client can never request
    more entitlement than it holds. Order follows ``requested``.
    """
    held = set(principal.principals)
    return tuple(p for p in requested if p in held)
