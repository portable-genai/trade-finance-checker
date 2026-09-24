// Small presentational primitives shared across the B4 console.

import type { ReactNode } from "react";
import type { ReviewRouting } from "../lib/types";

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

export function ReviewBanner({ routing }: { routing?: ReviewRouting }) {
  return (
    <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
      <strong>Human review required (maker-checker, P-06).</strong> This report is decision
      support, not an approval. A trade-finance officer must review before the bank acts (pay,
      refuse, or seek a waiver).
      {routing && routing !== "not_required" ? (
        <p
          data-review-routing={routing}
          className={`mt-1 text-xs font-medium ${
            routing === "routed" ? "text-emerald-800" : "text-rose-800"
          }`}
        >
          {REVIEW_ROUTING_TEXT[routing]}
        </p>
      ) : null}
    </div>
  );
}

/** What happened to the hand-off to the review console, in plain words. */
const REVIEW_ROUTING_TEXT: Record<Exclude<ReviewRouting, "not_required">, string> = {
  routed: "Sent to the review console.",
  failed: "Could not reach the review console; this report is not queued for review.",
  off: "Review routing is off in this deployment; this report is not queued for review.",
};

/** Shown when redaction changed the presented LC or documents before the model saw them. */
export function RedactionNotice() {
  return (
    <div
      role="note"
      data-input-redacted="true"
      className="rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-xs text-sky-900"
    >
      Personal data in your input was masked before the model saw it.
    </div>
  );
}
