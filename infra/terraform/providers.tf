# Terraform + Google provider. Every resource takes its location from var.region, the
# allowlisted deploy-time region (default asia-southeast1, Singapore).
# Do NOT run terraform as part of the build; this is reference IaC.

terraform {
  required_version = ">= 1.6"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.50.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = ">= 6.50.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
}
