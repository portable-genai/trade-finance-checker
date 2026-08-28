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

variable "docai_location" {
  description = <<-EOT
    Where the Document AI processor is CREATED. Deliberately NOT var.region.

    Document AI does not serve every Cloud region, and creating a processor in one it does not
    serve 404s at apply. It DOES serve asia-southeast1 -- and serves no us-central1 endpoint at
    all -- but Singapore is "limited support": a subset of processors, several in Preview, and
    access is gated behind Google's Document AI Single Region Request Form. Until that request
    is granted this routes to the `us` MULTI-REGION, which is a stated residency deviation:
    document bytes are extracted in the United States while the rest of the stack stays in
    region. Set this to asia-southeast1 the day access lands.

    Keep it equal to the runtime's TRADE_FINANCE_DOCAI_LOCATION, which selects the same location for
    the adapter. If the two disagree, Terraform creates the processor in one location and the
    adapter looks for it in another, and the failure surfaces as a confusing 404 at request
    time rather than at apply.

    `us` and `eu` are multi-regions, not `global`: each names ONE jurisdiction. Never widen
    this to a location the service does not serve just to make an apply succeed. Whichever is
    chosen, gcp.resourceLocations must be wide enough to permit it, and the
    residency claim must be stated at that width rather than at var.region's.
  EOT
  type        = string
  default     = "us"

  validation {
    # Mirrors the runtime rule: the deploy region, or a NAMED multi-region. `global` is refused
    # by name because it names no jurisdiction, and so is any other single region -- an
    # out-of-region single region would be a silent jurisdiction change dressed as a fix.
    condition     = contains(["us", "eu"], var.docai_location) || var.docai_location == var.region
    error_message = "docai_location must be the deploy region (var.region) or a named Document AI multi-region (us, eu). `global` names no jurisdiction and is refused."
  }
}
