"""Remote-platform AclPort adapter : thin HTTP client to the central entitlement service.

Object ownership (which tenant owns an LC, and which roles may examine it) is governed
centrally rather than vendored into this repo, so the managed (``gcp``) and ``platform``
profiles resolve it over HTTP from the shared entitlement / authorization service. This
adapter implements :class:`AclPort` by GETting the object's owner record and mapping it to
a domain :class:`ObjectOwner`.

It follows the B4 construction convention ``__init__(self, settings)`` and reads its base
URL from ``TRADE_FINANCE_ENTITLEMENTS_URL`` (localhost default), so nothing GCP-specific is
required to construct it. FAIL-CLOSED: a 404 (no such object) maps to ``None`` so the
caller denies, and any transport / non-2xx error raises rather than falling open.
"""

from __future__ import annotations

import httpx

from ...config import Settings
from ...domain.entitlements import ObjectOwner
from ...domain.errors import TradeFinanceError
from ...envread import setting_or_default
from . import _s2s

_DEFAULT_URL = "http://localhost:8087"
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class RemoteAclError(TradeFinanceError):
    """Raised when the central entitlement service returns an unexpected response."""


class RemoteAclAdapter:
    """HTTP client for the central object-ownership / entitlement service."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._base_url = _s2s.validate_base_url(
            setting_or_default("TRADE_FINANCE_ENTITLEMENTS_URL", _DEFAULT_URL),
            service="entitlements service",
        )

    def owner(self, object_id: str) -> ObjectOwner | None:
        """Look up the server-side owner of ``object_id`` via the entitlement service."""
        url = f"{self._base_url}/v1/objects/{object_id}/owner"
        try:
            response = httpx.get(url, timeout=_TIMEOUT, headers=_s2s.headers())
        except httpx.HTTPError as exc:  # network / connection / timeout
            raise RemoteAclError(f"entitlement service request to {url} failed: {exc}") from exc
        if response.status_code == 404:
            return None  # fail-closed: no registered owner
        if response.status_code // 100 != 2:
            raise RemoteAclError(
                f"entitlement service {url} returned {response.status_code}: {response.text[:500]}"
            )
        body = response.json()
        tenant = str(body.get("tenant") or "")
        if not tenant:
            return None  # an owner with no tenant is unusable; deny fail-closed
        roles = frozenset(str(r) for r in (body.get("allowed_roles") or ()))
        return ObjectOwner(tenant=tenant, allowed_roles=roles)

    def register(self, object_id: str, owner: ObjectOwner) -> None:
        """Register ``owner`` for ``object_id`` at the central entitlement service."""
        url = f"{self._base_url}/v1/objects/{object_id}/owner"
        payload = {"tenant": owner.tenant, "allowed_roles": sorted(owner.allowed_roles)}
        try:
            response = httpx.put(url, json=payload, timeout=_TIMEOUT, headers=_s2s.headers())
        except httpx.HTTPError as exc:  # network / connection / timeout
            raise RemoteAclError(f"entitlement service request to {url} failed: {exc}") from exc
        if response.status_code // 100 != 2:
            raise RemoteAclError(
                f"entitlement service {url} returned {response.status_code}: {response.text[:500]}"
            )
