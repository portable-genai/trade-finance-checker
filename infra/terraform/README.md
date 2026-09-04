# Terraform : `trade-finance-checker` Trade-Finance Document Checker infrastructure

Managed-stack infrastructure for `trade-finance-checker`, defaulting to `asia-southeast1` (Singapore). Only
`project_id`, the residency values (`region`, `allowed_regions`) and an org `access_policy_id`
for the VPC-SC perimeter are variables; every resource location derives from `var.region`,
which is chosen at deploy time and validated against the `allowed_regions` allowlist (default
`["asia-southeast1"]`).

> Reference IaC. Do **not** run `terraform apply` as part of the build/gate. Review and apply
> deliberately in your own project (see [`../../docs/runbook.md`](../../docs/runbook.md)).

## Files

| File | Resources |
|------|-----------|
| `providers.tf` | Terraform + Google / Google-beta providers, region-pinned. |
| `variables.tf` | `project_id`, region (validated == `asia-southeast1`), retention, rotation, labels. |
| `apis.tf` | Enables Document AI, Discovery Engine, DLP, aiplatform, Logging, Cloud KMS, Model Armor, Access Context Manager. |
| `kms.tf` | Regional CMEK key ring + key (P-10) with service-agent IAM bindings. |
| `document_ai.tf` | Regional Document AI processor for parsing the LC + trade documents. |
| `dlp.tf` | DLP inspect + de-identify templates (trade-party PII, P-04). |
| `model_armor.tf` | Model Armor template for input/output screening (`agent-guardrail-gateway` / P-05). |
| `logging_worm.tf` | Locked WORM Cloud Logging bucket (~7y, irreversible) + audit sink (`agent-observability` / P-07). |
| `iam.tf` | Least-privilege runtime service account + role bindings (P-03). |
| `vpc_sc.tf` | VPC Service Controls perimeter (P-01); created only when `access_policy_id` is set. |
| `agent_runtime.tf` | CMEK-encrypted staging bucket for the Agent Runtime deploy. |
| `outputs.tf` | Resource ids the runtime needs (CMEK key, Document AI processor, DLP templates, WORM bucket, SA). |

## Region fail-fast (P-01)

`terraform plan` is the region gate: if any required service is unavailable in the selected
region the dependent resources error before anything is created. There are no global
endpoints, and `region` is validated against `allowed_regions`, so a region outside the
residency allowlist is refused at plan time. Document AI is the one service that does not take
`region`: it has its own validated `docai_location` (default `us`) because it reaches
`asia-southeast1` only once Google grants single-region access. Extending `allowed_regions` is the deliberate
residency review point.

## WORM bucket warning (P-07)

`logging_worm.tf` sets `locked = true` with `retention_days = 2557`. **Locking is
irreversible**: retention cannot be shortened and the bucket cannot be deleted until
retention elapses. Confirm the retention value before apply.

## Usage

```bash
terraform init
cp terraform.tfvars.example terraform.tfvars   # edit project_id
terraform plan
terraform apply
```

After apply, wire the outputs into the runtime env (see the runbook): `TRADE_FINANCE_KMS_KEY`,
`TRADE_FINANCE_DOCAI_PROCESSOR`, `TRADE_FINANCE_DLP_INSPECT_TEMPLATE`,
`TRADE_FINANCE_DLP_DEIDENTIFY_TEMPLATE`.
