"""FastAPI application for the B4 Trade-Finance Document Checker.

Exposes the discrepancy-check and single-document-extract endpoints plus health, and
publishes the A2A AgentCard at ``/.well-known/agent-card.json``. The React/Next.js UI and
the CLI consume this surface.

Design constraints:

* **Import-safe.** Building the :class:`~trade_finance_checker.config.Container` is deferred
  to request time via the ``deps`` factories, so importing this module (or ``app``) never
  touches Google Cloud. The on-prem/test profile imports it with no GCP SDK installed.
* **Guardrail blocks are not errors.** A blocked presentation comes back as an HTTP 200
  carrying a *blocked* report flagged for human review, never a 500 : the caller always
  gets a well-formed, auditable response.
* **Region pinned** to ``asia-southeast1`` (Singapore) for data residency (SPEC §2).

Run locally with ``python -m trade_finance_checker.api.app`` (uvicorn on :8094).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from hex_service_kit import (
    ConfiguredEmptyError,
    cors_allowlist,
    read_env_setting,
    resolve_bind_host,
)
from hex_service_kit.web import add_loopback_exposure_guard

from ..config import end_user_auth_kind
from ..domain.entitlements import ObjectOwner
from ..domain.errors import AccessDenied, GuardrailBlockedError, RulesUnavailableError
from ..domain.services import TradeCheckService
from ..envread import boolean_setting, setting_or_default
from ..ports.identity import VERIFIED
from . import deps
from .schemas import (
    AgentCardModel,
    CheckRequest,
    DiscrepancyReportResponse,
    DocumentExtractResponse,
    ExtractRequest,
    HealthResponse,
    LcRegistrationRequest,
    LcRegistrationResponse,
)
from .security import CurrentPrincipal

# Local Next.js dev origins the browser UI is served from during development.
_DEV_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

# Embedding-surface controls. In secure/embedded mode the checker is served same-origin via
# the parent app's reverse-proxy (no CORS needed); for the cross-origin / standalone dev
# case, TRADE_FINANCE_CORS_ORIGINS is an explicit per-tenant allowlist (never "*").
# TRADE_FINANCE_FRAME_ANCESTORS is the CSP frame-ancestors allowlist of parent origins
# permitted to iframe the checker UI.
_CORS_ORIGINS_ENV = "TRADE_FINANCE_CORS_ORIGINS"
_FRAME_ANCESTORS_ENV = "TRADE_FINANCE_FRAME_ANCESTORS"
_DEFAULT_FRAME_ANCESTORS = "'self'"


#: Entries that are a wildcard by BEHAVIOUR rather than by spelling, so the asterisk test below
#: cannot see them. ``null`` is the one that matters: a sandboxed iframe presents a null origin,
#: so ``frame-ancestors null`` admits framing from a document whose own origin the browser has
#: already decided not to trust, and a null CORS origin trusts the same document WITH
#: credentials. ``'*'`` is the quoted form CSP also honours and ``*.*`` is the subdomain
#: wildcard; both carry an asterisk, and both are named here so the set reads as the complete
#: refusal rather than as a list of leftovers. Matching is exact, so ``https://nullify.example``
#: remains a perfectly good origin. The same four are refused in ``ui/lib/csp.mjs``.
_WILDCARD_TOKENS = frozenset({"*", "'*'", "null", "*.*"})


def _refuse_wildcard(origins: list[str] | tuple[str, ...], setting: str) -> None:
    """An origin policy naming everybody is not an allowlist, so refuse to boot with one.

    "never ``*``" was written in the comment above and enforced nowhere, which is the same
    as unenforced: the shared ``cors_allowlist`` docstring promises it never returns ``*``
    while its set-and-valid branch returns exactly what the operator wrote. ``*`` in the CORS
    allowlist trusts every origin WITH credentials, and in frame-ancestors it lets any page
    on the internet frame the checker UI and drive it as the signed-in user. The rule catches
    a wildcard hiding inside an origin too (``https://*.example``): a legitimate origin has
    no ``*`` anywhere in it, so this refuses no configuration a deployment could hold.

    Raised from the import-time resolvers below, so it is a BOOT refusal in the same way the
    emptied state already is: the process never comes up serving a policy nobody chose.

    The asterisk test alone was not the whole rule. ``null`` carries no asterisk, so it passed
    both allowlists and reached ``CORSMiddleware`` and the CSP directive verbatim: see
    :data:`_WILDCARD_TOKENS`. The two halves are a UNION, and the union is what
    ``ui/lib/csp.mjs`` already enforced for the document a browser actually frames, so until
    now the two surfaces disagreed about what an origin policy may hold.
    """
    offending = [origin for origin in origins if "*" in origin or origin in _WILDCARD_TOKENS]
    if offending:
        raise ValueError(
            f"{setting} origin policy must never contain a wildcard, got {offending}. "
            "Name each permitted origin in full."
        )


def _frame_ancestors() -> str:
    """Resolve the CSP ``frame-ancestors`` allowlist in THREE states, never two.

    ``os.environ.get(name, "").strip() or _DEFAULT`` distinguishes only two outcomes,
    because the ``or`` collapses "absent" and "present but empty" into the same branch. The
    variable an operator deliberately emptied (a Terraform variable that renders to nothing,
    a Cloud Run env var declared with no value, a ``.env`` line left as ``VAR=``) then
    inherited the unset default and the service answered ``frame-ancestors 'self'`` plus
    ``X-Frame-Options: SAMEORIGIN``, INDISTINGUISHABLE from never having configured it. An
    operator who empties the allowlist to name no parent has expressed an intent, and
    silently granting same-origin framing instead is reading an absence as consent.

    * unset: no intent was expressed, so the documented restrictive default stands.
    * set and empty: an intent WAS expressed and it names nothing. Refused, not silently
      widened. This resolver runs at import, so the refusal is a BOOT refusal: the process
      never comes up serving a framing policy nobody chose.
    * set with a value: used as given, stripped.
    """
    setting = read_env_setting(_FRAME_ANCESTORS_ENV)
    if setting.is_configured_empty:
        raise ConfiguredEmptyError(
            f"{_FRAME_ANCESTORS_ENV} is set but empty. An empty allowlist names no parent "
            "origin, and inheriting the default would silently permit same-origin framing "
            f"nobody asked for. Unset {_FRAME_ANCESTORS_ENV} to keep the "
            f"{_DEFAULT_FRAME_ANCESTORS} default, name the parent origins that may frame the "
            "checker UI, or set it to 'none' to refuse framing outright."
        )
    _refuse_wildcard(setting.value.split(), _FRAME_ANCESTORS_ENV)
    return setting.value or _DEFAULT_FRAME_ANCESTORS


_FRAME_ANCESTORS = _frame_ancestors()

# The two frame-ancestors policies the pre-CSP header can also express.
_LEGACY_FRAME_OPTIONS = {"'self'": "SAMEORIGIN", "'none'": "DENY"}


def _cors_origins() -> list[str]:
    """Explicit allowlist, never "*"; the localhost dev fallback applies ONLY under a
    DELIBERATELY chosen local profile (shared hex-service-kit rule).

    Keyed off ``exposure_profile`` rather than the raw profile: granting cross-origin
    credentialed access to localhost is a relaxation, so a run that never named a profile
    must not look like ``local`` here and gets an empty allowlist instead.

    The CONFIGURED value is judged by :func:`_refuse_wildcard` before the kit is called, and
    that ordering is the point rather than an accident. ``cors_allowlist`` now refuses a
    wildcard itself, raising ``InsecureCorsError``, so whichever of the two runs first is the
    one that decides which message an operator reads. This repo owns the rule: it names the
    variable, and its union covers the behavioural tokens as well as the asterisk. Running it
    first keeps it the single authority and leaves the kit an unreachable backstop on the
    configured path. The trailing call still guards the RESOLVED list, which under the unset
    default is a value the operator never wrote.
    """
    setting = read_env_setting(_CORS_ORIGINS_ENV)
    if setting.has_value:
        _refuse_wildcard(
            [origin.strip() for origin in setting.value.split(",") if origin.strip()],
            _CORS_ORIGINS_ENV,
        )
    resolved = cors_allowlist(
        deps.get_settings().profile_choice.exposure_profile,
        origins_env=_CORS_ORIGINS_ENV,
        dev_origins=tuple(_DEV_ORIGINS),
    )
    _refuse_wildcard(resolved, _CORS_ORIGINS_ENV)
    return resolved


app = FastAPI(
    title="B4 Trade-Finance Document Checker",
    version="0.1.0",
    description=(
        "Parses a Letter of Credit and the presented document set and detects "
        "discrepancies against the LC terms and UCP600, on the Gemini Enterprise Agent "
        "Platform. Decision support for a trade-finance officer, not an approval."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Dev-Persona"],
)


@app.middleware("http")
async def _security_headers(request: Request, call_next: Any) -> Any:
    """Emit embedding-surface headers: CSP frame-ancestors (who may iframe the checker).

    ``_FRAME_ANCESTORS`` is guaranteed non-empty by :func:`_frame_ancestors`, so the directive
    emitted here always carries a value a browser will honour. ``X-Frame-Options`` is the
    pre-CSP equivalent, so it accompanies the two policies it can express: ``'self'`` maps to
    ``SAMEORIGIN`` and ``'none'`` to ``DENY``. A named allowlist has no ``X-Frame-Options``
    spelling, so none is sent there rather than one that contradicts the CSP.
    """
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = f"frame-ancestors {_FRAME_ANCESTORS}"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    if deps.get_settings().profile in {"gcp", "platform"}:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    legacy = _LEGACY_FRAME_OPTIONS.get(_FRAME_ANCESTORS)
    if legacy is not None:
        response.headers["X-Frame-Options"] = legacy
    return response


# A request arrives with nothing authenticating the END USER unless BOTH of these hold, and
# the guard bounds every case where either fails:
#
#   1. a profile was chosen. Absent that, nobody selected an identity scheme, the seeded
#      persona adapter refuses to construct, and every end-user route answers 401; but
#      /healthz, /v1/personas and the agent card would still answer a stranger, and a
#      deployment in that state has no business being reachable at all. It is also the one
#      case where a settings file that bound a verifying adapter must NOT buy the relaxation:
#      unset is not consent, whatever the binding says;
#   2. the identity adapter the active binding names DECLARES that it verifies the end user.
#      Seeded personas arrive on the X-Dev-Persona header the caller wrote (client-asserted)
#      and the on-premises placeholder resolves nobody at all (unimplemented); neither
#      authenticates anyone, so neither may switch this off. Note that the seeded adapter is
#      bound under `live` as well as `local` (config/settings.yaml, identity port), which a
#      rule keyed on the profile string would have missed: `live` reads like a production
#      profile and authenticates nobody here.
#
# Note what is NOT in this expression: any service credential. S2S_TOKEN and its kin are
# evidence about a calling SERVICE and say nothing about the end-user routes, so setting one
# must not, and cannot, disable their bound.
_END_USER_AUTHENTICATED = deps.get_settings().profile_explicit and (
    end_user_auth_kind(deps.get_settings()) == VERIFIED
)

# The RESTRICTION's profile string. `bind_profile` already reads an unconsented run as
# `local`; this widens the same rule to every posture that cannot authenticate an end user, so
# the start-up bound in `main()` and the request-time guard agree instead of one binding every
# interface while the other refuses every caller on it. Without this, `live` would bind
# 0.0.0.0 (it does today) while the guard refused every peer that reached it.
_BIND_PROFILE = (
    deps.get_settings().profile_choice.bind_profile if _END_USER_AUTHENTICATED else "local"
)

# Registered LAST, so it is the OUTERMOST middleware: an off-loopback caller is refused before
# CORS, before the header baseline and before any route or dependency runs. Bound to the APP
# OBJECT, not to `main()`: `resolve_bind_host` bounds only the process that CALLS it, so one
# `uvicorn trade_finance_checker.api.app:app --host 0.0.0.0` (which no file here writes today,
# but nothing on the app object prevents) would serve the seeded trade-analyst and
# trade-approver personas to the LAN with the bind guard entirely bypassed.
add_loopback_exposure_guard(
    app,
    unauthenticated=not _END_USER_AUTHENTICATED,
    insecure_demo_env="TRADE_FINANCE_ALLOW_INSECURE_DEMO",
    # The EXPOSURE profile, so a run nobody configured names itself 'unconfigured' in the
    # refusal rather than borrowing the name of a profile an operator never chose.
    posture=deps.get_settings().profile_choice.exposure_profile,
)


# --------------------------------------------------------------------------- #
# Artifact endpoints
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# LC registration (the audience-data path)
# --------------------------------------------------------------------------- #
# The owner registry is fail-closed: an LC with no registered owner denies. This is how
# a NEW LC (one an audience member just typed into a presentation) enters the registry:
# its submitting tenant claims it, derived from the VERIFIED principal, never the body.
# The roles mirror the seeded demo registry so the standard trade personas can examine.
_TRADE_ROLES: frozenset[str] = frozenset(
    {"group:trade-analyst", "group:trade-approver", "group:trade-audit"}
)

#: The presentation template (LC + documents) served for download; the canonical sample
#: is preferred when running from a checkout so the template and the demo cannot drift.
_TEMPLATE_FALLBACK = """{
  "lc": {
    "lc_number": "LC-EXAMPLE-0001",
    "amount": 100000.0,
    "currency": "USD",
    "expiry_date": "2026-12-31",
    "latest_shipment": "2026-11-30",
    "incoterm": "CIF",
    "beneficiary": "Example Exporter Ltd (FICTIONAL)",
    "applicant": "Example Importer Pte Ltd (FICTIONAL)",
    "terms": {"goods_description": "industrial components"}
  },
  "documents": [
    {
      "doc_type": "commercial_invoice",
      "fields": {
        "invoice_number": "INV-0001",
        "amount": "100000.0",
        "currency": "USD",
        "goods_description": "industrial components"
      },
      "pages": 1,
      "document_id": "doc-invoice-1"
    }
  ]
}
"""


@app.get("/v1/presentations/template", tags=["artifacts"], response_class=Response)
def presentation_template() -> Response:
    """A downloadable presentation (LC + documents) JSON template."""
    import pathlib

    sample = pathlib.Path("eval/samples/presentation.json")
    content = sample.read_text(encoding="utf-8") if sample.is_file() else _TEMPLATE_FALLBACK
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="presentation-template.json"'},
    )


@app.post(
    "/v1/lcs",
    response_model=LcRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["artifacts"],
)
def register_lc(
    request: LcRegistrationRequest,
    principal: CurrentPrincipal,
) -> LcRegistrationResponse:
    """Claim ownership of a Letter of Credit for the caller's verified tenant.

    Idempotent within the owning tenant; a 409 protects an LC already owned by a
    DIFFERENT tenant, so registration can never be used to hijack another tenant's
    object. The fail-closed check gate is unchanged: an unregistered LC still denies.
    """
    if not principal.tenant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="a tenant-less principal cannot own a letter of credit",
        )
    acl = deps.get_container().acl
    object_id = f"lc:{request.lc_number}"
    existing = acl.owner(object_id)
    if existing is not None and existing.tenant != principal.tenant:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="this letter of credit is owned by another tenant",
        )
    if existing is None:
        acl.register(
            object_id,
            ObjectOwner(tenant=principal.tenant, allowed_roles=_TRADE_ROLES),
        )
    return LcRegistrationResponse(
        lc_number=request.lc_number,
        tenant=principal.tenant,
        already_registered=existing is not None,
    )


@app.post("/v1/check", response_model=DiscrepancyReportResponse, tags=["artifacts"])
def check(
    request: CheckRequest,
    principal: CurrentPrincipal,
    service: Annotated[TradeCheckService, Depends(deps.get_trade_check_service)],
) -> DiscrepancyReportResponse:
    """Examine a presentation against the LC and UCP600; return a DiscrepancyReport.

    The audit actor and the entitlement principals are the server-verified
    :class:`Principal` (never a client-supplied identity). Object-level authorization is
    enforced in the service: a caller not entitled to the submitted LC gets a 403 (via
    :class:`AccessDenied`) before any processing. The pipeline degrades gracefully on a
    guardrail block, but should the service ever raise :class:`GuardrailBlockedError` we
    still return a 200 blocked report rather than surfacing a 500.
    """
    lc = request.lc.to_domain()
    documents = [d.to_domain() for d in request.documents]
    try:
        report = service.check(lc, documents, principal=principal)
    except AccessDenied as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="not entitled to this letter of credit",
        ) from exc
    except RulesUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="governed UCP600 rule evidence is unavailable",
        ) from exc
    except GuardrailBlockedError:
        report = service.check(lc, documents, principal=principal)
    return DiscrepancyReportResponse.from_domain(report)


@app.post("/v1/extract", response_model=DocumentExtractResponse, tags=["artifacts"])
def extract(
    request: ExtractRequest,
    principal: CurrentPrincipal,
    service: Annotated[TradeCheckService, Depends(deps.get_trade_check_service)],
) -> DocumentExtractResponse:
    """Parse a single presented document into a structured DocumentExtract."""
    extract = service.extract(request.document.to_domain(), principal=principal)
    return DocumentExtractResponse.from_domain(extract)


# --------------------------------------------------------------------------- #
# Health & governance
# --------------------------------------------------------------------------- #
@app.get("/healthz", response_model=HealthResponse, tags=["ops"])
def healthz() -> HealthResponse:
    """Liveness/readiness probe. Reports the active profile and pinned region."""
    settings = deps.get_settings()
    return HealthResponse(status="ok", profile=settings.profile, region=settings.region)


@app.get("/v1/personas", tags=["ops"])
def personas() -> list[dict[str, str]]:
    """List seeded dev personas for the local persona picker (empty outside local profile).

    Local mode runs with no IdP; the UI uses this to let a demo/test pick an identity (and
    thus exercise per-user authorization) via the ``X-Dev-Persona`` header. Secure profiles
    resolve identity from the IAP assertion, so this returns an empty list.
    """
    identity = deps.get_container().identity
    lister = getattr(identity, "personas", None)
    if lister is None:
        return []
    return [dict(p) for p in lister()]


@app.get("/.well-known/agent-card.json", response_model=AgentCardModel, tags=["governance"])
def agent_card() -> AgentCardModel:
    """Publish this checker's A2A AgentCard for discovery (A3 Registry / interop)."""
    from ..agent.agent_card import build_agent_card

    settings = deps.get_settings()
    card = build_agent_card(settings)
    return AgentCardModel.from_domain(card)


def main() -> None:
    """Run the API locally with uvicorn (Cloud Run / Agent Runtime use this app object)."""
    import uvicorn

    uvicorn.run(
        "trade_finance_checker.api.app:app",
        # Fail-closed bind (shared hex-service-kit rule): a posture that
        # authenticates no end user binds loopback unless TRADE_FINANCE_ALLOW_INSECURE_DEMO=1;
        # verifying profiles keep 0.0.0.0 (container-local; ingress is fronted by the
        # platform). Keyed off ``_BIND_PROFILE``, which fails closed in the OPPOSITE direction
        # to the CORS relaxation above: here ``local`` is the restrictive case, so an
        # unconsented run must look like ``local`` and stay on loopback, and so must ``live``,
        # which binds the same seeded personas while reading as a non-local profile string.
        host=resolve_bind_host(
            _BIND_PROFILE,
            host_env="TRADE_FINANCE_API_HOST",
            insecure_demo_env="TRADE_FINANCE_ALLOW_INSECURE_DEMO",
        ),
        port=int(setting_or_default("PORT", "8094")),
        reload=boolean_setting("TRADE_FINANCE_API_RELOAD"),
    )


if __name__ == "__main__":
    main()
