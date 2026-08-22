import { ConfiguredEmptyError, readEnvSetting } from "./env-setting.mjs";
// Thin client for the B4 FastAPI backend. Base URL from NEXT_PUBLIC_API_BASE (default
// http://localhost:8094, the B4 service port).

import type { CheckRequest, DiscrepancyReport, Health, Persona } from "./types";

// The API base is resolved in THREE states, not two.
//
// Reading `process.env.NEXT_PUBLIC_API_BASE?.replace(...) || "<loopback default>"`
// which hands a variable an operator DELIBERATELY EMPTIED the loopback default. That is a
// widening: the console then talks to a local API instead of the configured one, and
// `connect-src` is built from the same value, so the emptied deployment is byte-identical to one
// that never configured the variable. Next inlines NEXT_PUBLIC_* AT BUILD TIME, so the wrong
// value is frozen into the bundle and cannot be corrected at start-up.
const DEFAULT_API_BASE = "http://localhost:8094";
const API_BASE_SETTING = readEnvSetting(process.env, "NEXT_PUBLIC_API_BASE");
if (API_BASE_SETTING.isConfiguredEmpty) {
  throw new ConfiguredEmptyError(
    "NEXT_PUBLIC_API_BASE is set to an empty value. An emptied variable names nothing, " +
      "so it cannot inherit the unset default (" + DEFAULT_API_BASE + "), which points this " +
      "console at a loopback API and widens connect-src to match. Unset it to take that " +
      "default deliberately, or give it the API origin this deployment should call.",
  );
}
const API_BASE = (API_BASE_SETTING.hasValue ? API_BASE_SETTING.value : DEFAULT_API_BASE).replace(
  /\/+$/,
  "",
);

// Dev-only identity selection. In LOCAL mode the backend resolves identity from the
// X-Dev-Persona header; in secure profiles this is ignored (identity comes from an IAP
// assertion injected by the platform). There is no client-supplied actor: the server
// derives the audit actor from the verified principal.
let devPersona = "";

export function setDevPersona(id: string): void {
  devPersona = id;
}

export function getDevPersona(): string {
  return devPersona;
}

function requestHeaders(): Record<string, string> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (devPersona) headers["X-Dev-Persona"] = devPersona;
  return headers;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: requestHeaders(),
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${path} returned ${res.status}: ${text.slice(0, 300)}`);
  }
  return (await res.json()) as T;
}

export async function check(request: CheckRequest): Promise<DiscrepancyReport> {
  return postJson<DiscrepancyReport>("/v1/check", request);
}

export interface LcRegistration {
  lc_number: string;
  tenant: string;
  already_registered: boolean;
}

/** Claim an LC for the caller's verified tenant so an audience-entered LC authorizes. */
export async function registerLc(lcNumber: string): Promise<LcRegistration> {
  return postJson<LcRegistration>("/v1/lcs", { lc_number: lcNumber });
}

/** Where the presentation (LC + documents) JSON template can be downloaded. */
export const PRESENTATION_TEMPLATE_URL = `${API_BASE}/v1/presentations/template`;

export async function health(): Promise<Health> {
  const res = await fetch(`${API_BASE}/healthz`, { headers: requestHeaders() });
  if (!res.ok) throw new Error(`/healthz returned ${res.status}`);
  return (await res.json()) as Health;
}

export async function listPersonas(): Promise<Persona[]> {
  const res = await fetch(`${API_BASE}/v1/personas`, { headers: requestHeaders() });
  if (!res.ok) throw new Error(`/v1/personas returned ${res.status}`);
  return (await res.json()) as Persona[];
}

export { API_BASE };
