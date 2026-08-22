// Renders a full DiscrepancyReport: verdict, summary, narrative, and the discrepancies.

import type { DiscrepancyReport } from "../lib/types";
import { DiscrepancyCard } from "./DiscrepancyCard";
import { Panel, ReviewBanner, VerdictBadge } from "./ui";

export function ReportView({ report }: { report: DiscrepancyReport }) {
  return (
    <div className="space-y-4">
      <Panel>
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-ink-900">
              Presentation {report.lc_number}
            </h2>
            <p className="text-sm text-ink-500">
              {report.discrepancy_count} discrepancy(ies), {report.material_count} material
            </p>
          </div>
          <VerdictBadge verdict={report.verdict} />
        </div>
        {report.requires_human_review ? (
          <div className="mt-3">
            <ReviewBanner />
          </div>
        ) : null}
        {report.narrative ? (
          <p className="mt-3 whitespace-pre-line text-sm text-ink-800">{report.narrative}</p>
        ) : null}
      </Panel>

      <Panel title="Presentation summary">
        <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-3">
          <Field label="Currency" value={report.summary.currency} />
          <Field label="LC amount" value={String(report.summary.amount)} />
          <Field label="Expiry" value={report.summary.expiry_date} />
          <Field label="Latest shipment" value={report.summary.latest_shipment} />
          <Field
            label="Documents"
            value={report.summary.documents_checked.join(", ") || "(none)"}
          />
        </dl>
      </Panel>

      <Panel title={`Discrepancies (${report.discrepancy_count})`}>
        {report.discrepancies.length ? (
          <div className="space-y-3">
            {report.discrepancies.map((d, i) => (
              <DiscrepancyCard key={`${d.kind}-${d.field}-${i}`} discrepancy={d} />
            ))}
          </div>
        ) : (
          <p className="text-sm text-emerald-700">
            No discrepancies detected; the presentation appears to comply on its face, subject
            to officer review.
          </p>
        )}
      </Panel>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs uppercase text-ink-400">{label}</dt>
      <dd className="text-ink-800">{value}</dd>
    </div>
  );
}
