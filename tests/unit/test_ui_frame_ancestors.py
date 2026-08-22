"""The UI's own clickjacking header, resolved in THREE states, never two.

The backend middleware only covers API responses. The document a browser actually frames is
served by Next.js, so the console emits its own ``frame-ancestors`` policy and that is the
header that governs framing of the checker page. It carried the identical two-state read the
backend did (``process.env.NEXT_PUBLIC_FRAME_ANCESTORS || "'self'"``), so closing the backend
alone would have left the governing header still reading an emptied allowlist as consent to
same-origin framing.

Red before that fix: evaluating the config with ``NEXT_PUBLIC_FRAME_ANCESTORS=""`` produced
``frame-ancestors 'self'`` + ``X-Frame-Options: SAMEORIGIN``, byte-for-byte identical to
leaving the variable unset. Green after: unset keeps the default, set-and-empty throws, and
set-and-valid is used.

The policy has since MOVED. ``ui/next.config.mjs`` no longer emits a
``Content-Security-Policy`` at all: the whole policy is built once in ``ui/lib/csp.mjs`` and
served by ``ui/proxy.ts``, because a script nonce is a per-request value the static
``headers()`` table cannot express, and a CSP emitted by two layers is two policies the
browser intersects. So these assertions now evaluate ``ui/lib/csp.mjs`` (the one policy
module, in a real node process) for the resolution itself, plus ``ui/next.config.mjs`` for
the boot refusal, which is what turns a set-but-empty allowlist into a build/start failure
rather than a surprise on some later request.

What these assertions CANNOT see is whether the served page hydrates under that policy; the
header is byte-identical in the working and the broken case. That is
``ui/scripts/assert-hydratable.mjs``, which executes the built server, and it is wired into
``make ui-check``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

_ENV = "NEXT_PUBLIC_FRAME_ANCESTORS"
_UI = Path(__file__).resolve().parents[2] / "ui"
_CSP = _UI / "lib" / "csp.mjs"
_CONFIG = _UI / "next.config.mjs"

# csp.mjs imports nothing at all, so this needs no node_modules.
_PROBE = """
const mod = await import(process.argv[1]);
const ancestors = mod.frameAncestors(process.env);
const csp = mod.contentSecurityPolicy(process.env, "test-nonce");
console.log(JSON.stringify({
  ancestors,
  csp,
  frameOptions: mod.frameOptions(ancestors),
}));
"""

# next.config.mjs resolves the allowlist at module scope for the side effect of refusing, and
# `next build` / `next start` both evaluate it. Importing it is exactly what they do.
_CONFIG_PROBE = """
await import(process.argv[1]);
console.log("loaded");
"""

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


@dataclass(frozen=True)
class _Load:
    """What evaluating the shipped module produced: either a policy, or a refusal."""

    returncode: int
    stdout: str
    stderr: str

    @property
    def loaded(self) -> bool:
        return self.returncode == 0

    @property
    def policy(self) -> dict[str, str]:
        assert self.loaded, f"the UI policy module refused: {self.stderr}"
        return dict(json.loads(self.stdout.strip().splitlines()[-1]))


def _run(script: str, module: Path, value: str | None) -> _Load:
    env = dict(os.environ)
    if value is None:
        env.pop(_ENV, None)
    else:
        env[_ENV] = value
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", script, module.as_uri()],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return _Load(completed.returncode, completed.stdout, completed.stderr)


def _load(value: str | None) -> _Load:
    """Evaluate ui/lib/csp.mjs with ``NEXT_PUBLIC_FRAME_ANCESTORS`` at ``value``."""
    return _run(_PROBE, _CSP, value)


def test_unset_ships_the_documented_default() -> None:
    policy = _load(None).policy
    assert "frame-ancestors 'self'" in policy["csp"]
    assert policy["frameOptions"] == "SAMEORIGIN"


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_set_and_empty_refuses(blank: str) -> None:
    """An emptied allowlist must not be indistinguishable from an unset one.

    Red before: this resolved cleanly to the same ``'self'`` default as
    :func:`test_unset_ships_the_documented_default`.
    """
    load = _load(blank)
    assert not load.loaded, (
        f"the UI policy resolved an emptied allowlist to {load.stdout.strip()!r}: "
        "an emptied allowlist is being read as consent to the default"
    )
    assert _ENV in load.stderr


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_set_and_empty_refuses_at_config_load(blank: str) -> None:
    """The refusal is a BUILD/BOOT refusal, not a per-request surprise.

    ``next build`` and ``next start`` both evaluate ``next.config.mjs``, so resolving the
    allowlist there for its side effect is what stops a console coming up serving a framing
    policy nobody chose.
    """
    load = _run(_CONFIG_PROBE, _CONFIG, blank)
    assert not load.loaded, "next.config.mjs loaded with an emptied framing allowlist"
    assert _ENV in load.stderr


def test_set_and_valid_reaches_the_emitted_policy() -> None:
    policy = _load("https://portal.client.example").policy
    assert "frame-ancestors https://portal.client.example" in policy["csp"]
    # A named allowlist has no X-Frame-Options spelling: emit none rather than a
    # contradiction.
    assert policy["frameOptions"] == ""


def test_an_explicit_refusal_ships_both_halves_of_the_control() -> None:
    policy = _load("'none'").policy
    assert "frame-ancestors 'none'" in policy["csp"]
    assert policy["frameOptions"] == "DENY"


def test_the_policy_is_more_than_a_framing_rule() -> None:
    """Shipping ``frame-ancestors`` and nothing else is not a policy.

    That is an anti-clickjacking rule, not a policy: with no ``default-src``, no
    ``script-src``, no ``object-src`` and no ``base-uri``, every fetch a page can make was
    default-ALLOW. The nonce itself is asserted against the SERVED document by
    ``ui/scripts/assert-hydratable.mjs``, because a header string cannot tell the working
    case from the broken one.
    """
    csp = _load(None).policy["csp"]
    for directive in ("default-src 'self'", "object-src 'none'", "base-uri 'self'"):
        assert directive in csp
    assert "'nonce-test-nonce' 'strict-dynamic'" in csp


# The FOURTH state: a wildcard. The backend refuses one; without the same refusal here the two
# halves of one embedding posture would answer differently, and the console's header is the one
# a browser honours for the DOCUMENT, so the permissive half would be the one that governs.


@pytest.mark.parametrize("value", ["*", "'self' https://*.client.example"])
def test_a_wildcard_allowlist_refuses(value: str) -> None:
    """Red before: both resolved and were emitted verbatim into the document policy.

    ``frame-ancestors *`` lets any page on the internet frame the console and drive it as the
    signed-in user, and the partial form is no better: ``https://*.client.example`` trusts every
    subdomain including one an attacker managed to take.
    """
    load = _load(value)
    assert not load.loaded, f"the policy resolved {value!r} to {load.stdout.strip()!r}"
    assert "wildcard" in load.stderr


def test_the_wildcard_refusal_leaves_the_other_three_states_alone() -> None:
    """The refusal adds ONE state. Unset, emptied and a named allowlist are unchanged."""
    assert _load(None).policy["ancestors"] == "'self'"
    assert not _load("").loaded
    assert _load("'none'").policy["ancestors"] == "'none'"
    assert _load("https://portal.client.example").policy["ancestors"] == (
        "https://portal.client.example"
    )
