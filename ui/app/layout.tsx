import type { Metadata } from "next";
import type { ReactNode } from "react";

import { ProvenanceBanner } from "../components/ProvenanceBanner";
import "./globals.css";

// REQUIRED by the nonce CSP, and not a performance preference. `proxy.ts` mints a per-request
// script nonce, and Next can only stamp a per-request value onto the script tags of a DYNAMICALLY
// rendered route. Prerendered HTML is built before the nonce exists, so nothing carries it and
// `'strict-dynamic'` has already switched off the `'self'` fallback: every script is blocked and
// the page never hydrates. `next.config.mjs` refuses to build if this line goes missing.
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Trade-Finance Document Checker",
  description:
    "Detect discrepancies in a documentary-credit presentation against the LC terms and UCP600 (Transaction Banking).",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  // EMBED mode: the host page owns the chrome, so drop our header/branding and render the
  // children bare so the checker drops cleanly into an existing app (same-origin iframe or
  // micro-frontend). Standalone keeps the full header.
  const embed = process.env.NEXT_PUBLIC_EMBED === "1";
  // The banner renders in BOTH modes, and embedded is the mode that needs it most: a panel
  // inside somebody else's portal is where a viewer has least context about where the answer
  // came from. It is mounted in the LAYOUT rather than in a page because "at the top of every
  // page" is a property of the console, and a page that forgot it would be the one page a
  // screenshot came from. This checker is the one tree that KEPT its local model, so the
  // banner is the only place a viewer learns that its answer came from Gemma, not Gemini.
  return (
    <html lang="en">
      <body className="min-h-screen">
        <ProvenanceBanner />
        {embed ? (
          <main className="p-4">{children}</main>
        ) : (
          <>
            <header className="border-b border-ink-200 bg-white">
              <div className="mx-auto max-w-5xl px-6 py-4">
                <h1 className="text-lg font-semibold text-ink-900">
                  Trade-Finance Document Checker
                </h1>
                <p className="text-sm text-ink-500">
                  Documentary-credit discrepancy checks · region asia-southeast1 · synthetic
                  data is fictional
                </p>
              </div>
            </header>
            <main className="mx-auto max-w-5xl px-6 py-6">{children}</main>
          </>
        )}
      </body>
    </html>
  );
}
