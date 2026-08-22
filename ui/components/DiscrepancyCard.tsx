// Renders one detected discrepancy: kind, document/field, expected vs found, the UCP600
// article it breaches, severity, and the citations that back it (P-07).

import type { Discrepancy } from "../lib/types";
import { CitationList } from "./CitationChip";
import { SeverityBadge } from "./ui";

const KIND_LABEL: Record<string, string> = {
  amount_mismatch: "Amount mismatch",
  date_expired: "Presentation after expiry",
  late_shipment: "Late shipment",
  description_mismatch: "Goods description mismatch",
  missing_document: "Missing document",
  inconsistent_data: "Inconsistent data",
  ucp600_rule_breach: "UCP600 rule breach",
};

export function DiscrepancyCard({ discrepancy }: { discrepancy: Discrepancy }) {
  const kindLabel = KIND_LABEL[discrepancy.kind] || discrepancy.kind;
  return (
    <div className="rounded-lg border border-ink-200 bg-ink-50 p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-ink-800">
          {kindLabel}
          <span className="ml-2 font-mono text-xs font-normal text-ink-500">
            {discrepancy.doc_type}.{discrepancy.field}
          </span>
        </h3>
        <SeverityBadge severity={discrepancy.severity} />
      </div>
      <dl className="mt-2 grid grid-cols-1 gap-1 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-xs uppercase text-ink-400">Expected</dt>
          <dd className="text-ink-800">{discrepancy.expected}</dd>
        </div>
        <div>
          <dt className="text-xs uppercase text-ink-400">Found</dt>
          <dd className="text-ink-800">{discrepancy.found}</dd>
        </div>
      </dl>
      <p className="mt-2 text-xs text-ink-500">Breaches {discrepancy.ucp600_article}</p>
      <CitationList citations={discrepancy.citations} />
    </div>
  );
}
