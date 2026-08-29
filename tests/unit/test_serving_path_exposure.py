"""The loopback bound is a property of the APP OBJECT, not of ``main()``.

This repo was NOT leaking when this file was written, and the file is not a bug report. The
shipped entry point is ``python -m trade_finance_checker.api.app`` (the Dockerfile ``CMD`` and
the Makefile ``run-api`` target both), which reaches ``main()`` and therefore
``resolve_bind_host``; nothing in the tree passes ``--host 0.0.0.0``. What was missing is that
the bound was a property of ONE ENTRY POINT rather than of the application: a single
``uvicorn trade_finance_checker.api.app:app --host 0.0.0.0`` -- an operator improvising, a
process manager unit file, a base image whose CMD is overridden -- never reaches ``main()``,
and nothing on the app object stopped it. The guard now rides the app object, so the bound
holds however the app is served. ``test_the_app_object_is_bounded_without_main`` is the cell
that distinguishes the two: it never calls ``main()``.

WHAT the guard is derived from is the second half, and the reason a rule keyed on the profile
STRING would not have been enough. ``config/settings.yaml`` binds the SAME seeded-persona
adapter under ``live`` as under ``local``, and ``live`` reads like a production profile
everywhere else in this repo (it even took ``0.0.0.0`` from ``resolve_bind_host`` before this
change). A guard written as ``profile == "local"`` would have left ``live`` serving the
trade-analyst and trade-approver personas to the LAN, and it would pass every other cell in
this file. ``test_a_profile_string_rule_would_have_missed_live`` is that mutant, executed.

The guard is likewise not derived from a service credential: ``S2S_TOKEN`` authenticates a
calling SERVICE and no end user, so it is no evidence that ``/v1/personas`` is protected. The
scanner at the bottom fails the build if one reappears in the derivation.

The control at the end keeps the other cells from being true for a boring reason: a VERIFYING
binding must stand the guard DOWN, or "everything refuses" would just mean the guard is stuck
on.
"""

from __future__ import annotations

import ast
import importlib
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tests.conftest import LOOPBACK_PEER

from trade_finance_checker.adapters.gcp.iap_identity import IapIdentityAdapter
from trade_finance_checker.adapters.local.identity import (
    LocalPersonaIdentityAdapter,
    LocalPersonaProfileError,
)
from trade_finance_checker.adapters.onprem.identity import OnPremIdentityAdapter
from trade_finance_checker.config import (
    RUNTIME_PROFILES,
    Settings,
    end_user_auth_kind,
    identity_adapter_class,
)
from trade_finance_checker.ports.identity import (
    CLIENT_ASSERTED,
    END_USER_AUTH_ATTR,
    END_USER_AUTH_KINDS,
    UNIMPLEMENTED,
    VERIFIED,
    declared_end_user_auth,
)

#: A peer somewhere else on the LAN. RFC 5737 documentation address: no real host, and
#: obviously fictional.
LAN_PEER = ("203.0.113.7", 51234)

#: Every environment variable the API module reads at import. Cleared before each cell so a
#: case that omits one is testing the ABSENT state rather than inheriting the developer's
#: shell (or the ``local`` default the rest of the suite runs under).
_ENV = (
    "TRADE_FINANCE_PROFILE",
    "TRADE_FINANCE_ALLOW_INSECURE_DEMO",
    "TRADE_FINANCE_IAP_AUDIENCE",
    "TRADE_FINANCE_API_HOST",
    "S2S_TOKEN",
)

#: Every route that answers without a credential, including the two that need no identity at
#: all: a deployment that can authenticate nobody has no business answering a stranger even
#: about its own health.
UNCREDENTIALED_ROUTES = ("/healthz", "/v1/personas", "/.well-known/agent-card.json")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_APP_MODULE = _REPO_ROOT / "src" / "trade_finance_checker" / "api" / "app.py"


