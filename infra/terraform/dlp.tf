# Sensitive Data Protection / DLP templates for de-identifying trade-party PII before it
# reaches a model, span, or audit sink (P-04 / R1). Regional, asia-southeast1.

resource "google_data_loss_prevention_inspect_template" "tfc" {
  parent       = "projects/${var.project_id}/locations/${var.region}"
  display_name = "trade-finance-checker-inspect"
  description  = "Detect trade-party PII (names, emails, NRIC/FIN, bank account numbers)."

  inspect_config {
    # Tuned against false positives (runtime-control contract, 2026-09-24), the same as the
    # adapter's inline config: only LIKELY findings, and a PERSON_NAME finding containing
    # trade-finance vocabulary (rules, instruments, bank roles, carriers) is excluded.
    min_likelihood = "LIKELY"

    info_types { name = "PERSON_NAME" }
    info_types { name = "EMAIL_ADDRESS" }
    info_types { name = "PHONE_NUMBER" }
    info_types { name = "IBAN_CODE" }
    info_types { name = "SWIFT_CODE" }

    # Each custom pattern is specific enough to be a finding in its own right, so it must clear
    # the LIKELY floor or it would never be masked.
    custom_info_types {
      info_type { name = "SG_NRIC_FIN" }
      likelihood = "VERY_LIKELY"
      regex { pattern = "[STFGM]\\d{7}[A-Z]" }
    }

    # The contiguous 9-17 digit shape the shared pack and the eval gate prove. The hyphen-
    # tolerant form this template used to carry matched every ISO date (2026-06-15), so it
    # masked the shipment and expiry dates out of the documents under examination.
    custom_info_types {
      info_type { name = "BANK_ACCOUNT_NUMBER" }
      likelihood = "VERY_LIKELY"
      regex { pattern = "\\b\\d{9,17}\\b" }
    }

    rule_set {
      info_types { name = "PERSON_NAME" }
      rules {
        exclusion_rule {
          matching_type = "MATCHING_TYPE_PARTIAL_MATCH"
          regex {
            pattern = "(?i)\\b(UCP ?600|ISBP|URR|URC|eUCP|ICC|SWIFT|MT ?7\\d\\d|Incoterms?|FOB|CIF|CFR|CIP|CPT|EXW|FCA|DAP|DPU|DDP|MAS|HKMA|Letter of Credit|Documentary Credit|Bill of Lading|Invoice|Packing List|Certificate|Beneficiary|Applicant|Issuing|Advising|Confirming|Nominated|Negotiating|Reimbursing|Bank|Port|Vessel|Voyage|Carrier|Shipping|Lines?|Terminal|Maersk|Evergreen|Ever Given|COSCO|Hapag|MSC)\\b"
          }
        }
      }
    }
  }
}

resource "google_data_loss_prevention_deidentify_template" "tfc" {
  parent       = "projects/${var.project_id}/locations/${var.region}"
  display_name = "trade-finance-checker-deidentify"
  description  = "Replace detected trade-party PII with its info-type name."

  deidentify_config {
    info_type_transformations {
      transformations {
        # "[PERSON_NAME]" rather than a run of "#": irreversible, and the model still reads
        # the document's shape.
        primitive_transformation {
          replace_with_info_type_config = true
        }
      }
    }
  }
}
