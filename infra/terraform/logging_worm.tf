# Cloud Logging WORM bucket (lockable) + sink for the immutable audit trail (A5 / P-07).
# Retention is ~7 years; the bucket is LOCKED, which is IRREVERSIBLE. Lock it last, after
# verifying the retention value (see docs/runbook.md).

resource "google_logging_project_bucket_config" "worm" {
  project        = var.project_id
  location       = var.region
  bucket_id      = "trade-finance-checker-worm"
  description    = "WORM audit bucket for B4 trade-finance checks (lockable, ~7y retention)."
  retention_days = var.audit_retention_days

  # Locking is irreversible: retention cannot be shortened and the bucket cannot be deleted
  # until retention elapses. Keep this true in production.
  locked = var.worm_locked

  dynamic "cmek_settings" {
    for_each = var.cmek_enabled ? [1] : []
    content {
      kms_key_name = one(google_kms_crypto_key.tfc[*].id)
    }
  }

  depends_on = [google_kms_crypto_key_iam_member.logging]
}

# Route the audit log to the WORM audit bucket. The log name matches LoggingSettings.log_name.
resource "google_logging_project_sink" "audit" {
  project     = var.project_id
  name        = "trade-finance-checker-audit-sink"
  destination = "logging.googleapis.com/${google_logging_project_bucket_config.worm.id}"
  filter      = "logName=\"projects/${var.project_id}/logs/trade-finance-checker-audit\""

  unique_writer_identity = true
}