def _app_under(monkeypatch: pytest.MonkeyPatch, **env: str) -> Any:
    """Re-import the API module under a scrubbed environment and return its app object.

    The posture is resolved at IMPORT (the guard rides the app object), so an app built under
    the ambient environment would prove nothing about any other.
    """
    for name in _ENV:
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)

    from trade_finance_checker.api import deps

    deps.get_container.cache_clear()
    module = importlib.import_module("trade_finance_checker.api.app")
    return importlib.reload(module).app


@pytest.fixture(autouse=True)
def _restore_the_shared_app_module() -> Any:
    """Reload the API module under the suite's own environment after every cell.

    ``importlib.reload`` rebinds the module object every other test in the session imported,
    so leaving a reloaded-under-``onprem`` module behind would break unrelated tests in file
    order. The cache is cleared too, since the container is keyed to the old settings.
    """
    yield
    from trade_finance_checker.api import deps

    deps.get_container.cache_clear()
    importlib.reload(importlib.import_module("trade_finance_checker.api.app"))
    deps.get_container.cache_clear()


def _status(app: Any, path: str, peer: tuple[str, int]) -> int:
    with TestClient(app, client=peer) as client:
        return client.get(path, headers={"X-Dev-Persona": "approver"}).status_code


def _settings_for(profile: str, identity: dict[str, str] | None = None) -> Settings:
    """The shipped settings, re-pointed at ``profile`` (and optionally at a REBOUND adapter).

    ``replace`` rather than mutation: ``Settings`` is frozen and its ``adapters`` map is shared
    with the process-wide container, so writing into it would leak a test's rebinding into
    every later test in the session.
    """
    loaded = Settings.load("config/settings.yaml")
    adapters = {port: dict(bindings) for port, bindings in loaded.adapters.items()}
    if identity is not None:
        adapters["identity"] = dict(identity)
    return replace(loaded, profile=profile, adapters=adapters)


# --------------------------------------------------------------------------- #
# 1. The guard is ON the app object, and it refuses every no-auth posture.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("path", UNCREDENTIALED_ROUTES)
@pytest.mark.parametrize(
    ("label", "env"),
    [
        # The ordinary offline dev/demo shape.
        ("local chosen", {"TRADE_FINANCE_PROFILE": "local"}),
        # A service credential authenticates a calling SERVICE, never an end user, so it must
        # not unbound the end-user routes.
        (
            "local chosen, S2S token SET",
            {"TRADE_FINANCE_PROFILE": "local", "S2S_TOKEN": "s3cret"},
        ),
        # `live` binds the SAME seeded-persona adapter while reading as a non-local profile
        # string. This is the cell a `profile == "local"` rule would fail.
        ("live (seeded personas)", {"TRADE_FINANCE_PROFILE": "live"}),
        (
            "live (seeded personas), token SET",
            {"TRADE_FINANCE_PROFILE": "live", "S2S_TOKEN": "s3cret"},
        ),
        # Unset is not consent: no profile means no identity scheme was chosen at all.
        ("profile UNSET", {}),
        ("profile UNSET, token SET", {"S2S_TOKEN": "s3cret"}),
        # The on-premises placeholder resolves nobody until a client binds their own IdP.
        ("onprem placeholder binding", {"TRADE_FINANCE_PROFILE": "onprem"}),
    ],
)
def test_a_posture_that_authenticates_no_end_user_refuses_a_lan_peer(
    monkeypatch: pytest.MonkeyPatch, label: str, env: dict[str, str], path: str
) -> None:
    app = _app_under(monkeypatch, **env)
    assert _status(app, path, LAN_PEER) == 503, f"{label}: {path} answered a LAN peer"


