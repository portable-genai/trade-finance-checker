/** @type {import('next').NextConfig} */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { assertHydratableCsp, frameAncestors } from "./lib/csp.mjs";

// Two refusals, both evaluated by `next build` AND `next start`, so a misconfigured console never
// comes up rather than surprising somebody on a later request.
//
// 1. The framing allowlist must not be present-but-empty. Resolving it here for the side effect
//    is the whole point: `lib/csp.mjs` throws, and this is where that throw becomes a boot
//    refusal. (Three states, not two: see the module for why an emptied allowlist is not consent
//    to the default.)
// 2. The route must be dynamically rendered. The CSP mints a per-request nonce, and a statically
//    prerendered page was built before the nonce existed, so nothing carries it and every script
//    is blocked. That combination blocks strictly MORE than the unfixed policy did, and no check
//    short of executing the served page can see it, so it is refused at build time.
frameAncestors(process.env);
assertHydratableCsp(readFileSync(new URL("./app/layout.tsx", import.meta.url), "utf8"));

// basePath/assetPrefix from NEXT_PUBLIC_BASE_PATH so the UI can mount under a reverse-proxy
// sub-path (e.g. portal.client.com/trade-finance/*) for same-origin embedding. Blank keeps
// the standalone build unchanged.
const basePath = process.env.NEXT_PUBLIC_BASE_PATH || "";

const nextConfig = {
  reactStrictMode: true,
  // `next dev` writes AGENTS.md and CLAUDE.md into this directory unless this is false; the
  // writer is node_modules/next/dist/server/lib/generate-agent-files.js. This repo's working
  // agreement is the AGENTS.md at its root and there is no tool-specific alias of it, so a
  // second one here is a second agreement to keep in step and CLAUDE.md is precisely the alias
  // the convention forbids. The generated prose also carries an em-dash, which the catalog's
  // house style forbids in shipped markdown. tests/unit/test_ui_agent_documents.py fails the
  // gate if this line goes away or if either file turns up on disk anyway.
  agentRules: false,
  // The canonical fictional presentation belongs to the backend/eval contract one level
  // above this Next.js project. Include the repository in Turbopack's filesystem boundary
  // so the client can import that single source of truth rather than duplicate demo data.
  turbopack: { root: fileURLToPath(new URL("..", import.meta.url)) },
  ...(basePath ? { basePath, assetPrefix: basePath } : {}),
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          // ONLY the statically expressible headers live here. The Content-Security-Policy and
          // X-Frame-Options are emitted by `proxy.ts`, from `lib/csp.mjs`, and deliberately NOT
          // here as well: a CSP set in two layers is two policies the browser intersects, the
          // stricter wins per directive, and the nonce this console needs would be intersected
          // away by whatever the other copy said about `script-src`.
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "no-referrer" },
        ],
      },
    ];
  },
};

export default nextConfig;
