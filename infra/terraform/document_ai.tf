# Document AI processor for parsing the LC and the presented trade documents (regional).
# Created in asia-southeast1 so document parsing stays in-country (P-01).

resource "google_document_ai_processor" "trade_docs" {
  project      = var.project_id
  location     = var.region
  display_name = var.documentai_processor_display_name
  # A form/document parser is used to extract the structured fields the deterministic
  # detector reasons over (amount, currency, shipment_date, goods_description, ...).
  type = "FORM_PARSER_PROCESSOR"

  depends_on = [google_project_service.required]
}
