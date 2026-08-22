# Least-privilege service account for the B4 runtime (P-03). It can call Document AI, DLP,
# Model Armor, write audit logs, use the CMEK key, and run inference on Vertex/aiplatform.

resource "google_service_account" "runtime" {
  account_id   = "trade-finance-checker"
  display_name = "B4 Trade-Finance Checker runtime"
  project      = var.project_id
}

locals {
  runtime_roles = [
    "roles/documentai.apiUser",
    "roles/dlp.user",
    "roles/aiplatform.user",
    "roles/logging.logWriter",
    "roles/cloudtrace.agent",
    "roles/discoveryengine.viewer",
  ]
}

resource "google_project_iam_member" "runtime" {
  for_each = toset(local.runtime_roles)

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

# Allow the runtime SA to use the CMEK key.
resource "google_kms_crypto_key_iam_member" "runtime" {
  crypto_key_id = google_kms_crypto_key.tfc.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:${google_service_account.runtime.email}"
}
