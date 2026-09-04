# Demo guide - `trade-finance-checker` Trade-Finance Document Checker

Step-by-step scripts for demoing `trade-finance-checker` two ways:

- **Demo A - Documentary-credit examination over several presentation rounds** (the
  headline flow): a beneficiary presents documents under a Letter of Credit, the
  deterministic detector finds discrepancies against the LC terms and UCP600, the bank
  issues a discrepancy advice, the beneficiary re-presents corrected documents over a
  couple of rounds, the verdict flips to COMPLIANT, and a trade-finance officer records
  the release decision under four-eyes maker-checker. Runs **fully offline** (no cloud,
  no API key).
- **Demo B - One-shot check on the managed GCP stack**: the same examination producing a
  cited DiscrepancyReport against real Document AI / Gemini / Model Armor / DLP in
  `asia-southeast1`, shown over the REST endpoint and the Next.js console.

- **Demo C - YOUR presentation under the `live` profile** (the audience-facing demo):
  the presentation data is whatever the audience brings. Download the presentation
  template (`GET /v1/presentations/template`, or the link in the UI), fill in a real LC
  and its documents, and check it: the LC is claimed for your verified tenant on first
  check (`POST /v1/lcs`; another tenant's LC still denies), every discrepancy verdict
  comes from the deterministic detector, and the report prose is generated on a local
  Gemma model server. Rule citations reference the real UCP600 article numbers with the
  official ICC publication page as the verification link; the requirement text is this
  project's own paraphrase because the ICC licenses the full text.

> The synthetic trade data in Demos A/B is **fictional**. Do not run against live
> customer or transaction data without your own legal, security and model-risk sign-off.

### Demo C in three commands

```bash
# 1. Start a local OpenAI-compatible model server on :8001 (MLX / Ollama / vLLM).

# 2. Serve under the live profile.
TRADE_FINANCE_PROFILE=live python -m trade_finance_checker.api.app

# 3. In the UI (:3000): download the template, edit the LC + documents, Check presentation.
#    (The UI registers the LC for your tenant automatically before checking.)
```

---

## 0. Prerequisites

| Need | Demo A (local) | Demo B (GCP) | Notes |
|------|:--:|:--:|-------|
| `git` | yes | yes | clone the repo |
| **Python 3.12+** | yes | yes | the package pins `>=3.12` |
| Node.js 18+ and npm | for the UI | for the UI | only if you show the browser console |
| **Playwright** (`pip install playwright` + `playwright install chromium`) | for the guided walkthrough | no | Demo A's presenter walkthrough only |
| A GCP project + `gcloud` | no | yes | billing enabled; `asia-southeast1` available |
| Terraform | no | yes | provisions Document AI, DLP, WORM bucket, CMEK |
| Cloud KMS key (regional) | no | yes | CMEK; set `TRADE_FINANCE_KMS_KEY` |

Install/setup references (read these once):

- Local install and profiles -> [README 4.1 `local`](README.md#41-local-profile-a-working-offline-stack-no-gcp-no-api-key)
- GCP install and deploy -> [README 4.3 `gcp`](README.md#43-gcp-profile-real-managed-stack-in-asia-southeast1) and [`docs/runbook.md`](docs/runbook.md)
- Running the surfaces (API / CLI / UI) -> [README 5](README.md#5-running-the-surfaces)
- The check pipeline -> [README 6](README.md#6-the-check-pipeline-full-r1-safety)
- The demo scripts -> [`scripts/README.md`](scripts/README.md)
- The UI console -> [`ui/README.md`](ui/README.md)
- Config (`${ENV_VAR}` resolved at load) -> [`config/settings.yaml`](config/settings.yaml)

---

## 1. Common setup (both demos)

```bash
git clone https://github.com/portable-genai/trade-finance-checker.git
cd trade-finance-checker

python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # core + dev tooling (NO google-cloud-* packages)

# Sanity check the offline stack before presenting:
export TRADE_FINANCE_PROFILE=local
make lint test                   # ruff + mypy + pytest (all local, no cloud)
```

See [README 4.1](README.md#41-local-profile-a-working-offline-stack-no-gcp-no-api-key) for details.

---

## 2. Demo A - Documentary-credit examination over rounds (local, offline)

The check pipeline runs entirely in-process on the `local` profile (SQLite FTS5 over
UCP600 + a deterministic LLM), so it needs **no Google Cloud and no API key** - ideal for
a laptop demo. Four ways to present it, in order of polish.

### 2.1 Guided, presenter-controlled walkthrough (recommended)

A real browser opens; the script narrates each step and **waits for you to press Enter**
before performing it, so you control the pace. (One-time: `pip install playwright &&
playwright install chromium`.)

```bash
# Terminal 1 - the live demo server (http://localhost:8095)
source .venv/bin/activate
PYTHONPATH=src:tests python scripts/trade_finance_demo_server.py

# Terminal 2 - the guided walkthrough (a Chrome window opens)
source .venv/bin/activate
python scripts/trade_finance_demo_playwright.py
```

You'll step through, pressing Enter each time:

1. **First presentation** - invoice + bill of lading -> **7 discrepancies** (amount over
   the credit, EUR vs USD currency, goods description mismatch, late shipment, missing
   insurance for a CIF credit); verdict DISCREPANT, discrepancy advice issued.
2. **Round 1** - beneficiary corrects the invoice (amount + currency) and ships in time ->
   only the missing insurance document remains; still DISCREPANT.
3. **Round 2** - beneficiary adds an insurance document covering 110% of the credit value
   -> **0 discrepancies**, verdict **COMPLIANT**.
4. **Officer review** - a trade-finance officer records the release decision under
   four-eyes maker-checker (P-06).

**What to point at on screen:** the verdict pill (DISCREPANT -> COMPLIANT), each
discrepancy card's expected-vs-found with its UCP600 article and citation chips (LC /
UCP600 / DOC), the discrepancy count shrinking each round, and the green "no discrepancies"
panel in Round 2. Full options (`SLOWMO_MS`, `HEADLESS`, `CHROME_PATH`, ...) are in
[`scripts/README.md`](scripts/README.md).

### 2.2 Manual, click-through (no Playwright)

Run only the server and drive it yourself in any browser:

```bash
PYTHONPATH=src:tests python scripts/trade_finance_demo_server.py     # http://localhost:8095
```

Open `http://localhost:8095` and click **Next** to advance the real examination, **Restart**
to reset. Same four steps as above.

To show the **real Next.js console** instead, run the API and the UI (this is the actual
product surface, not the demo server):

```bash
make run-api PROFILE=local        # FastAPI on :8094, profile=local
cd ui && npm install && npm run build && npm run start
# -> production console on http://localhost:3000
```

Present from the BUILT console, never the dev server. `next dev` compiles with `eval` and
opens an HMR websocket, so it needs CSP relaxations a deployment must never carry; those
are emitted only outside `NODE_ENV=production` (see [`ui/lib/csp.mjs`](ui/lib/csp.mjs)).
`make run-ui` remains the developer loop, and it now hydrates, but a demo runs what ships.

The console (port 3000) reads `NEXT_PUBLIC_API_BASE` (default `http://localhost:8094`),
POSTs the pasted presentation to `/v1/check`, and renders the cited DiscrepancyReport. The
pre-filled sample is already a discrepant presentation, so "Check presentation" returns a
full set of cited findings.

### 2.3 Static artifacts (slides / screenshots)

Generate the audit-first pages and JSON without a browser:

```bash
PYTHONPATH=src:tests python scripts/trade_finance_demo.py trade_finance_demo.json   # prints the round-by-round summary
PYTHONPATH=src:tests python scripts/render_trade_finance_ui.py trade_finance_demo.json ./out
# -> ./out/tf-round-0.html, tf-round-1.html, tf-round-2.html, tf-timeline.html
```

Or in one shot: `make demo` (writes JSON + HTML into `./demo-out`).

### 2.4 One-shot check via the CLI (quick variant)

If you only want to show a single cited report (not the multi-round flow):

```bash
export TRADE_FINANCE_PROFILE=local
trade-finance-checker check eval/samples/presentation.json
# or: make check-local
```

It prints the verdict, each discrepancy (expected vs found, the UCP600 article breached,
and the LC / UCP600 / document citations), and the mandatory human-review banner.

---

## 3. Demo B - One-shot check on the managed GCP stack

Shows the same domain producing a cited DiscrepancyReport against **real managed services**
in `asia-southeast1`. Follow [`docs/runbook.md`](docs/runbook.md) for the authoritative
deploy steps; the short version:

### 3.1 GCP setup

```bash
source .venv/bin/activate
pip install -e ".[gcp,dev]"                 # adds google-adk, google-genai, documentai, dlp, ...

export GOOGLE_CLOUD_PROJECT=your-sg-project
export TRADE_FINANCE_PROFILE=gcp
export TRADE_FINANCE_KMS_KEY="projects/.../locations/asia-southeast1/keyRings/.../cryptoKeys/..."
gcloud auth application-default login
```

### 3.2 Provision infra (one-time)

```bash
make tf-plan          # review the plan - the WORM bucket lock is IRREVERSIBLE
cd infra/terraform && terraform apply && cd ../..
# Export the outputs the app reads (see docs/runbook.md):
export TRADE_FINANCE_DOCAI_PROCESSOR="$(terraform -chdir=infra/terraform output -raw documentai_processor_id)"
export TRADE_FINANCE_DLP_INSPECT_TEMPLATE="$(terraform -chdir=infra/terraform output -raw dlp_inspect_template)"
export TRADE_FINANCE_DLP_DEIDENTIFY_TEMPLATE="$(terraform -chdir=infra/terraform output -raw dlp_deidentify_template)"
```

Details and gotchas (region fail-fast, key rotation, retention): [`docs/runbook.md`](docs/runbook.md).

### 3.3 Run and show

```bash
make run-api          # FastAPI on :8094, profile=gcp
```

Then demo any surface ([README 5](README.md#5-running-the-surfaces)):

```bash
# REST - examine a presentation
curl -s localhost:8094/v1/check -H 'content-type: application/json' -d '{
  "lc": {
    "lc_number": "LC-DEMO-2026-0917",
    "amount": 120000.00, "currency": "USD",
    "expiry_date": "2026-06-30", "latest_shipment": "2026-05-31",
    "incoterm": "CIF",
    "beneficiary": "Fictional Exporters Pte Ltd",
    "applicant": "Imaginary Importers Co",
    "terms": {
      "goods_description": "1000 cartons of organic arabica coffee beans grade A",
      "documents_required": "invoice, bill_of_lading, insurance"
    }
  },
  "documents": [
    {"doc_type": "invoice", "fields": {"amount": "138500.00", "currency": "EUR", "goods_description": "assorted dried agricultural produce", "issue_date": "2026-05-18"}},
    {"doc_type": "bill_of_lading", "fields": {"shipment_date": "2026-06-08", "goods_description": "assorted dried agricultural produce"}}
  ]
}' | python -m json.tool
# The audit actor is the server-verified identity, not a body field. In local mode select a
# demo persona with the X-Dev-Persona header, e.g. add: -H 'x-dev-persona: approver'

# Agent card / health
curl -s localhost:8094/.well-known/agent-card.json | python -m json.tool
curl -s localhost:8094/healthz
```

Or the browser console (talks to the API on :8094) - see [`ui/README.md`](ui/README.md):

```bash
cd ui && npm install && npm run build && npm run start   # http://localhost:3000
```

**What to highlight:** the verdict and every discrepancy carry a source citation (the LC
term, the UCP600 article, the presented document); trade-party PII (beneficiary /
applicant) is redacted before any model, trace, or audit write; the report is **always**
marked human-review (maker-checker, P-06); the LLM only drafts the narrative and can never
invent, suppress, or override a finding; everything stays in `asia-southeast1` with CMEK
([README 8](README.md#8-security--residency-posture)).

---

## 4. Talking points

- **The verdict is deterministic, not the model's.** The discrepancy set and the
  COMPLIANT / DISCREPANT verdict are computed by pure code over the parsed LC and the
  extracted fields (replayable by an examiner); the LLM only narrates. That is what makes
  the finding auditable.
- **Every finding is cited.** Each discrepancy names the UCP600 article it breaches and
  the LC term and presented document behind it (P-07) - a finding an officer cannot trace
  to a rule is worthless.
- **It's a presentation workflow, not a one-shot.** A documentary credit usually clears
  over several rounds of discrepancy advice and re-presentation; the rounds show the count
  shrinking until the presentation complies.
- **Decision support, never approval.** Every report is flagged human-review; a
  trade-finance officer makes the pay / refuse / waiver call under four-eyes (P-06).
- **Guardrails hold.** Redact-before-everything, guardrail screen on input and output,
  WORM audit, single-region + CMEK residency.

---

## 5. Troubleshooting and cleanup

| Symptom | Fix |
|---------|-----|
| `python3.12: command not found` | Install Python 3.12+; the package pins `>=3.12`. |
| Playwright: "executable doesn't exist" | `playwright install chromium`, or set `CHROME_PATH=/path/to/chrome`. |
| No display for the headed walkthrough | Use 2.2 (manual browser) on a machine with a display, or `HEADLESS=1 DEMO_AUTO=1 python scripts/trade_finance_demo_playwright.py` to self-run. |
| "Cannot reach the demo server" | Start 2.1 Terminal 1 first; or set `DEMO_URL` if you changed `--port`. |
| Port 8095 / 8094 in use | `python scripts/trade_finance_demo_server.py --port 9000` (then `DEMO_URL=http://127.0.0.1:9000`); API port via `PORT=... make run-api`. |
| UI shows a fetch error | Start `make run-api` first; the console reads `NEXT_PUBLIC_API_BASE` (default `http://localhost:8094`). |
| CLI exits with code 2 | You're on `TRADE_FINANCE_PROFILE=onprem` (fail-fast). Use `local` (Demo A) or `gcp` (Demo B). |
| GCP deploy/region/VPC-SC errors | See [`docs/runbook.md`](docs/runbook.md). |

**Stop / clean up:** Ctrl-C the demo server, `make run-api`, and the console. For GCP,
scale the deployment to zero or remove the app SA's model permission - the audit trail
remains intact ([runbook 8 Kill switch](docs/runbook.md#8-kill-switch)). `make clean`
removes local caches; `rm -rf demo-out trade_finance_demo.json` removes demo artefacts.
