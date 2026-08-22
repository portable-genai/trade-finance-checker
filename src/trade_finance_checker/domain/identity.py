"""Identity value objects for server-side, verified principals.

The checker never trusts a client-asserted ``actor`` or ACL. A :class:`Principal` is
resolved server-side by an :class:`~trade_finance_checker.ports.identity.IdentityPort`
adapter (local dev persona, GCP IAP-verified assertion, or an on-prem client IdP) from the
inbound transport context, and becomes the audit actor plus the entitlement principals used
for per-user / per-tenant authorization (non-repudiation under MAS TRM / CPS 234).

Nothing is DECLARED here any more. These four names were hand-copied from the commons into
this repo and, like the observability types beside them, into a dozen others; the copies then
drifted while every structural test kept passing. They now come from
:mod:`hex_service_kit.identity`, which is still pure standard library, so the domain stays
free of any web framework or cloud SDK. This module remains the import site the rest of the
repo uses, so no call site had to move.
"""

from __future__ import annotations

from hex_service_kit.identity import ANONYMOUS as ANONYMOUS
from hex_service_kit.identity import IdentityError as IdentityError
from hex_service_kit.identity import Principal as Principal
from hex_service_kit.identity import RequestContext as RequestContext

__all__ = ["ANONYMOUS", "IdentityError", "Principal", "RequestContext"]
