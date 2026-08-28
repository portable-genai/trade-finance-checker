# Document AI processor for parsing the LC and the presented trade documents.
#
# P-01 (residency): PARTIAL, and stated rather than absorbed. Created at var.docai_location,
# which defaults to the `us` MULTI-REGION -- so LC and presentation bytes are parsed in the
# United States while the rest of the stack stays in Singapore. Document AI serves
# asia-southeast1 only once Google grants single-region access; set var.docai_location (and
# the runtime's TRADE_FINANCE_DOCAI_LOCATION) to asia-southeast1 the day it lands.

resource "google_document_ai_processor" "trade_docs" {
  project      = var.project_id
  location     = var.docai_location # NOT var.region: Document AI serves neither every region nor, yet, ours in-country
  display_name = var.documentai_processor_display_name
  # A form/document parser is used to extract the structured fields the deterministic
  # detector reasons over (amount, currency, shipment_date, goods_description, ...).
  type = "FORM_PARSER_PROCESSOR"

  depends_on = [google_project_service.required]
}