def test_the_app_object_is_bounded_without_main(monkeypatch: pytest.MonkeyPatch) -> None:
    """The cell that distinguishes an app-object guard from an entry-point one.

    No ``main()``, no ``resolve_bind_host``: just the app object, exactly as
    ``uvicorn trade_finance_checker.api.app:app --host 0.0.0.0`` would hand it to a server.
    Red before the guard existed: this served 200 and the body carried the whole persona
    roster, subjects, tenants and entitlement groups included.
    """
    app = _app_under(monkeypatch, TRADE_FINANCE_PROFILE="local")
    with TestClient(app, client=LAN_PEER) as client:
        response = client.get("/v1/personas")
    assert response.status_code == 503
    assert "demo.analyst@bank.example" not in response.text, (
        "a 503 whose body still carried the personas would be no fix at all"
    )
    detail = response.json()["detail"]
    assert "203.0.113.7" in detail, "the refusal must name the peer it refused"
    assert "TRADE_FINANCE_ALLOW_INSECURE_DEMO" in detail, "the refusal must name the opt-out"


def test_a_forwarding_header_is_disqualifying_even_from_loopback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A proxy has already overwritten the scope peer, so the header's PRESENCE is the signal."""
    app = _app_under(monkeypatch, TRADE_FINANCE_PROFILE="local")
    with TestClient(app, client=LOOPBACK_PEER) as client:
        response = client.get("/healthz", headers={"X-Forwarded-For": "127.0.0.1"})
    assert response.status_code == 503


# --------------------------------------------------------------------------- #
# 2. The other direction: loopback still works, under BOTH no-auth profiles.
#    A guard that refuses everybody is a broken service, not a secure one.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("profile", ["local", "live"])
@pytest.mark.parametrize("path", UNCREDENTIALED_ROUTES)
def test_the_same_posture_still_serves_a_loopback_peer(
    monkeypatch: pytest.MonkeyPatch, profile: str, path: str
) -> None:
    """The offline demo is the whole point of these profiles and must not regress."""
    app = _app_under(monkeypatch, TRADE_FINANCE_PROFILE=profile)
    assert _status(app, path, LOOPBACK_PEER) == 200


@pytest.mark.parametrize("profile", ["local", "live"])
def test_the_seeded_personas_are_intact_on_loopback(
    monkeypatch: pytest.MonkeyPatch, profile: str
) -> None:
    """The refusal must be about the PEER, not about the personas having gone away."""
    app = _app_under(monkeypatch, TRADE_FINANCE_PROFILE=profile)
    with TestClient(app, client=LOOPBACK_PEER) as client:
        response = client.get("/v1/personas")
    assert response.status_code == 200
    assert [p["id"] for p in response.json()] == [
        "analyst",
        "approver",
        "auditor",
        "other-tenant",
    ]


def test_the_insecure_demo_opt_in_lifts_the_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    """The operator's explicit consent, and it is the SAME variable the bind guard honours.

    Read per request rather than at import, and it must be exactly "1": the relaxation fails
    closed in the opposite direction from the restriction, so "true" leaves the guard on.
    """
    app = _app_under(
        monkeypatch, TRADE_FINANCE_PROFILE="local", TRADE_FINANCE_ALLOW_INSECURE_DEMO="1"
    )
    assert _status(app, "/v1/personas", LAN_PEER) == 200
    monkeypatch.setenv("TRADE_FINANCE_ALLOW_INSECURE_DEMO", "true")
    assert _status(app, "/v1/personas", LAN_PEER) == 503


