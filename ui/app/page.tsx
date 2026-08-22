"use client";

// B4 demo console. Paste a presentation (LC + documents) as JSON and POST it to /v1/check,
// then render the DiscrepancyReport with cited findings. Decision support only.

import { useEffect, useState } from "react";

import demoPresentation from "../../eval/samples/presentation.json";
import { ReportView } from "../components/ReportView";
import { Panel } from "../components/ui";
import {
  PRESENTATION_TEMPLATE_URL,
  check,
  health,
  listPersonas,
  registerLc,
  setDevPersona,
} from "../lib/api";
import type { CheckRequest, DiscrepancyReport, Persona } from "../lib/types";

const IS_EMBEDDED = process.env.NEXT_PUBLIC_EMBED === "1";

// This is the canonical fictional presentation used by the local CLI and evaluation.
// Import it rather than maintaining a second copy: the UI demo cannot drift to an LC
// number that the fail-closed local entitlement registry does not authorize.
const SAMPLE = demoPresentation as unknown as CheckRequest;

export default function Home() {
  const [text, setText] = useState(JSON.stringify(SAMPLE, null, 2));
  const [report, setReport] = useState<DiscrepancyReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [selectedPersona, setSelectedPersona] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const status = await health();
        if (status.profile !== "local") return;
        const list = await listPersonas();
        if (cancelled || list.length === 0) return;
        setPersonas(list);
        setSelectedPersona(list[0].id);
        setDevPersona(list[0].id);
      } catch {
        // Persona picker is a dev-only convenience; ignore lookup failures.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  function onPersonaChange(id: string) {
    setSelectedPersona(id);
    setDevPersona(id);
  }

  async function runCheck() {
    setError(null);
    setLoading(true);
    try {
      const request = JSON.parse(text) as CheckRequest;
      // An audience-entered LC has no owner yet: claim it for the caller's verified
      // tenant first, so the fail-closed authorization gate can pass. Idempotent for
      // already-owned LCs in the same tenant; another tenant's LC still 409s/denies.
      if (request.lc?.lc_number) {
        await registerLc(request.lc.lc_number);
      }
      const result = await check(request);
      setReport(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setReport(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      {!IS_EMBEDDED && personas.length > 0 ? (
        <Panel title="Demo identity">
          <label className="text-sm">
            <span className="text-ink-500">Persona</span>
            <select
              className="mt-1 w-full rounded border border-ink-200 px-2 py-1.5 text-sm sm:w-96"
              value={selectedPersona}
              onChange={(e) => onPersonaChange(e.target.value)}
            >
              {personas.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.subject} · {p.tenant}
                </option>
              ))}
            </select>
          </label>
          <p className="mt-2 text-xs text-ink-500">
            Local profile only. The backend derives the audit actor from the verified
            identity, so this selects who the request runs as (the X-Dev-Persona header).
          </p>
        </Panel>
      ) : null}

      <Panel title="Presentation (LC + documents)">
        <textarea
          className="h-72 w-full rounded-lg border border-ink-200 bg-ink-50 p-3 font-mono text-xs text-ink-800"
          value={text}
          onChange={(e) => setText(e.target.value)}
          spellCheck={false}
        />
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <button
            onClick={runCheck}
            disabled={loading}
            className="rounded-lg bg-regblue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-regblue-700 disabled:opacity-50"
          >
            {loading ? "Checking..." : "Check presentation"}
          </button>
          <a
            href={PRESENTATION_TEMPLATE_URL}
            download
            className="text-xs font-medium text-regblue-600 underline decoration-dotted"
          >
            Download presentation template
          </a>
          {error ? <span className="break-words text-sm text-red-700">{error}</span> : null}
        </div>
        <p className="mt-2 text-xs text-ink-400">
          Paste your own LC and documents (or start from the template); the LC is claimed
          for your tenant on first check, then examined deterministically against UCP600.
        </p>
      </Panel>

      {report ? <ReportView report={report} /> : null}
    </div>
  );
}
