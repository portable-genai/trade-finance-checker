// Renders one examiner-grade citation (LC term / UCP600 article / document) as a chip.

import type { Citation } from "../lib/types";

const TYPE_LABEL: Record<string, string> = {
  LC: "LC",
  UCP600: "UCP600",
  DOCUMENT: "Doc",
};

export function CitationChip({ citation }: { citation: Citation }) {
  const label = TYPE_LABEL[citation.source_type] || citation.source_type;
  const page = citation.page != null ? ` p.${citation.page}` : "";
  const inner = (
    <span className="inline-flex items-center gap-1 rounded-md border border-regblue-200 bg-regblue-50 px-2 py-0.5 text-xs text-regblue-800">
      <span className="font-semibold">{label}</span>
      <span className="font-mono">
        {citation.source_id}
        {page}
      </span>
    </span>
  );
  if (citation.url) {
    return (
      <a href={citation.url} target="_blank" rel="noreferrer" title={citation.title}>
        {inner}
      </a>
    );
  }
  return <span title={citation.title}>{inner}</span>;
}

export function CitationList({ citations }: { citations: Citation[] }) {
  if (!citations.length) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {citations.map((c, i) => (
        <CitationChip key={`${c.source_type}-${c.source_id}-${i}`} citation={c} />
      ))}
    </div>
  );
}
