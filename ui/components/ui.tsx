// Small presentational primitives shared across the B4 console.

import type { ReactNode } from "react";

export function Panel({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <section className="rounded-xl border border-ink-200 bg-white p-5 shadow-panel">
      {title ? (
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-ink-500">
          {title}
        </h2>
      ) : null}
      {children}
    </section>
  );
}

const SEVERITY_CLASS: Record<string, string> = {
  low: "bg-ink-100 text-ink-700",
  medium: "bg-amber-100 text-amber-800",
  high: "bg-orange-100 text-orange-800",
  critical: "bg-red-100 text-red-800",
};

export function SeverityBadge({ severity }: { severity: string }) {
  const cls = SEVERITY_CLASS[severity] || "bg-ink-100 text-ink-700";
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-semibold uppercase ${cls}`}>
      {severity}
    </span>
  );
}

export function VerdictBadge({ verdict }: { verdict: string }) {
  const ok = verdict === "compliant";
  const cls = ok ? "bg-emerald-100 text-emerald-800" : "bg-red-100 text-red-800";
  return (
    <span className={`rounded-full px-3 py-1 text-sm font-bold uppercase ${cls}`}>
      {verdict}
    </span>
  );
}

export function ReviewBanner() {
  return (
    <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
      <strong>Human review required (maker-checker, P-06).</strong> This report is decision
      support, not an approval. A trade-finance officer must review before the bank acts (pay,
      refuse, or seek a waiver).
    </div>
  );
}
