# Outputs : the resource ids the runtime needs in config/settings.yaml (via env vars).

output "region" {
  description = "Deployment region selected at deploy time (default asia-southeast1, Singapore)."
  value       = var.region
}

output "kms_key" {
  description = "Regional CMEK key id for TRADE_FINANCE_KMS_KEY."
  value       = google_kms_crypto_key.tfc.id
}

output "documentai_processor" {
  description = "Document AI processor resource name for TRADE_FINANCE_DOCAI_PROCESSOR."
  value       = google_document_ai_processor.trade_docs.id
}

output "dlp_inspect_template" {
  description = "DLP inspect template id for TRADE_FINANCE_DLP_INSPECT_TEMPLATE."
  value       = google_data_loss_prevention_inspect_template.tfc.id
}

output "dlp_deidentify_template" {
  description = "DLP de-identify template id for TRADE_FINANCE_DLP_DEIDENTIFY_TEMPLATE."
  value       = google_data_loss_prevention_deidentify_template.tfc.id
}

output "model_armor_template" {
  description = "Model Armor template id used by the guardrail adapter."
  value       = google_model_armor_template.tfc.template_id
}

output "audit_log_bucket" {
  description = "Locked WORM audit bucket id."
  value       = google_logging_project_bucket_config.worm.id
}

output "runtime_service_account" {
  description = "Least-privilege runtime service account email."
  value       = google_service_account.runtime.email
}

output "agent_staging_bucket" {
  description = "Staging bucket for the Agent Runtime deploy."
  value       = google_storage_bucket.agent_staging.name
}
