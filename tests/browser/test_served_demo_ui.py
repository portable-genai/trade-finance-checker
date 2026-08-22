"""F2: the presenter demo is driven through a real headless browser, not a string.

``scripts/demo_selftest.py`` starts the real server and reads the served bytes, which covers
the server/renderer path browserlessly. This file closes the other half: a pinned headless
Chromium loads the SERVED pages, clicks the presenter's own ``Next`` button, and reads every
asserted figure back out of the LIVE DOM through the stable ``data-*`` evidence hooks.
Nothing here is compared against hard-coded prose; every expectation is recomputed from the
running :class:`DemoSession`.

Playwright is pinned in the ``[demo]`` extra. The browser binary is a network download, so a
fork's day-one offline gate (D3) must not depend on it: the module skips (loudly, via
``-rs``) when the browser is absent, and ``make demo-browser`` runs it for anyone who has the
extra installed.
"""

from __future__ import annotations

import importlib.util
import sys
import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="the pinned [demo] extra is not installed"
)


def _load(name: str) -> ModuleType:
    """Import a sibling demo script the same way ``make demo-server`` does."""
    for path in (SCRIPTS, REPO_ROOT / "src", REPO_ROOT / "tests"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


demo_server = _load("trade_finance_demo_server")


def _material(report: dict) -> int:
    return sum(1 for d in report["discrepancies"] if d["severity"] != "low")


@pytest.fixture(scope="module")
def served() -> Iterator[tuple[str, Any]]:
    """The REAL demo server, on an ephemeral port, for the duration of the module.

    The SESSION is yielded, never a snapshot of its ``data`` dict: ``reset()`` rebinds
    ``data`` to a brand-new dict, so a cached reference goes stale the instant the
    walkthrough navigates to ``/restart`` and every later assertion silently compares the
    live DOM against a dead object.
    """
    server = ThreadingHTTPServer(("127.0.0.1", 0), demo_server.Handler)
    server.session = demo_server.DemoSession()
    server.lock = threading.Lock()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", server.session
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture(scope="module")
def page(served: tuple[str, Any]) -> Iterator[Any]:
    try:
        with playwright_api.sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
            except Exception as exc:  # pragma: no cover - environment-dependent
                pytest.skip(f"no pinned browser binary available: {exc}")
            context = browser.new_context()
            yield context.new_page()
            context.close()
            browser.close()
    except NotImplementedError as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"playwright cannot run here: {exc}")


def _attributes(page: Any, selector: str, attribute: str) -> list[str]:
    """Read one attribute off every matching element in the LIVE DOM, in document order."""
    return page.locator(selector).evaluate_all(
        f"els => els.map(e => e.getAttribute({attribute!r}))"
    )


def test_the_served_demo_walks_every_step_in_a_real_browser(
    page: Any, served: tuple[str, Any]
) -> None:
    base, session = served
    page.goto(f"{base}/restart", wait_until="load")

    steps = demo_server.STEPS

    for index in range(len(steps)):
        bar = page.locator("[data-demo='presenter-step']")
        assert bar.get_attribute("data-step") == str(index)

        report = session.data["rounds"][-1]["report"]
        is_decision = steps[index]["key"] == "decision"

        # Report-level figures, read out of the LIVE DOM and checked against the running app.
        for attribute, expected in (
            ("data-report-lc", report["lc_number"]),
            ("data-report-verdict", report["verdict"]),
            ("data-report-review", str(bool(report["requires_human_review"])).lower()),
            ("data-discrepancy-count", str(len(report["discrepancies"]))),
            ("data-material-count", str(_material(report))),
            ("data-citation-count", str(len(report["citations"]))),
        ):
            served_values = _attributes(page, f"[{attribute}]", attribute)
            assert served_values, f"step {index} rendered no {attribute} hook"
            assert set(served_values) == {expected}, (
                f"step {index} DOM says {attribute}={sorted(set(served_values))}, "
                f"the running app says {expected}"
            )

        # Every result panel the step is supposed to show.
        required = (
            ("presentation-summary", "discrepancies", "officer-decision")
            if is_decision
            else ("presentation-summary", "discrepancies", "examination-verdict", "review-gate")
        )
        for slug in required:
            assert page.locator(f"[data-panel='{slug}']").count() == 1, slug

        # Every discrepancy card, in order, with the rule id and severity the deterministic
        # detector assigned it.
        for attribute, expected_list in (
            ("data-discrepancy-kind", [d["kind"] for d in report["discrepancies"]]),
            ("data-discrepancy-rule", [d["ucp600_article"] for d in report["discrepancies"]]),
            ("data-discrepancy-severity", [d["severity"] for d in report["discrepancies"]]),
            (
                "data-discrepancy-citations",
                [str(len(d["citations"])) for d in report["discrepancies"]],
            ),
        ):
            assert _attributes(page, f"[{attribute}]", attribute) == expected_list, attribute

        assert (
            _attributes(page, "[data-summary-document]", "data-summary-document")
            == report["summary"]["documents_checked"]
        )

        if is_decision:
            decision = session.data["officer_decision"]
            banner = page.locator("[data-panel='officer-decision']")
            assert banner.get_attribute("data-officer-decision") == decision["decision"]
            assert banner.get_attribute("data-officer-maker") == decision["maker"]
            assert banner.get_attribute("data-officer-checker") == decision["officer"]
        else:
            page.locator("button.next:not([disabled])").click()
            page.wait_for_load_state("load")

    assert page.locator("button.next[disabled]").count() == 1
    assert "Demo complete" in page.content()


def test_the_timeline_page_serves_every_live_citation_in_the_browser(
    page: Any, served: tuple[str, Any]
) -> None:
    base, session = served
    renderer = _load("render_trade_finance_ui")
    citations = renderer.timeline_citations(session.data)
    assert citations, "the running app produced no citations to prove"

    page.goto(f"{base}/timeline", wait_until="load")
    assert page.locator("[data-panel='sources']").count() == 1
    assert page.locator("[data-panel='sources']").get_attribute("data-source-count") == str(
        len(citations)
    )

    served_sources = _attributes(page, "[data-citation-source]", "data-citation-source")
    content = page.content()
    for citation in citations:
        assert citation["source_id"] in served_sources, citation["source_id"]
        assert citation["title"] in content or citation["source_id"] in content

    assert _attributes(page, "[data-timeline-discrepancies]", "data-timeline-discrepancies") == [
        str(len(rnd["report"]["discrepancies"])) for rnd in session.data["rounds"]
    ]
