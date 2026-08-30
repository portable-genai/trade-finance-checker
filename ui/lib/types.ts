// TypeScript projections of the B4 domain artifacts. These mirror the pydantic response
// models in src/trade_finance_checker/api/schemas.py one-for-one (enums as strings).

export type CitationType = "LC" | "UCP600" | "DOCUMENT";
export type Severity = "low" | "medium" | "high" | "critical";
export type ComplianceVerdict = "compliant" | "discrepant";

export type TradeDocType =
  | "invoice"
  | "bill_of_lading"
  | "insurance"
  | "packing_list"
  | "cert_origin"
  | "draft"
  | "other";

export type DiscrepancyKind =
  | "amount_mismatch"
  | "date_expired"
  | "late_shipment"
  | "description_mismatch"
  | "missing_document"
  | "inconsistent_data"
  | "ucp600_rule_breach";

export interface Citation {
  source_id: string;
  source_type: CitationType;
  title: string;
  url?: string;
  page?: number | null;
  snippet?: string;
  score?: number | null;
}

export interface Discrepancy {
  kind: DiscrepancyKind;
  ucp600_article: string;
  doc_type: TradeDocType;
  field: string;
  expected: string;
  found: string;
  severity: Severity;
  citations: Citation[];
}

export interface PresentationSummary {
  lc_number: string;
  currency: string;
  amount: number;
  expiry_date: string;
  latest_shipment: string;
  documents_checked: string[];
  terms: Record<string, string>;
}

export interface DiscrepancyReport {
  lc_number: string;
  documents_checked: string[];
  discrepancies: Discrepancy[];
  verdict: ComplianceVerdict;
  summary: PresentationSummary;
  requires_human_review: boolean;
  narrative: string;
  citations: Citation[];
  discrepancy_count: number;
  material_count: number;
  generated_at: string;
}

export interface LetterOfCreditInput {
  lc_number: string;
  amount: number;
  currency: string;
  expiry_date: string;
  latest_shipment: string;
  incoterm?: string;
  beneficiary?: string;
  applicant?: string;
  terms?: Record<string, string>;
}

export interface PresentedDocumentInput {
  doc_type: TradeDocType;
  fields: Record<string, string>;
  pages?: number;
  document_id?: string;
}

export interface CheckRequest {
  lc: LetterOfCreditInput;
  documents: PresentedDocumentInput[];
}

export interface Persona {
  id: string;
  subject: string;
  tenant: string;
  principals: string;
}

export interface Health {
  // Provenance the banner states on every page: where the runtime sits and which model
  // answers. Both come from the service; nothing in the console infers either.
  runtime: string;
  generator_model: string;
  status: string;
  profile: string;
  region: string;
}
