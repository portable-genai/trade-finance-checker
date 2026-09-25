# Runbook : `trade-finance-checker` Trade-Finance Document Checker

Operational guide for deploying and running `trade-finance-checker` in `asia-southeast1`. The on-prem/test
profile needs none of this; this is the `gcp` (and `platform`) profile playbook.

## 1. Prerequisites

- A GCP project in `asia-southeast1` with billing enabled.
- `gcloud` authenticated; `terraform >= 1.6`.
- The `[gcp]` extra installed: `pip install -e ".[gcp,dev]"`.
- A regional Cloud KMS key for CMEK and a Document AI processor (created by Terraform).

## 2. Provision infrastructure (region fail-fast)

```bash
cd infra/terraform
terraform init
terraform plan -var project_id=your-sg-project        # review
terraform apply -var project_id=your-sg-project
```

`terraform plan` is the region fail-fast gate (P-01): `region` is chosen at deploy time and
refused unless it is in the `allowed_regions` residency allowlist (default
`["asia-southeast1"]`), and if a required service is unavailable in the selected region the
plan errors before anything is created. No global endpoints are used.

**Document AI is the documented exception, not a misconfiguration to escalate.** It is created
at `var.docai_location`, which defaults to the `us` multi-region because the service reaches
`asia-southeast1` only once Google grants the Document AI Single Region Request. Keep it equal
to the runtime's `TRADE_FINANCE_DOCAI_LOCATION`: if the two disagree the processor is created in
one location and looked for in another, and the failure surfaces as a 404 at request time
instead of at apply. Move both to `asia-southeast1` the day access lands. Neither side accepts
a location that is neither the deploy region nor a named multi-region: `global` is refused by
name at `terraform plan`, and again when the runtime loads its settings, so a service pointed
at an unlocated endpoint fails at startup rather than extracting bytes nobody can place. Do NOT
point any other service at a global endpoint to work around a region error; that is the failure
this gate exists to catch.

**Order matters for the WORM bucket.** The Cloud Logging locked bucket (`logging_worm.tf`)
is created with retention `2557` days and is **locked last**. Locking is **irreversible**:
once locked, the retention cannot be shortened and the bucket cannot be deleted until
retention elapses. Confirm the retention value before applying the lock.

## 3. Configure & run

```bash
export GOOGLE_CLOUD_PROJECT=your-sg-project
export TRADE_FINANCE_PROFILE=gcp
export TRADE_FINANCE_KMS_KEY="projects/.../locations/asia-southeast1/keyRings/.../cryptoKeys/..."
export TRADE_FINANCE_DOCAI_PROCESSOR="projects/.../locations/asia-southeast1/processors/..."
gcloud auth application-default login

make run-api        # FastAPI on :8094
```

Both live profiles route R8 reviews to `human-review-console`: set `HUMAN_REVIEW_URL` (plus the shared
`S2S_TOKEN` / `S2S_SIGNING_KEY` pair the platform delegates use). With review routing on (the
default) the process refuses to boot without it; to run without the console, say so with
`TRADE_FINANCE_REVIEW_ROUTING=off`. Under `gcp` the deployed console is an embedded app behind
the portal's IAP edge: `HUMAN_REVIEW_URL` is `https://<edge-host>/apps/human-review-console/api`
and `HUMAN_REVIEW_IAP_AUDIENCE` must name the deployment's IAP OAuth client id beside it. The
router then mints a Google-signed ID token for that audience with the service's own identity on
every submission, in place of the static `S2S_TOKEN`. Boot refuses `gcp` with routing on and
either variable missing (naming both), and refuses an audience that is the
`/projects/.../backendServices/...` path, which the edge would reject as a bearer audience. The
console must list this service's account in its `REVIEW_IAP_SERVICE_CALLERS_JSON`, or it
answers 403 and the report says `review_routing: "failed"`. A hand-off that fails at request time does not fail the
report (the WORM audit record stays the escalation of record), but the report carries
`review_routing: "failed"` and the service logs a warning. For the `platform` profile, also set `GUARDRAIL_GATEWAY_URL`, `KNOWLEDGE_BASE_URL`,
`QUALITY_GATE_URL`, `OBSERVABILITY_URL` to the `agent-guardrail-gateway`, `enterprise-knowledge-base`, `model-quality-gate`, `agent-observability` service endpoints, and
`AGENT_REGISTRY_URL` only if the deployment publishes the agent card to `agent-registry`.

