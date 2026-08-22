# Sensitive Data Protection / DLP templates for de-identifying trade-party PII before it
# reaches a model, span, or audit sink (P-04 / R1). Regional, asia-southeast1.

resource "google_data_loss_prevention_inspect_template" "tfc" {
  parent       = "projects/${var.project_id}/locations/${var.region}"
  display_name = "trade-finance-checker-inspect"
  description  = "Detect trade-party PII (names, emails, NRIC/FIN, bank account numbers)."

  inspect_config {
    min_likelihood = "POSSIBLE"

    info_types { name = "PERSON_NAME" }
    info_types { name = "EMAIL_ADDRESS" }
    info_types { name = "PHONE_NUMBER" }
    info_types { name = "IBAN_CODE" }
    info_types { name = "SWIFT_CODE" }

    custom_info_types {
      info_type { name = "SG_NRIC_FIN" }
      likelihood = "POSSIBLE"
      regex { pattern = "[STFGM]\\d{7}[A-Z]" }
    }

    custom_info_types {
      info_type { name = "BANK_ACCOUNT_NUMBER" }
      likelihood = "POSSIBLE"
      regex { pattern = "\\b\\d[\\d-]{7,16}\\d\\b" }
    }
  }
}

resource "google_data_loss_prevention_deidentify_template" "tfc" {
  parent       = "projects/${var.project_id}/locations/${var.region}"
  display_name = "trade-finance-checker-deidentify"
  description  = "Mask detected trade-party PII with a single masking character."

  deidentify_config {
    info_type_transformations {
      transformations {
        primitive_transformation {
          character_mask_config {
            masking_character = "#"
          }
        }
      }
    }
  }
}
