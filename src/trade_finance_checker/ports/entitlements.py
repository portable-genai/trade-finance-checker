"""AclPort : the server-side owner registry for object-level authorization.

The single source of truth for WHO owns an addressable object (a Letter of Credit). The
LC in a ``/v1/check`` request is client-submitted and therefore spoofable, so the checker
never trusts an owner/tenant carried in the body: it asks this port for the object's
server-side owner and then runs the fail-closed ``authorize_object`` gate
(``domain/entitlements.py``) against the VERIFIED principal.

Bound per profile like every other port: ``local`` is a seeded in-process registry,
``onprem`` is a fail-fast placeholder for the client's entitlement store, and
``gcp``/``platform`` delegate to the managed / central entitlement service.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.entitlements import ObjectOwner


@runtime_checkable
class AclPort(Protocol):
    def owner(self, object_id: str) -> ObjectOwner | None:
        """Return the server-side owner of ``object_id`` (an ``lc:<lc_number>`` key), or None.

        A ``None`` return is the fail-closed signal for an object with no registered owner:
        the caller denies access rather than inventing one.
        """
        ...

    def register(self, object_id: str, owner: ObjectOwner) -> None:
        """Record ``owner`` as the server-side owner of ``object_id``.

        Ownership provisioning: how a NEW object (an audience-entered LC) enters the
        registry at all. The API layer derives ``owner`` from the VERIFIED principal's
        tenant, never from the request body, and refuses to re-register an object owned
        by another tenant, so fail-closed authorization is preserved: an unregistered
        LC still denies until its submitting tenant claims it.
        """
        ...
