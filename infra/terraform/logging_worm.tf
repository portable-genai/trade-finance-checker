# Cloud Logging locked WORM bucket + sink for the immutable audit trail (A5 / P-07).
# Retention is ~7 years; the bucket is LOCKED, which is IRREVERSIBLE. Lock it last, after
# verifying the retention value (see docs/runbook.md).

resource "google_logging_project_bucket_config" "worm" {
  project        = var.project_id
  location       = var.region
  bucket_id      = "trade-finance-checker-worm"
  description    = "WORM audit bucket for B4 trade-finance checks (locked, ~7y retention)."
  retention_days = var.audit_retention_days

  # Locking is irreversible: retention cannot be shortened and the bucket cannot be deleted
  # until retention elapses. Keep this true in production.
  locked = true

  cmek_settings {
    kms_key_name = google_kms_crypto_key.tfc.id
  }

  depends_on = [google_kms_crypto_key_iam_member.logging]
}

# Route the audit log to the locked bucket. The log name matches LoggingSettings.log_name.
resource "google_logging_project_sink" "audit" {
  project     = var.project_id
  name        = "trade-finance-checker-audit-sink"
  destination = "logging.googleapis.com/${google_logging_project_bucket_config.worm.id}"
  filter      = "logName=\"projects/${var.project_id}/logs/trade-finance-checker-audit\""

  unique_writer_identity = true
}
