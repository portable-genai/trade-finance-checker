"""The half of the model-pills contract that lives in the BROWSER.

Every served console shows two small pills at the top right of every page: the model that
ANSWERED the last request, and ``Search`` when that answer used an online search tool (owner
decision, 2026-09-23). They replaced the full-width provenance banner, which named the model
configuration would call rather than the one that answered. The SERVICE half (the adapters note
what answered, ``api/app.py`` emits and exposes ``X-Answered-By`` / ``X-Search-Used``, and
``generator_model`` is the model the adapter calls) is pinned in
``tests/unit/test_answer_provenance.py`` and ``tests/unit/test_health_provenance.py``.

This file pins the other half, because the other half is the one that broke before. On
2026-09-04 eight consoles were found rendering NOTHING on every page load: the banner's health
call named ``/api/agent``, a same-origin route handler those trees do not ship, and the failure
branch renders nothing by design. Every service-side assertion was green throughout. A pill that
never leaves its configured state fails the same way, as an ABSENCE nobody notices, so the
whole chain is held here: where the component reads from, what it reads, where it is mounted,
and that the old banner is gone rather than rendering beside it.
"""

from __future__ import annotations

import re
from pathlib import Path

UI = Path("ui")
PILLS = UI / "components" / "ModelPills.tsx"
WATCHER = UI / "lib" / "answer-provenance.mjs"

#: Build output and vendored packages are not this console's source.
_NOT_SOURCE = frozenset({"node_modules", ".next", "dist", "out", "coverage"})


def _console_sources() -> list[Path]:
    """Every ``.ts``/``.tsx`` this console ships, build output and vendored trees pruned."""
    found: list[Path] = []
    pending = [UI]
    while pending:
        for child in pending.pop().iterdir():
            if child.is_dir():
                if child.name not in _NOT_SOURCE:
                    pending.append(child)
            elif child.suffix in {".ts", ".tsx"}:
                found.append(child)
    return sorted(found)


def test_the_pills_start_from_healthz_and_read_both_answer_headers() -> None:
    pills = PILLS.read_text(encoding="utf-8")
    assert "health()" in pills, "the pills do not start from the service's own /healthz"
    assert "generator_model" in pills and "runtime" in pills
    assert "watchAnswers(window, API_BASE" in pills, "the pills do not read the answer headers"
    watcher = WATCHER.read_text(encoding="utf-8")
    for header in ('"x-answered-by"', '"x-search-used"'):
        assert header in watcher, "the pills never read " + header
    assert (UI / "tests" / "answer-provenance.test.mjs").is_file()


def test_the_pills_reach_the_base_this_console_actually_serves() -> None:
    """The defect that shipped in eight consoles, stated as an assertion.

    This console has no same-origin proxy under ``ui/app/api``; it reaches its backend through
    the ``NEXT_PUBLIC_API_BASE`` resolved once in ``ui/lib/api``, which ``connect-src`` and the
    service's CORS allowlist already cover. A pill that named ``/api/agent`` here, or spelled a
    base of its own, would reach nothing and stay blank.
    """
    pills = PILLS.read_text(encoding="utf-8")
    assert not Path("ui/app/api").exists(), "a proxy appeared; it must forward both headers"
    assert '"/api/agent"' not in pills
    assert re.search(r'import \{ API_BASE, health \} from "\.\./lib/api"', pills)


def test_the_pills_are_mounted_in_the_layout_and_the_banner_is_gone() -> None:
    layout = (UI / "app" / "layout.tsx").read_text(encoding="utf-8")
    assert "<ModelPills />" in layout, "the pills are not mounted on every page"
    assert not (UI / "components" / "ProvenanceBanner.tsx").exists(), "the old banner is back"
    for source in _console_sources():
        text = source.read_text(encoding="utf-8")
        assert "ProvenanceBanner" not in text, f"{source} still references the banner"
        assert "· model " not in text, f"{source} still renders the banner sentence"


def test_the_pills_sit_fixed_at_the_top_right() -> None:
    """Fixed, so no page content can scroll or push them off screen; never hoisted above it."""
    pills = PILLS.read_text(encoding="utf-8")
    container = re.search(r'<div\s+className="([^"]+)"', pills)
    assert container, "the pills have no positioned container"
    classes = container.group(1).split()
    assert "fixed" in classes
    assert any(c.startswith("top-") for c in classes)
    assert any(c.startswith("right-") for c in classes)
    assert not [c for c in classes if c.startswith(("-top-", "-mt-", "-inset-"))]