# --------------------------------------------------------------------------- #
# 3. The posture comes from the BOUND ADAPTER CLASS, never from the profile string.
# --------------------------------------------------------------------------- #
def test_a_profile_string_rule_would_have_missed_live() -> None:
    """The mutant, executed: ``profile == "local"`` reads ``live`` as an authenticated posture.

    ``live`` binds ``LocalPersonaIdentityAdapter`` (config/settings.yaml, identity port), the
    very same seeded personas ``local`` binds, and a bind guard keyed on the profile NAME hands
    it ``0.0.0.0``. A rule keyed on that name therefore calls the no-auth `live` posture
    authenticated and stands the guard down on it, while passing every other cell in this file.
    The BINDING knows; the name does not.
    """
    live = _settings_for("live")
    assert live.adapters["identity"]["live"] == live.adapters["identity"]["local"], (
        "this file's premise: `live` binds the same seeded-persona adapter as `local`"
    )

    def mutant_posture(settings: Settings) -> bool:
        """What a guard derived from the profile STRING would have concluded."""
        return settings.profile != "local"

    assert mutant_posture(live) is True, "the mutant reads `live` as authenticated"
    assert end_user_auth_kind(live) == CLIENT_ASSERTED, (
        "the shipped derivation reads the BOUND ADAPTER and sees seeded personas under `live`"
    )


@pytest.mark.parametrize(
    ("profile", "expected"),
    [
        ("local", CLIENT_ASSERTED),
        ("live", CLIENT_ASSERTED),
        ("gcp", VERIFIED),
        ("platform", VERIFIED),
        ("onprem", UNIMPLEMENTED),
    ],
)
def test_the_posture_follows_the_profile_binding(profile: str, expected: str) -> None:
    assert end_user_auth_kind(_settings_for(profile)) == expected


def test_the_posture_follows_a_REBOUND_adapter_not_the_profile_name() -> None:
    """The on-premises migration path: bind a real verifier and the posture changes with it.

    An adopter who wires their own verifying adapter under `onprem` has an authenticated
    service, and a guard keyed off the word "onprem" would confine it to loopback forever.
    """
    rebound = _settings_for(
        "onprem",
        identity={"onprem": "trade_finance_checker.adapters.gcp.iap_identity:IapIdentityAdapter"},
    )
    assert end_user_auth_kind(rebound) == VERIFIED


def test_an_unresolvable_binding_fails_CLOSED_rather_than_raising_past_the_guard() -> None:
    """A guard that switches off because a lookup raised is a guard that fails open."""
    broken = _settings_for("local", identity={"local": "trade_finance_checker.nope:Missing"})
    assert end_user_auth_kind(broken) == CLIENT_ASSERTED


def test_the_posture_is_read_WITHOUT_constructing_the_adapter() -> None:
    """The seeded-persona adapter refuses to construct under an inherited profile.

    A posture computed from an INSTANCE would therefore be unobtainable in one of the exact
    cases it has to describe, so the declaration is a class attribute and the resolver reads
    the class.
    """
    inherited = replace(_settings_for("local"), profile_explicit=False)
    with pytest.raises(LocalPersonaProfileError):
        LocalPersonaIdentityAdapter(inherited)
    assert end_user_auth_kind(inherited) == CLIENT_ASSERTED


# --------------------------------------------------------------------------- #
# 4. Every shipped adapter declares what it does, explicitly.
# --------------------------------------------------------------------------- #
def test_the_seeded_persona_adapter_declares_client_asserted() -> None:
    """The persona rides a header the caller wrote, and an absent header still resolves one."""
    assert declared_end_user_auth(LocalPersonaIdentityAdapter) == CLIENT_ASSERTED


def test_the_iap_adapter_declares_that_it_verifies() -> None:
    assert declared_end_user_auth(IapIdentityAdapter) == VERIFIED


def test_the_onprem_placeholder_declares_that_it_verifies_nothing() -> None:
    assert declared_end_user_auth(OnPremIdentityAdapter) == UNIMPLEMENTED


@pytest.mark.parametrize("profile", sorted(RUNTIME_PROFILES))
def test_every_bound_adapter_declares_explicitly(profile: str) -> None:
    """A new adapter must SAY what it does; inheriting the safe default silently is not enough."""
    adapter = identity_adapter_class(_settings_for(profile))
    declared = [klass for klass in adapter.__mro__ if END_USER_AUTH_ATTR in vars(klass)]
    assert declared, (
        f"{adapter.__name__} (the {profile} identity binding) sets no {END_USER_AUTH_ATTR}. "
        f"Declare one of {sorted(END_USER_AUTH_KINDS)} on the class: the exposure guard reads "
        "it, and silence is read as client-asserted."
    )
    assert declared_end_user_auth(adapter) in END_USER_AUTH_KINDS


