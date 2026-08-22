# Agent Runtime (ex-Agent Engine) hosting placeholder. The reasoningEngine resource is
# created by the Agent Platform SDK at deploy time (see docs/runbook.md), not by Terraform,
# because the agent package is built from this repo. This file reserves the staging bucket
# the deploy uses and records the intended display name.

resource "google_storage_bucket" "agent_staging" {
  name                        = "${var.project_id}-trade-finance-checker-agent-staging"
  project                     = var.project_id
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = false

  encryption {
    default_kms_key_name = google_kms_crypto_key.tfc.id
  }

  labels = var.labels

  depends_on = [google_kms_crypto_key_iam_member.storage]
}

# The reasoningEngine display name the deploy step uses; matches AgentEngineSettings.
locals {
  agent_display_name = "trade-finance-checker"
}
