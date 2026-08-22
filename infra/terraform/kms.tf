# Regional CMEK (Cloud KMS) for B4 (P-10). The same regional key encrypts Document AI
# output staging and the Cloud Logging WORM bucket. Region-pinned to asia-southeast1.

resource "google_kms_key_ring" "tfc" {
  name     = "trade-finance-checker"
  location = var.region
  project  = var.project_id

  depends_on = [google_project_service.required]
}

resource "google_kms_crypto_key" "tfc" {
  name            = "trade-finance-checker-cmek"
  key_ring        = google_kms_key_ring.tfc.id
  rotation_period = var.kms_rotation_period
  purpose         = "ENCRYPT_DECRYPT"

  labels = var.labels

  lifecycle {
    prevent_destroy = true
  }
}

# Allow the Cloud Logging service agent to use the key for the WORM bucket CMEK.
data "google_project" "this" {
  project_id = var.project_id
}

resource "google_kms_crypto_key_iam_member" "logging" {
  crypto_key_id = google_kms_crypto_key.tfc.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:cloud-logging@system.gserviceaccount.com"
}

resource "google_kms_crypto_key_iam_member" "storage" {
  crypto_key_id = google_kms_crypto_key.tfc.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:service-${data.google_project.this.number}@gs-project-accounts.iam.gserviceaccount.com"
}
