"""Presenter-controlled Playwright walkthrough of the live trade-finance demo.

Drives a headed browser through the documentary-credit examination flow served by
``scripts/trade_finance_demo_server.py``. It is **paced by the presenter**: before each
step it prints what is about to happen and waits for you to press Enter, then performs the
action (click "Next") and highlights the panel to look at. You stay in control of timing.

Usage (two terminals)::

    # terminal 1 — the live demo server
    PYTHONPATH=src:tests python scripts/trade_finance_demo_server.py

    # terminal 2 — the guided walkthrough (a real Chrome window opens)
    pip install playwright && playwright install chromium     # one-time
    python scripts/trade_finance_demo_playwright.py

Environment overrides:
    DEMO_URL    server base URL (default http://127.0.0.1:8095)
    HEADLESS=1  run headless (used for the self-test; no window)
    DEMO_AUTO=1 don't wait for Enter — advance automatically (self-test / recording)
    SLOWMO_MS   per-action slow-motion in ms (default 250 headed, 0 headless)
    CHROME_PATH explicit Chromium/Chrome binary (else Playwright's own)

It can also point at the real Next.js console (``make run-ui``) instead of the demo
server — set ``DEMO_URL=http://localhost:3000`` — but then it only narrates (the console
is a single-shot check form, so the per-round "Next" clicks are skipped automatically when
the demo control bar is absent).
"""

from __future__ import annotations

import contextlib
import os
import sys
import time

from playwright.sync_api import sync_playwright

BASE = os.environ.get("DEMO_URL", "http://127.0.0.1:8095")
HEADLESS = os.environ.get("HEADLESS") == "1"
AUTO = os.environ.get("DEMO_AUTO") == "1"
SLOWMO = int(os.environ.get("SLOWMO_MS", "0" if HEADLESS else "250"))
CHROME_PATH = os.environ.get("CHROME_PATH") or None

# (narration shown in the terminal, whether this step clicks "Next", panel to spotlight)
STEPS = [
    (
        "First presentation. The beneficiary presents an invoice and a bill of lading. "
        "Watch the deterministic detector flag SEVEN discrepancies — invoice amount over "
        "the credit, wrong currency, goods description mismatch, late shipment, and the "
        "missing insurance document for a CIF credit — verdict DISCREPANT.",
        False,
        ".panel",
    ),
    (
        "Round 1 — the beneficiary corrects the invoice (amount and currency) and presents "
        "a bill of lading shipped in time. The amount, currency, late-shipment and "
        "description findings clear; only the missing insurance document remains.",
        True,
        ".panel",
    ),
    (
        "Round 2 — the beneficiary adds the insurance document covering 110% of the credit "
        "value. Every discrepancy clears and the verdict flips to COMPLIANT: the "
        "discrepancies panel goes green.",
        True,
        ".empty",
    ),
    (
        "Officer review — a trade-finance officer records the maker-checker release decision "
        "(P-06): the checker is not the maker. The bank can honour the complying "
        "presentation. Examination complete.",
        True,
        ".release",
    ),
]


def _pause(prompt: str) -> None:
    if AUTO:
        time.sleep(1.2)
        return
    try:
        input(prompt)
    except EOFError:  # non-interactive stdin
        time.sleep(1.0)


def _spotlight(page, selector: str | None) -> None:
    if not selector:
        return
    with contextlib.suppress(Exception):  # cosmetic only
        page.eval_on_selector_all(
            selector,
            "els => els.forEach((e,i)=>{ if(i<6){ e.style.transition='box-shadow .3s';"
            " e.style.boxShadow='0 0 0 3px #3a60f0'; setTimeout(()=>e.style.boxShadow='',1600);} })",
        )


def _reachable() -> bool:
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(BASE, timeout=2):
            return True
    except (urllib.error.URLError, OSError):
        return False


def main() -> int:
    if not _reachable():
        print(f"Cannot reach the demo server at {BASE}.")
        print("Start it first:  PYTHONPATH=src:tests python scripts/trade_finance_demo_server.py")
        return 2

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS, slow_mo=SLOWMO, executable_path=CHROME_PATH)
        page = browser.new_context(viewport={"width": 1100, "height": 900}).new_page()

        print("\n=== Trade-finance live demo — press Enter to advance each step ===\n")
        # Reset to a clean state when driving the demo server (no-op elsewhere).
        with contextlib.suppress(Exception):
            page.goto(BASE + "/restart", wait_until="load")
        page.goto(BASE, wait_until="load")

        for i, (say, click, spotlight) in enumerate(STEPS):
            print(f"[{i + 1}/{len(STEPS)}] {say}")
            _pause("        press Enter to run this step... ")
            if click:
                btn = page.locator(".democtl button.next")
                if btn.count() and btn.is_enabled():
                    btn.click()
                    page.wait_for_load_state("load")
            page.wait_for_timeout(200)
            _spotlight(page, spotlight)
            page.wait_for_timeout(700)
            print()

        print("Demo complete. The browser stays open for questions.")
        _pause("        press Enter to close the browser... ")
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