## 4. Seed the governed UCP600 rule set (`enterprise-knowledge-base`)

`trade-finance-checker` does not vendor UCP600. Seed the `enterprise-knowledge-base` `ucp600-rules` collection with the articles the
detector maps discrepancies to:

```bash
python -m trade_finance_checker.pipelines.seed_rules   # lists the expected articles
```

Ingest those articles into `enterprise-knowledge-base` via its `/v1/ingest` surface (an `enterprise-knowledge-base` concern). `trade-finance-checker` retrieves them
at runtime via `RulesRetrievalPort` (R3).

## 5. Deploy the agent to Agent Runtime

```python
from vertexai import agent_engines
from trade_finance_checker.agent.root_agent import build_root_agent
from trade_finance_checker.config import Settings

remote = agent_engines.create(
    build_root_agent(Settings.load()),
    requirements=["google-adk==2.7.1", "trade-finance-checker"],
)  # record remote.resource_name in settings.agent_engine.resource_name
```

## 6. Promotion gate (`model-quality-gate`)

```bash
make eval                       # offline gate; must exit 0
python eval/run_eval.py --use-gcp   # the judged Gen AI evaluation service (needs creds)
```

A build is not promoted unless every metric (discrepancy recall, discrepancy precision,
citation accuracy, PII safety) clears its threshold. CI enforces it
(the hosted GitHub Actions check).

## 7. Key rotation & retention

- **CMEK rotation:** rotate the Cloud KMS key on your schedule; the regional key encrypts
  Document AI output staging and the log bucket. Rotating the key does not require a `trade-finance-checker`
  redeploy.
- **Audit retention:** `LoggingSettings.retention_days = 2557` (~7 years). The bucket is
  locked, so this is irreversible; plan the value carefully.

## 8. Kill switch

To stop serving checks immediately: scale the Agent Runtime / Cloud Run revision to zero, or
switch `TRADE_FINANCE_PROFILE` to a profile whose adapters refuse traffic. The deterministic
detector and audit trail mean any in-flight check has already been recorded.

**Runtime controls.** `TRADE_FINANCE_GUARDRAIL`, `TRADE_FINANCE_PII_REDACTION` and
`TRADE_FINANCE_REVIEW_ROUTING` each switch one cheap control. Each is read in three states:
unset is on, `true`/`false` (or `on`/`off`) wins, and an emptied or unrecognised value refuses
at boot. A process with any of them off logs one warning at startup naming each.

- **Pause escalations:** set `TRADE_FINANCE_REVIEW_ROUTING=off`. The ESCALATED audit rows are
  still written, and every check reports `review_routing: "off"` (API, agent tools, MCP tools,
  CLI), so the officer is told the report is not queued. Unsetting `HUMAN_REVIEW_URL` (or,
  under `gcp`, `HUMAN_REVIEW_IAP_AUDIENCE`) does not pause anything: under `gcp` or `platform`
  with routing on, the process refuses to boot.
- **Redaction disclosure:** a check or extract whose presented LC or documents redaction
  changed carries `input_redacted: true`, and the console says so.
- **Redaction tuning:** DLP masks only `LIKELY` findings, replaces each with its info-type name
  (`[PERSON_NAME]`) rather than `#` characters, and excludes trade-finance vocabulary (UCP600,
  ISBP, Incoterms, bank roles, carriers) from `PERSON_NAME`, both inline and in the
  `infra/terraform/dlp.tf` templates. The local redactor leaves an amount after a currency
  marker (`SGD 90000000`) and an HS code (`HS code 8471300000`) alone.
