# Demo scripts - Doc4 trade-finance documentary-credit examination

All scripts are SDK-free and run against the in-process `local` stack (no Google Cloud,
no API key). Run them from the repo root with the package and test fixtures on the path:

```bash
export PYTHONPATH=src:tests
export TRADE_FINANCE_PROFILE=local
```

| Script | What it does |
|--------|--------------|
| `trade_finance_demo.py` | Drives the synthetic LC presentation through 3 rounds (first presentation -> corrected -> compliant) and writes the report JSON (one entry per round + the officer decision). |
| `render_trade_finance_ui.py` | Renders that JSON into static audit-first HTML pages (one per round + a timeline) for screenshots / slides. |
| `trade_finance_demo_server.py` | A **live, click-through** server that runs the *real* `TradeCheckService` one round per click and renders the audit-first report UI. |
| `trade_finance_demo_playwright.py` | A **presenter-controlled** Playwright walkthrough of the live server: it narrates each step and waits for you to press Enter before performing it. |

## Static artifacts (slides / screenshots)

```bash
python scripts/trade_finance_demo.py trade_finance_demo.json
python scripts/render_trade_finance_ui.py trade_finance_demo.json ./out
# -> ./out/tf-round-0.html, tf-round-1.html, tf-round-2.html, tf-timeline.html
```

## Live, presenter-controlled demo

Two terminals:

```bash
# 1) the live demo server  (http://localhost:8095)
PYTHONPATH=src:tests python scripts/trade_finance_demo_server.py

# 2) the guided walkthrough  (a real Chrome window opens)
pip install playwright && playwright install chromium      # one-time
python scripts/trade_finance_demo_playwright.py
```

The walkthrough is **paced by you**: it prints what the next step will do, waits for you to
press **Enter**, then clicks **Next** and spotlights the panel to look at. The four steps
are: first presentation (7 discrepancies, DISCREPANT) -> Round 1 (corrected invoice + B/L,
fewer discrepancies) -> Round 2 (insurance added, COMPLIANT) -> officer release decision
(four-eyes maker-checker, P-06).

You can also just open `http://localhost:8095` and click **Next** / **Restart** by hand -
the server holds the live examination, so the buttons drive the same real pipeline. The
demo port (`8095`) is distinct from the API port (`8094`, `make run-api`) so both can run
side by side.

`make demo` runs the static-artifact path end to end (build JSON + render HTML into
`./demo-out`).

Useful environment overrides for `trade_finance_demo_playwright.py`:

| Var | Default | Purpose |
|-----|---------|---------|
| `DEMO_URL` | `http://127.0.0.1:8095` | server base URL (set to `http://localhost:3000` to narrate over the real Next.js console) |
| `HEADLESS=1` | off | run without a window (self-test / recording) |
| `DEMO_AUTO=1` | off | don't wait for Enter - advance automatically |
| `SLOWMO_MS` | `250` headed | per-action slow motion |
| `CHROME_PATH` | - | explicit Chromium/Chrome binary |
| `lock.py` | Compiles both lockfiles and puts the header back, because `uv pip compile` REPLACES the output file: it writes its own two-line provenance comment and destroys the `tag = commit` map the pin tests check against. `make lock` runs this rather than uv directly. |
