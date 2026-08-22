#!/usr/bin/env python3
"""Credential-free anti-rot check for the real Doc4 presenter demo.

Two stages, both executed, neither reading hard-coded prose:

1. **In-process** : the real :class:`DemoSession` runs the real UCP600 discrepancy check
   round by round and renders every presenter step.
2. **Served** : the real ``ThreadingHTTPServer`` is started on an ephemeral port and the
   whole presenter journey is driven over HTTP with ``POST /advance``. Every figure
   asserted at this stage is read out of the SERVED bytes through the stable ``data-*``
   evidence hooks and compared with the value the RUNNING app computed, so a renderer that
   stops emitting a figure, a server that stops advancing, or a hook that gets renamed all
   fail here. A step that only rendered in-process was invisible to the old check.

The headless-browser journey over the same served pages lives in
``tests/browser/test_served_demo_ui.py`` and needs the pinned ``[demo]`` extra.
"""

from __future__ import annotations

import re
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import render_trade_finance_ui as r  # sibling: the renderer whose hooks are asserted
from trade_finance_demo_server import STEPS, DemoSession, Handler


def _hook(html: str, attribute: str) -> str:
    """Read one stable ``data-*`` evidence hook out of served markup."""
    match = re.search(rf"{attribute}='([^']*)'", html) or re.search(rf'{attribute}="([^"]*)"', html)
    assert match, f"evidence hook {attribute} is missing from the served page"
    return match.group(1)


def _hooks(html: str, attribute: str) -> list[str]:
    """Read EVERY occurrence of one evidence hook, in document order."""
    return re.findall(rf"{attribute}='([^']*)'", html) or re.findall(
        rf'{attribute}="([^"]*)"', html
    )


def _only(html: str, attribute: str, expected: str) -> None:
    """A scalar figure may be repeated across panels, but never with two values."""
    found = _hooks(html, attribute)
    assert found, f"evidence hook {attribute} is missing from the served page"
    assert set(found) == {expected}, f"{attribute} served {sorted(set(found))}, app says {expected}"


def _material(report: dict) -> int:
    return sum(1 for d in report["discrepancies"] if d["severity"] != "low")


def check_in_process() -> None:
    session = DemoSession()
    page = session.render()
    assert session.data["rounds"][0]["report"]["discrepancies"]
    assert "data-demo='presenter-step'" in page
    while not session.at_end:
        session.advance()
        page = session.render()
        assert f"data-step='{session.idx}'" in page
    assert session.data["rounds"][-1]["report"]["verdict"] == "compliant"
    assert session.data["officer_decision"]["decision"] == "release"
    assert session.idx == len(STEPS) - 1 and "Demo complete" in page
    print("PASS demo: discrepancy reduction and four-eyes release rendered")


def check_served() -> None:
    """Drive the REAL server over HTTP and assert live figures from served bytes."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.session = DemoSession()  # type: ignore[attr-defined]
    server.lock = threading.Lock()  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    # The SESSION, not a snapshot of its ``data`` dict: ``reset()`` rebinds ``data`` to a
    # brand-new dict, so anything that caches the dict is reading a corpse the moment the
    # walkthrough restarts. Read it through the session every time.
    session = server.session  # type: ignore[attr-defined]

    try:
        for index in range(len(STEPS)):
            with urllib.request.urlopen(f"{base}/", timeout=20) as response:  # noqa: S310
                assert response.status == 200
                page = response.read().decode("utf-8")

            # The served page is at the step the served app believes it is at.
            assert _hook(page, "data-step") == str(index), f"served step marker is not {index}"

            # Live figures: served bytes vs what the RUNNING app computed this round.
            rnd = session.data["rounds"][-1]
            report = rnd["report"]
            _only(page, "data-report-lc", report["lc_number"])
            _only(page, "data-report-verdict", report["verdict"])
            _only(page, "data-report-review", str(bool(report["requires_human_review"])).lower())
            _only(page, "data-discrepancy-count", str(len(report["discrepancies"])))
            _only(page, "data-material-count", str(_material(report)))
            _only(page, "data-citation-count", str(len(report["citations"])))
            _only(page, "data-summary-lc", report["summary"]["lc_number"])
            _only(
                page,
                "data-summary-document-count",
                str(len(report["summary"]["documents_checked"])),
            )
            assert _hooks(page, "data-summary-document") == report["summary"]["documents_checked"]

            # Every discrepancy card, in order, with the rule id and severity the
            # deterministic detector assigned it.
            for attribute, expected in (
                ("data-discrepancy-kind", [d["kind"] for d in report["discrepancies"]]),
                ("data-discrepancy-rule", [d["ucp600_article"] for d in report["discrepancies"]]),
                ("data-discrepancy-severity", [d["severity"] for d in report["discrepancies"]]),
                ("data-discrepancy-doc", [d["doc_type"] for d in report["discrepancies"]]),
                (
                    "data-discrepancy-citations",
                    [str(len(d["citations"])) for d in report["discrepancies"]],
                ),
            ):
                assert _hooks(page, attribute) == expected, (
                    f"served {attribute} is {_hooks(page, attribute)}, app says {expected}"
                )

            # Result panels: the round pages and the officer-decision page differ, and both
            # sets are derived from the step the app is actually on.
            panels = _hooks(page, "data-panel")
            is_decision = STEPS[index]["key"] == "decision"
            required = (
                ("presentation-summary", "discrepancies", "officer-decision")
                if is_decision
                else ("presentation-summary", "discrepancies", "examination-verdict", "review-gate")
            )
            for slug in required:
                assert slug in panels, f"served step {index} lost the {slug} panel hook"

            if is_decision:
                decision = session.data["officer_decision"]
                _only(page, "data-officer-decision", decision["decision"])
                _only(page, "data-officer-maker", decision["maker"])
                _only(page, "data-officer-checker", decision["officer"])
                assert "Demo complete" in page
            else:
                request = urllib.request.Request(f"{base}/advance", method="POST", data=b"")
                with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
                    assert response.status in (200, 303)

        # The timeline / sources page must serve too, with every live citation present.
        with urllib.request.urlopen(f"{base}/timeline", timeout=20) as response:  # noqa: S310
            assert response.status == 200
            sources = response.read().decode("utf-8")
        citations = r.timeline_citations(session.data)
        assert citations, "the running app produced no citations to prove"
        assert "sources" in _hooks(sources, "data-panel")
        _only(sources, "data-source-count", str(len(citations)))
        served_sources = _hooks(sources, "data-citation-source")
        for citation in citations:
            assert citation["source_id"] in served_sources, citation["source_id"]
            assert citation["title"] in sources or citation["source_id"] in sources
        assert _hooks(sources, "data-timeline-discrepancies") == [
            str(len(rnd["report"]["discrepancies"])) for rnd in session.data["rounds"]
        ]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    print(
        "PASS served: every presenter step, panel hook and live figure read back over "
        "HTTP from the running demo server"
    )


def main() -> int:
    check_in_process()
    check_served()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