class _UndeclaredAdapter:
    """An adapter that says nothing at all."""


class _MisdeclaredAdapter:
    """An adapter whose declaration is a typo, which must not read as a verification claim."""

    end_user_auth = "Verified"


@pytest.mark.parametrize("adapter", [_UndeclaredAdapter, _MisdeclaredAdapter, object()])
def test_silence_and_typos_are_read_as_client_asserted(adapter: object) -> None:
    """The fail-closed default, in the only direction that matters: never VERIFIED."""
    assert declared_end_user_auth(adapter) == CLIENT_ASSERTED


# --------------------------------------------------------------------------- #
# 5. The control: a verifying binding stands the guard DOWN.
# --------------------------------------------------------------------------- #
def test_a_verifying_binding_stands_the_guard_down(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without this, "everything refuses" would just mean the guard is stuck on.

    A fronted deployment (IAP verifies the assertion before the request arrives) must stay
    reachable and health-checkable off loopback. That it leaks no seeded identity is the
    separate assertion below: ``/v1/personas`` is empty outside the persona binding.
    """
    app = _app_under(
        monkeypatch,
        TRADE_FINANCE_PROFILE="gcp",
        TRADE_FINANCE_IAP_AUDIENCE="/projects/000/global/backendServices/000",
        S2S_TOKEN="s3cret",
    )
    assert _status(app, "/healthz", LAN_PEER) == 200

    with TestClient(app, client=LAN_PEER) as client:
        response = client.get("/v1/personas", headers={"X-Dev-Persona": "approver"})
    assert response.status_code == 200
    assert response.json() == [], "a verifying binding must publish no seeded identities"


# --------------------------------------------------------------------------- #
# 6. The start-up bound and the request-time guard agree.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("profile", "expected"),
    [("local", "local"), ("live", "local"), ("gcp", "gcp"), ("onprem", "local")],
)
def test_the_bind_profile_agrees_with_the_guard(
    monkeypatch: pytest.MonkeyPatch, profile: str, expected: str
) -> None:
    """One must not bind every interface while the other refuses every peer on it.

    Handing ``resolve_bind_host`` the raw ``bind_profile`` breaks ``live`` and ``onprem``: a
    ``live`` run of the SHIPPED entry point then binds ``0.0.0.0`` while authenticating
    nobody.
    """
    for name in _ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TRADE_FINANCE_PROFILE", profile)

    from trade_finance_checker.api import deps

    deps.get_container.cache_clear()
    module = importlib.reload(importlib.import_module("trade_finance_checker.api.app"))
    assert expected == module._BIND_PROFILE


# --------------------------------------------------------------------------- #
# 7. The guard's argument names no credential, at any depth.
# --------------------------------------------------------------------------- #
#: The guard call whose argument must never be derived from a credential.
_GUARD_CALL = "add_loopback_exposure_guard"

#: Anything naming a SERVICE credential. The guard bounds the whole app, including routes that
#: carry no credential at all, so none of these may appear anywhere in the expression that
#: decides whether it is on, at any depth.
_CREDENTIAL_MARKERS: tuple[str, ...] = ("S2S", "TOKEN", "SECRET", "BEARER")


class _StripDocstrings(ast.NodeTransformer):
    """Drop every docstring from a subtree before it is scanned.

    The scan looks for the NAME of a credential in what the guard's posture reaches, and a
    docstring is prose, not a read. Without this, a comment or docstring saying that the S2S
    token is NOT in the expression would fail the build for saying so.
    """

    def _strip(self, node: ast.AST) -> ast.AST:
        body = getattr(node, "body", None)
        first = body[0] if isinstance(body, list) and body else None
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            node.body = body[1:] or [ast.Pass()]  # type: ignore[attr-defined,index]
        return self.generic_visit(node)

    visit_FunctionDef = _strip
    visit_AsyncFunctionDef = _strip
    visit_ClassDef = _strip
    visit_Module = _strip


def _module_definitions(tree: ast.Module) -> dict[str, str]:
    """Module-level ``NAME = <expr>`` assignments AND function bodies, as source text."""
    found: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                found[target.id] = ast.unparse(node.value)
        elif isinstance(node, ast.FunctionDef):
            stripped = _StripDocstrings().visit(ast.parse(ast.unparse(node)))
            found[node.name] = ast.unparse(stripped)
    return found


def guard_posture_source(source: str) -> str:
    """Everything the exposure guard's ``unauthenticated`` argument reaches, as one blob.

    Transitive on purpose: the posture is one indirection deep (``_END_USER_AUTHENTICATED``),
    and a check that only read the call site would see nothing.
    """
    tree = ast.parse(source)
    definitions = _module_definitions(tree)
    expressions: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and ast.unparse(node.func).endswith(_GUARD_CALL):
            expressions += [
                ast.unparse(kw.value) for kw in node.keywords if kw.arg == "unauthenticated"
            ]
    assert expressions, f"no {_GUARD_CALL}(unauthenticated=...) call found"
    seen: set[str] = set()
    reached = list(expressions)
    pending = list(expressions)
    while pending:
        for name_node in ast.walk(ast.parse(pending.pop())):
            if isinstance(name_node, ast.Name) and name_node.id not in seen:
                seen.add(name_node.id)
                if name_node.id in definitions:
                    reached.append(definitions[name_node.id])
                    pending.append(definitions[name_node.id])
    return "\n".join(reached + sorted(seen))


def test_the_exposure_guard_reads_no_service_credential() -> None:
    """A credential may not decide whether the guard is on."""
    reached = guard_posture_source(_APP_MODULE.read_text(encoding="utf-8")).upper()
    offenders = [marker for marker in _CREDENTIAL_MARKERS if marker in reached]
    assert offenders == [], (
        f"the exposure guard's posture reaches {offenders}. A service credential authenticates "
        "a calling SERVICE and no end user, so it is no evidence that the end-user routes are "
        "protected. Derive the posture from the identity binding (config.end_user_auth_kind)."
    )


def test_the_exposure_guard_is_derived_from_the_identity_binding() -> None:
    """Not merely "no credential": the posture must come from the thing that actually knows."""
    reached = guard_posture_source(_APP_MODULE.read_text(encoding="utf-8"))
    assert "end_user_auth_kind" in reached, (
        "the guard no longer reads the identity binding, so nothing checks whether this "
        "deployment can authenticate anybody at all"
    )


#: The defect shape a credential-derived posture would have, one indirection deep. A scanner
#: nobody proved can find anything is a green tick over an empty set.
_MUTANT = (
    "_TOKEN_ENV = 'S2S_TOKEN'\n"
    "_END_USER_AUTHENTICATED = not read_env_setting(_TOKEN_ENV).is_unset\n"
    "add_loopback_exposure_guard(\n"
    "    app,\n"
    "    unauthenticated=not _END_USER_AUTHENTICATED,\n"
    "    insecure_demo_env='TRADE_FINANCE_ALLOW_INSECURE_DEMO',\n"
    ")\n"
)


def test_the_scan_finds_the_defect_it_was_written_for() -> None:
    reached = guard_posture_source(_MUTANT).upper()
    caught = {marker for marker in _CREDENTIAL_MARKERS if marker in reached}
    assert caught == {"S2S", "TOKEN"}, (
        "the scan no longer finds the credential in the expression the defect was written as, "
        "so a green result from it means nothing"
    )
