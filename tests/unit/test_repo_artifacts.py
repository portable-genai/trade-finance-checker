"""The lockfile pin discipline, asserted rather than merely described.

Both lockfile headers, and `scripts/lock.py`'s docstring, name THIS file as the thing that proves
the pins. Until it existed the claim was decoration: the hand-maintained `tag = commit` map in
each header, and the agreement between the two lockfiles and `pyproject.toml`, were checked by
nothing at all. `scripts/lock.py` describes what that costs ("One catalog repo has been carrying
exactly this damage, with a red gate, since somebody ran the command and committed the result"),
and a header nobody proves decays the same way for the same reason.

The pin lives in two homes on purpose. `pyproject.toml` names a TAG, because that is the half a
human can review: a tag step says something, `4971c33 -> 8ad20fe` says nothing. The
lockfiles pin the COMMIT, because a tag is a movable pointer and a re-pushed one changes what
installs with no diff anywhere in the repo. Two homes for one pin is one home too many unless
something ties them together, so each header carries the `tag = commit` map and the tests below
assert the three-way agreement offline, with no network call.

These are cheap file assertions, deliberately: they run in the offline gate, need nothing but the
repo, and fail the build the moment a pin is downgraded, a header is destroyed by a bare
`uv pip compile`, or the two lockfiles drift apart.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: Each lockfile mapped to the `pyproject.toml` extra it is compiled with. `scripts/lock.py`
#: compiles exactly this set, and reads the core dependencies PLUS that one extra: a commons
#: declared only in a different extra is legitimately absent from another lockfile, so the
#: scoping has to be preserved here or the checks below invent failures.
_LOCK_EXTRA = {
    "requirements-dev.lock": "dev",
    "requirements-gcp.lock": "gcp",
    "requirements-demo.lock": "demo",
}
#: Discovered by glob, not read off the map above: a lockfile the repo ships that the map
#: does not name would otherwise escape every check below and sit on a superseded pin
#: indefinitely. The parity test beneath the constants keeps the two in step.
_LOCKFILES = tuple(sorted(path.name for path in _REPO_ROOT.glob("requirements-*.lock")))

#: `name[extras] @ git+URL@REF`, the shape a commons dependency is declared and pinned in. The
#: ref is captured loosely, on purpose: a check that only matched a 40-character commit would
#: skip straight past a lockfile pinned at a tag, which is the exact defect being guarded.
_GIT_PIN = re.compile(r"^([a-z0-9-]+)(?:\[[^\]]*\])?\s*@\s*git\+\S+?@(\S+)$")

#: The `#   <package>  v<tag> = <commit>` map a lockfile header carries, so the commit it pins
#: can be checked against the tag `pyproject.toml` names WITHOUT a network call.
_TAG_COMMIT_LINE = re.compile(
    r"^#\s+(?P<package>[a-z0-9-]+)\s+(?P<tag>v[0-9]\S*)\s*=\s*(?P<commit>[0-9a-f]{40})\s*$"
)


def test_every_shipped_lockfile_is_one_the_extra_map_names() -> None:
    """A third lockfile appearing on disk fails here, loudly, instead of being skipped."""
    named = tuple(sorted(_LOCK_EXTRA))
    assert named == _LOCKFILES, (
        f"lockfiles on disk {_LOCKFILES} do not match the extras the map names {named}"
    )


def _declared_refs(extra: str | None = None) -> dict[str, str]:
    """Commons package -> the git ref `pyproject.toml` declares, for core deps + one extra.

    ``extra=None`` reads the core dependencies alone, which is the set every lockfile in the
    repo has to carry.
    """
    data = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    requirements = list(data["project"].get("dependencies", []))
    if extra is not None:
        requirements.extend(data["project"].get("optional-dependencies", {}).get(extra, []))
    found: dict[str, str] = {}
    for requirement in requirements:
        match = _GIT_PIN.match(requirement.strip())
        if match:
            found.setdefault(match.group(1), match.group(2))
    return found


def _locked_refs(text: str) -> dict[str, str]:
    """Commons package -> the git ref a lockfile BODY pins it at."""
    found: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#"):
            continue
        match = _GIT_PIN.match(line)
        if match:
            found[match.group(1)] = match.group(2)
    return found


def _tag_commit_map(text: str) -> dict[str, tuple[str, str]]:
    """Package -> (tag, commit) from a lockfile HEADER."""
    found: dict[str, tuple[str, str]] = {}
    for raw in text.splitlines():
        match = _TAG_COMMIT_LINE.match(raw)
        if match:
            found[match["package"]] = (match["tag"], match["commit"])
    return found


def _lock_text(name: str) -> str:
    return (_REPO_ROOT / name).read_text(encoding="utf-8")


def test_pyproject_names_a_tag_so_a_bump_stays_readable() -> None:
    """The tag is the reviewable half of the pin; a diff of two shas says nothing to a human."""
    declared = _declared_refs()
    assert declared, "pyproject pins no commons by git+ at all; the repo pins three"
    for package, ref in sorted(declared.items()):
        assert re.fullmatch(r"v[0-9][0-9a-zA-Z.\-+]*", ref), (
            f"pyproject pins {package} at {ref!r}; it should name the release TAG, and the "
            "lockfiles should carry the commit that tag resolves to."
        )


@pytest.mark.parametrize("name", _LOCKFILES)
def test_every_commons_pyproject_declares_is_pinned_in_the_lockfile(name: str) -> None:
    """A commons that installs unlocked is a dependency nobody has pinned.

    Scoped the way `scripts/lock.py` scopes it: core dependencies plus this lockfile's own
    extra. Every commons in that set must appear in the compiled output, or the install this
    lockfile is supposed to make reproducible resolves one of them fresh at pip time.
    """
    declared = _declared_refs(_LOCK_EXTRA[name])
    locked = _locked_refs(_lock_text(name))
    missing = sorted(set(declared) - set(locked))
    assert not missing, (
        f"{name} does not pin {', '.join(missing)}, which pyproject declares by git+. "
        "Run `make lock` and commit the result."
    )
    unexpected = sorted(set(locked) - set(declared))
    assert not unexpected, (
        f"{name} pins {', '.join(unexpected)}, which pyproject does not declare for the "
        f"{_LOCK_EXTRA[name]!r} extra; the lockfile is stale or hand-edited."
    )


@pytest.mark.parametrize("name", _LOCKFILES)
def test_the_lockfile_pins_the_commons_to_a_commit_not_a_movable_tag(name: str) -> None:
    """A tag is a pointer somebody can move; a lockfile that pins one is not a lock.

    A re-pushed tag changes what installs with NO diff in the lockfile and nothing in the repo
    to notice it, which is the reproducible-install claim failing exactly where it is supposed
    to be strongest.

    SHAPE ONLY, and that is not enough on its own: an ANNOTATED TAG OBJECT's sha is also 40 hex
    characters, so this passes a lockfile pinned at `git rev-parse <tag>` output. The check that
    can tell the two apart is `test_each_locked_sha_is_a_commit_object_and_not_a_tag_object`
    below, which asks git rather than a regular expression.
    """
    locked = _locked_refs(_lock_text(name))
    assert locked, f"{name} pins no commons at all"
    for package, ref in sorted(locked.items()):
        assert re.fullmatch(r"[0-9a-f]{40}", ref), (
            f"{name} pins {package} at {ref!r}, which is not a 40-character commit sha. "
            "Dereference the tag with `git rev-list -n 1 <tag>` (NOT `git rev-parse <tag>`, "
            "which returns the annotated tag object) and pin the commit."
        )


@pytest.mark.parametrize("name", _LOCKFILES)
def test_the_header_ties_each_locked_commit_to_the_tag_pyproject_names(name: str) -> None:
    """The offline proof that the pinned commit IS the pinned tag.

    The header map is the only thing in the repo that connects the two homes of one pin, so it
    has to be PRESENT (a bare `uv pip compile` destroys it), COMPLETE (a package pinned in the
    body and absent from the map is unproven), and in agreement with both sides.
    """
    text = _lock_text(name)
    locked = _locked_refs(text)
    declared = _declared_refs(_LOCK_EXTRA[name])
    recorded = _tag_commit_map(text)
    assert recorded, (
        f"{name} carries no `tag = commit` header map. `uv pip compile` REPLACES its output "
        "file, so a bare compile deletes it: run `make lock`, which restores the header."
    )
    assert set(recorded) == set(locked), (
        f"{name}: the header map covers {sorted(recorded)} but the file pins {sorted(locked)}"
    )
    for package, (tag, commit) in sorted(recorded.items()):
        assert package in declared, f"{name} pins {package}, which pyproject does not declare"
        assert commit == locked[package], (
            f"{name}: the header records {package} at {commit}, the pin says {locked[package]}"
        )
        assert tag == declared[package], (
            f"{name}: the header records {package} {tag}, pyproject declares {declared[package]}"
        )


def test_every_lockfile_pins_each_commons_at_the_same_commit() -> None:
    """The dev gate, the shipped image and the browser job must install the same commons.

    A drift here is the worst kind: everything is green, because each lockfile is internally
    consistent, and the code that passed CI is not the code in the image.

    Written as an N-way comparison rather than a pair, because the repo now ships three
    lockfiles and the pair form did not survive the third: it unpacked `_LOCKFILES` into exactly
    two names and raised `ValueError: too many values to unpack` the moment
    `requirements-demo.lock` appeared beside them. That matters most for the demo lock in
    particular, because the browser job installs it ON TOP of the dev lock, so a demo lock left
    a release behind pulls a kit BACKWARDS on every run of the served-browser evidence.
    """
    by_file = {name: _locked_refs(_lock_text(name)) for name in _LOCKFILES}
    packages = sorted({package for pins in by_file.values() for package in pins})
    assert packages, "no lockfile pins any commons; the pin regex is not matching"
    for package in packages:
        pinned = {name: pins[package] for name, pins in by_file.items() if package in pins}
        assert len(set(pinned.values())) == 1, (
            f"{package} is pinned at more than one commit across the lockfiles: "
            + ", ".join(f"{name} -> {ref}" for name, ref in sorted(pinned.items()))
        )


def _make_lock_recipe() -> str:
    """The body of the Makefile's `lock` target, which is what `make lock` actually runs."""
    text = (_REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    match = re.search(r"^lock:.*?\n((?:\t.*\n)+)", text, re.M | re.S)
    assert match, "the Makefile has no `lock` target, so nothing regenerates the lockfiles"
    return match.group(1)


def test_make_lock_regenerates_every_lockfile_the_repo_ships() -> None:
    """A lockfile outside `make lock` drifts the moment a dependency is bumped.

    This is the root cause the demo lock demonstrated across eight repositories: the extra was
    pinned in `pyproject.toml`, the browser suite cited it, and no regeneration path compiled
    it, so it was never committed at all and the suite skipped for want of it.
    """
    reachable = _make_lock_recipe() + (_REPO_ROOT / "scripts" / "lock.py").read_text(
        encoding="utf-8"
    )
    uncovered = [name for name in _LOCKFILES if name not in reachable]
    assert not uncovered, (
        f"{', '.join(uncovered)} is shipped but `make lock` does not regenerate it"
    )
    assert "scripts/lock.py" in _make_lock_recipe(), (
        "`make lock` has to run the script, not open-code `uv pip compile`: a bare compile "
        "REPLACES its output file and destroys the `tag = commit` header these tests read"
    )


# --------------------------------------------------------------------------------------- #
# The pinned sha is a COMMIT object, asked of git rather than of a regular expression.
#
# Nothing about a sha says what KIND of object it names. `git rev-parse <annotated tag>` returns
# the tag object's sha, which is also 40 hex characters, so it satisfies every structural check
# above while installing nothing reproducible. Only an object store can tell the two apart.
#
# Offline: a LOCAL object store, never the network. `git ls-remote` would answer beautifully and
# would put the offline gate on the internet, which it must never be.
# --------------------------------------------------------------------------------------- #

#: A directory holding clones of the commons repos, one per package name. Set it when the
#: checkouts are not siblings of this repo. Read two-state deliberately: it names a search path
#: and grants nothing, and an emptied value simply finds no store, which is the same as unset.
_CHECKOUT_ROOT_ENV = "COMMONS_GIT_CHECKOUT_ROOT"


def _git(store: Path, *args: str) -> str | None:
    """Run git in ``store``; ``None`` when git is absent or the command failed."""
    if shutil.which("git") is None:  # pragma: no cover - git is present in the gate
        return None
    completed = subprocess.run(
        ["git", "-C", str(store), *args], capture_output=True, text=True, check=False
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def object_stores(package: str) -> list[Path]:
    """Every local git work tree that might hold ``package``'s objects, best guess first."""
    candidates: list[Path] = []
    root = os.environ.get(_CHECKOUT_ROOT_ENV, "").strip()
    if root:
        candidates.append(Path(root) / package)
    # The polyrepo workspace: every catalog repo sits next to the commons it pins.
    candidates.append(_REPO_ROOT.parent / package)
    return [
        path
        for path in candidates
        if path.is_dir() and _git(path, "rev-parse", "--git-dir") is not None
    ]


def git_object_type(store: Path, sha: str) -> str | None:
    """``commit`` / ``tag`` / ..., or ``None`` when this store does not have the object.

    A store that has never fetched the object is NO evidence, in either direction, so it is
    reported as absent and the caller keeps looking. Only a positive answer decides anything.
    """
    return _git(store, "cat-file", "-t", sha)


def pin_verdict(package: str, sha: str, tag: str) -> tuple[str, str] | None:
    """``(verdict, detail)`` from the first store that knows ``sha``, or None if none does."""
    for store in object_stores(package):
        kind = git_object_type(store, sha)
        if kind is None:
            continue
        if kind != "commit":
            return "not-a-commit", f"{store} says {sha} is a {kind} object, not a commit"
        # The store knows the object AND may know the tag; when it does, tie the two together.
        # `rev-list -n 1` dereferences an annotated tag to its commit, which `rev-parse` does
        # not, and that difference is the whole defect.
        dereferenced = _git(store, "rev-list", "-n", "1", tag) if tag else None
        if dereferenced is not None and dereferenced != sha:
            return "wrong-commit", f"{store} says {tag} is {dereferenced}, not {sha}"
        return "commit", str(store)
    return None


@pytest.mark.parametrize("name", _LOCKFILES)
def test_each_locked_sha_is_a_commit_object_and_not_a_tag_object(name: str) -> None:
    """Ask git what the pinned object IS. A regular expression cannot, and never could.

    Skips only when no local object store can answer for any package at all: a check with no
    evidence has proved nothing and must say so rather than pass. In this workspace the commons
    are cloned next to the repo, so it runs; in a bare CI checkout it skips, and the structural
    checks above are what hold the line there.
    """
    text = _lock_text(name)
    locked = _locked_refs(text)
    recorded = _tag_commit_map(text)
    checked: list[str] = []
    unknown: list[str] = []
    for package, sha in sorted(locked.items()):
        tag = recorded.get(package, ("", ""))[0]
        verdict = pin_verdict(package, sha, tag)
        if verdict is None:
            unknown.append(package)
            continue
        kind, detail = verdict
        assert kind == "commit", (
            f"{name} pins {package} at {sha}, and {detail}. An annotated tag object's sha is "
            "also 40 hex characters, so it passes every shape check while installing nothing "
            "reproducible. Dereference with `git rev-list -n 1 <tag>`, never `git rev-parse`."
        )
        checked.append(package)
    if not checked:
        pytest.skip(
            f"no local git object store holds any of {unknown}, so the pinned objects' TYPE "
            f"cannot be established offline. Clone the commons next to this repo, or set "
            f"{_CHECKOUT_ROOT_ENV} to a directory holding them."
        )


def test_the_object_type_check_can_tell_a_tag_object_from_a_commit(tmp_path: Path) -> None:
    """The positive control, on a repo built here: a green tick nobody proved is decoration.

    Builds a throwaway repository with an ANNOTATED tag, which is the only kind that produces a
    second 40-hex sha, and proves the helper distinguishes the two objects. Without this, a
    `git_object_type` that quietly returned None forever would make the test above skip its way
    to green in every environment.
    """
    if shutil.which("git") is None:  # pragma: no cover - git is present in the gate
        pytest.skip("git is not installed")
    store = tmp_path / "repo"
    store.mkdir()
    (store / "file.txt").write_text("synthetic", encoding="utf-8")
    for args in (
        ("init", "-q"),
        ("config", "user.email", "gate@example.invalid"),
        ("config", "user.name", "Gate"),
        ("add", "file.txt"),
        ("commit", "-q", "-m", "one"),
        ("tag", "-a", "v9.9.9", "-m", "annotated"),
    ):
        assert _git(store, *args) is not None, f"git {args[0]} failed building the fixture"
    commit = _git(store, "rev-list", "-n", "1", "v9.9.9")
    tag_object = _git(store, "rev-parse", "v9.9.9")
    assert commit and tag_object and commit != tag_object, (
        "the fixture did not produce an annotated tag, so it cannot prove the distinction"
    )
    assert git_object_type(store, commit) == "commit"
    assert git_object_type(store, tag_object) == "tag", (
        "`git rev-parse <annotated tag>` returns a TAG object whose sha is also 40 hex "
        "characters. That is the whole defect, and the check must be able to see it."
    )
    assert git_object_type(store, "0" * 40) is None, "an unknown object is not evidence"


# --------------------------------------------------------------------------------------- #
# The served-browser evidence: pinned, locked, and actually RUN somewhere.
#
# Every one of these three had to be true at once, and none of them was. The [demo] extra
# pinned playwright, `tests/browser/test_served_demo_ui.py` cited it, `make demo-browser`
# invoked it -- and no lockfile compiled the extra and no CI job installed a browser, so the
# suite skipped on every machine that ever ran it. A skip is reported as success, so the
# arrangement looked complete from every angle except the one that counts.
#
# These are file assertions and cannot prove the browser starts; that is what the CI job and
# `make demo-browser` do. What they prove is that the job still EXISTS and still names the
# lockfile, so the evidence cannot be silently unplugged again.
# --------------------------------------------------------------------------------------- #


def test_the_demo_extra_is_pinned_exactly_and_compiled_into_a_lockfile() -> None:
    """An unpinned browser driver is a demo that renders differently every week."""
    pyproject = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r'"playwright==[0-9]', pyproject), (
        "the [demo] extra must pin playwright EXACTLY; a range makes the browser evidence "
        "depend on the day it ran"
    )
    assert "requirements-demo.lock" in _LOCKFILES, (
        "the [demo] extra is declared but never compiled, so `pip install -r` cannot install "
        "it reproducibly and the browser suite skips for want of it. Run `make lock`."
    )
    assert re.search(
        r"^playwright==", (_REPO_ROOT / "requirements-demo.lock").read_text(encoding="utf-8"), re.M
    ), "requirements-demo.lock does not pin playwright; it was compiled without the extra"
