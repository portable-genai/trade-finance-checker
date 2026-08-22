# VPC Service Controls perimeter (P-01). Keeps the managed services inside a service
# perimeter so trade-document data cannot egress to other projects or regions. The
# perimeter is org-scoped; supply an access_policy_id to create it.

resource "google_access_context_manager_service_perimeter" "tfc" {
  count = var.access_policy_id == "" ? 0 : 1

  parent = "accessPolicies/${var.access_policy_id}"
  name   = "accessPolicies/${var.access_policy_id}/servicePerimeters/trade_finance_checker"
  title  = "trade-finance-checker"

  status {
    resources = ["projects/${data.google_project.this.number}"]

    restricted_services = [
      "documentai.googleapis.com",
      "discoveryengine.googleapis.com",
      "dlp.googleapis.com",
      "aiplatform.googleapis.com",
      "logging.googleapis.com",
      "cloudkms.googleapis.com",
      "modelarmor.googleapis.com",
    ]

    vpc_accessible_services {
      enable_restriction = true
      allowed_services   = ["RESTRICTED-SERVICES"]
    }
  }
}
