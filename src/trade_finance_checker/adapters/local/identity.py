"""Local IdentityPort adapter: seeded dev personas, NO IdP / AD / LDAP.

The SDK-free ``local`` profile must run with zero authentication so demos and tests work
fully offline. This adapter resolves a :class:`Principal` from a small set of seeded
personas, selected by the ``X-Dev-Persona`` request header (the UI's persona picker),
defaulting to the first persona when none is supplied. It lets you exercise per-user
authorization (different entitlement principals and tenants, including a cross-tenant
persona) without standing up any identity provider. It is bound ONLY under the local
profile; secure mode uses the IAP adapter, which verifies a real assertion.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.identity import IdentityError, Principal, RequestContext
from ...ports.identity import CLIENT_ASSERTED

_PERSONA_HEADER = "x-dev-persona"

# Seeded dev personas. Ordered; the first entry is the default when no persona is selected.
# The persona id is the suffix of ``source`` after the colon. The group names are this
# repo's trade-finance domain roles; the other-tenant persona proves per-tenant isolation
# is demoable offline.
_PERSONAS: tuple[Principal, ...] = (
    Principal(
        subject="demo.analyst@bank.example",
        principals=("group:trade-analyst", "group:trade-finance"),
        tenant="demo-bank",
        assurance="local-demo",
        source="local-persona:analyst",
    ),
    Principal(
        subject="demo.approver@bank.example",
        principals=("group:trade-analyst", "group:trade-finance", "group:trade-approver"),
        tenant="demo-bank",
        assurance="local-demo",
        source="local-persona:approver",
    ),
    Principal(
        subject="demo.auditor@bank.example",
        principals=("group:trade-audit",),
        tenant="demo-bank",
        assurance="local-demo",
        source="local-persona:auditor",
    ),
    Principal(
        subject="user@other-tenant.example",
        principals=("group:trade-analyst",),
        tenant="other-bank",
        assurance="local-demo",
        source="local-persona:other-tenant",
    ),
)


def _persona_id(principal: Principal) -> str:
    _, _, suffix = principal.source.partition(":")
    return suffix or principal.subject


#: The profiles this adapter is bound under, both of them laptop stacks with no IdP: ``local``
#: (fully offline) and ``live`` (the same stack against a real local model server). Every other
#: profile resolves identity from a verified IAP assertion.
_NO_AUTH_PROFILES = frozenset({"local", "live"})


class LocalPersonaProfileError(IdentityError):
    """Raised when seeded dev personas would be served under a non-deliberate local profile."""


class LocalPersonaIdentityAdapter:
    """Resolve a Principal from a seeded dev persona (laptop profiles only, no auth).

    These personas are an UNAUTHENTICATED grant of the trade-analyst and trade-approver
    entitlements, so this adapter refuses to construct unless the profile was chosen
    DELIBERATELY: it must be one of :data:`_NO_AUTH_PROFILES` AND (when the settings came from
    the environment) ``TRADE_FINANCE_PROFILE`` or the settings file must actually have named
    it. A missing variable therefore fails closed instead of serving a trade-finance checker
    with dev approvers.
    """

    #: The persona arrives on ``X-Dev-Persona``, a header the CALLER writes, and an absent
    #: header still resolves the first seeded persona. That is a picker, not authentication,
    #: and the exposure guard reads this declaration to keep the routes it serves off the LAN.
    #: Bound under ``live`` as well as ``local``, which is exactly why the guard asks the
    #: BINDING rather than the profile string.
    end_user_auth = CLIENT_ASSERTED

    def __init__(self, settings: Settings) -> None:
        if settings.profile not in _NO_AUTH_PROFILES:
            allowed = ", ".join(sorted(_NO_AUTH_PROFILES))
            raise LocalPersonaProfileError(
                f"seeded dev personas are for the {allowed} profiles only; "
                f"refusing to serve them under profile {settings.profile!r}"
            )
        if not settings.profile_explicit:
            raise LocalPersonaProfileError(
                "TRADE_FINANCE_PROFILE is not set and config/settings.yaml names no profile, "
                "so the local profile was inherited rather than chosen; seeded dev personas "
                "grant the trade-analyst and trade-approver entitlements with no "
                "authentication and are refused. Set TRADE_FINANCE_PROFILE=local deliberately "
                "for a dev or demo run, or TRADE_FINANCE_PROFILE=gcp for a real deployment."
            )
        self._settings = settings
        self._by_id: dict[str, Principal] = {_persona_id(p): p for p in _PERSONAS}
        self._default: Principal = _PERSONAS[0]

    def resolve(self, ctx: RequestContext) -> Principal:
        chosen = ctx.header(_PERSONA_HEADER).strip()
        if not chosen:
            return self._default
        persona = self._by_id.get(chosen)
        if persona is None:
            raise IdentityError(
                f"unknown dev persona {chosen!r}; valid personas: {sorted(self._by_id)}"
            )
        return persona

    def personas(self) -> tuple[dict[str, str], ...]:
        """List the seeded personas for the local persona picker (id, subject, tenant)."""
        return tuple(
            {
                "id": _persona_id(p),
                "subject": p.subject,
                "tenant": p.tenant,
                "principals": ", ".join(p.principals),
            }
            for p in _PERSONAS
        )
