# Inputs. Only project_id, the residency values and genuinely per-tenant values are
# variables; everything else is concrete.
#
# P-01 residency: `region` is SELECTED AT DEPLOY TIME and validated against the residency
# allowlist (var.allowed_regions) so a caller fails fast rather than deploying to an
# unvetted, out-of-jurisdiction region. The default is asia-southeast1 (Singapore).

variable "project_id" {
  type        = string
  description = "GCP project id (must host all resources in var.region)."
}

variable "allowed_regions" {
  type        = list(string)
  description = <<-EOT
    Residency allowlist: the regions this regulated stack may be deployed to. The region is
    chosen at deploy time (var.region) and validated against this list to FAIL FAST, so an
    operator cannot accidentally deploy to an unvetted region. Extending this list is the
    deliberate residency review point: do it only after confirming the full managed stack
    (Document AI, DLP, Model Armor, Vertex/Agent Platform, CMEK, Logging) and your residency
    obligations are satisfied in that region.
  EOT
  default     = ["asia-southeast1"]

  validation {
    condition     = length(var.allowed_regions) > 0
    error_message = "allowed_regions must list at least one residency-approved region."
  }
}

variable "region" {
  type        = string
  description = <<-EOT
    Deployment region, SELECTED AT DEPLOY TIME. Defaults to asia-southeast1 (Singapore) but
    is overridable. Validated against var.allowed_regions so an unapproved region fails fast
    at `terraform plan` rather than deploying data out of jurisdiction.
  EOT
  default     = "asia-southeast1"

  validation {
    # Cross-variable validation (Terraform >= 1.9). Fails at plan time = setup time.
    condition     = contains(var.allowed_regions, var.region)
    error_message = "region must be one of var.allowed_regions (residency allowlist). Add it there first if that region is approved for this workload."
  }
}

variable "labels" {
  type        = map(string)
  description = "Common resource labels."
  default = {
    app        = "trade-finance-checker"
    catalog_id = "b4"
    group      = "doc"
    managed_by = "terraform"
  }
}

variable "audit_retention_days" {
  type        = number
  description = "WORM audit retention in days (~7 years). Locking is irreversible."
  default     = 2557
}

variable "kms_rotation_period" {
  type        = string
  description = "CMEK key rotation period."
  default     = "7776000s" # 90 days
}

variable "access_policy_id" {
  type        = string
  description = "Access Context Manager policy id for the VPC-SC perimeter (org-level)."
  default     = ""
}

variable "documentai_processor_display_name" {
  type        = string
  description = "Display name for the trade-document Document AI processor."
  default     = "trade-finance-doc-parser"
}
