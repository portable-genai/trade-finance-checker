// Next 16's request interceptor (the file `middleware.ts` was renamed to on this major).
//
// It exists for one reason: a script nonce is a PER-REQUEST value, and the static `headers()`
// table in `next.config.mjs` cannot express one. Every response gets a fresh nonce, and the policy
// that names it is built by the single module in `lib/csp.mjs`.
//
// Both header sets below are required, and they are not redundant:
//
//   * the REQUEST header is where Next reads the nonce it stamps onto every `<script>` tag it
//     emits. Setting only the response header would advertise a nonce no tag carries, which
//     blocks strictly more than no nonce at all because `'strict-dynamic'` disables the `'self'`
//     fallback.
//   * the RESPONSE header is what the browser actually enforces. Setting only the request header
//     proves nothing to anybody.
//
// The request header name must be exactly `Content-Security-Policy`; that is the name Next looks
// for. The companion requirement lives in `app/layout.tsx`: the route must be dynamically
// rendered, or there is no per-request pass in which to stamp anything.

import { type NextRequest, NextResponse } from "next/server";

import { contentSecurityPolicy, frameAncestors, frameOptions, generateNonce } from "./lib/csp.mjs";

export function proxy(request: NextRequest) {
  const nonce = generateNonce();
  const csp = contentSecurityPolicy(process.env, nonce);

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("Content-Security-Policy", csp);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", csp);

  // Only for the two framing policies X-Frame-Options can actually express; a named allowlist
  // gets none rather than a SAMEORIGIN that would contradict the CSP in an older agent.
  const legacy = frameOptions(frameAncestors(process.env));
  if (legacy) response.headers.set("X-Frame-Options", legacy);

  return response;
}

export const config = { matcher: "/:path*" };
