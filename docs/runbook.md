# Runbook : Doc4 Trade-Finance Document Checker

Operational guide for deploying and running Doc4 in `asia-southeast1`. The on-prem/test
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
`["asia-southeast1"]`), and if Document AI (or any required service) is unavailable in the
selected region the plan errors before anything is created. Everything is regional; no global
endpoints are used.

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

For the `platform` profile, also set `HRZ_GUARDRAIL_URL`, `HRZ_KB_URL`, `HRZ_REGISTRY_URL`,
`HRZ_QUALITY_URL`, `HRZ_OBSERVABILITY_URL` to the Hrz1 to Hrz5 service endpoints.

## 4. Seed the governed UCP600 rule set (Hrz2)

Doc4 does not vendor UCP600. Seed the Hrz2 `ucp600-rules` collection with the articles the
detector maps discrepancies to:

```bash
python -m trade_finance_checker.pipelines.seed_rules   # lists the expected articles
```

Ingest those articles into Hrz2 via its `/v1/ingest` surface (an Hrz2 concern). Doc4 retrieves them
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

## 6. Promotion gate (Hrz4)

```bash
make eval                       # offline gate; must exit 0
python eval/run_eval.py --use-gcp   # the judged Gen AI evaluation service (needs creds)
```

A build is not promoted unless every metric (discrepancy recall, discrepancy precision,
citation accuracy, PII safety) clears its threshold. CI enforces it
(`.github/workflows/eval-gate.yaml`).

## 7. Key rotation & retention

- **CMEK rotation:** rotate the Cloud KMS key on your schedule; the regional key encrypts
  Document AI output staging and the log bucket. Rotating the key does not require a Doc4
  redeploy.
- **Audit retention:** `LoggingSettings.retention_days = 2557` (~7 years). The bucket is
  locked, so this is irreversible; plan the value carefully.

## 8. Kill switch

To stop serving checks immediately: scale the Agent Runtime / Cloud Run revision to zero, or
switch `TRADE_FINANCE_PROFILE` to a profile whose adapters refuse traffic. The deterministic
detector and audit trail mean any in-flight check has already been recorded.
