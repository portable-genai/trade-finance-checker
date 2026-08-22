# Enable the Google Cloud APIs B4 depends on. terraform plan is the region fail-fast gate:
# if a service is unavailable in asia-southeast1 the dependent resources error before apply.

locals {
  required_apis = [
    "documentai.googleapis.com",
    "discoveryengine.googleapis.com",
    "dlp.googleapis.com",
    "aiplatform.googleapis.com",
    "logging.googleapis.com",
    "cloudkms.googleapis.com",
    "modelarmor.googleapis.com",
    "accesscontextmanager.googleapis.com",
  ]
}

resource "google_project_service" "required" {
  for_each = toset(local.required_apis)

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}
