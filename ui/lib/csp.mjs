// The console's Content-Security-Policy, in one module so it is built once and read everywhere.
//
// Living inline in `next.config.mjs`, emitted through the static `headers()` table, would say
// exactly one thing: `frame-ancestors <allowlist>`. That is an anti-clickjacking rule, not
// a policy. With no `default-src`, no `script-src`, no `object-src` and no `base-uri`, the console
// was default-ALLOW for every fetch a page can make, and a single injected tag could have loaded
// anything from anywhere.
//
// The obvious repair, adding `script-src 'self'`, is worse than it looks: Next serves its
// hydration bootstrap as an INLINE script carrying the Flight payload, so `'self'` blocks it,
// `__next_f` never fills, React never attaches, and the console renders its controls as dead
// markup while the headers, the type-check, the build and every test stay green. So `script-src`
// takes a PER-REQUEST nonce, minted in `proxy.ts`, plus `'strict-dynamic'` so the nonced bootstrap
// may load its own chunks and nothing else may run.
//
// `next.config.mjs` no longer emits a `Content-Security-Policy` at all. Two layers both setting it
// gives the browser two policies to intersect, the stricter one wins per directive, and that is
// precisely how the defect this module exists to remove comes back.
//
// The `frame-ancestors` semantics here MIRROR THE BACKEND, `trade_finance_checker.api.app`, which
// resolves `TRADE_FINANCE_FRAME_ANCESTORS` in three states and REFUSES a set-but-empty allowlist.
// The two halves of one embedding posture must not disagree, so an emptied
// `NEXT_PUBLIC_FRAME_ANCESTORS` refuses here too rather than quietly inheriting the `'self'`
// default an operator had just tried to replace.

/**
 * Where the console's API lives when nobody configured one.
 *
 * This mirrors the fallback in `lib/api.ts`, and `connect-src` has to carry it or the offline
 * demo's very first fetch is blocked by the policy that was supposed to protect it. The two are
 * kept in step by `tests/csp.test.mjs`, which reads `lib/api.ts` and asserts the literal matches.
 */
export const DEFAULT_API_BASE = "http://localhost:8094";

/** Raised when an allowlist is present but names nothing, which is an intent that selected zero. */
export class ConfiguredEmptyError extends Error {}

/** Raised when an origin policy names everybody. Mirrors `_refuse_wildcard` in the backend. */
export class WildcardOriginError extends Error {}

/**
 * Exact tokens that may never be a framing ancestor.
 *
 * The set exists for `null`, which the asterisk rule below cannot see: it carries no asterisk and
 * is a wildcard by BEHAVIOUR rather than by spelling, because a sandboxed iframe presents a null
 * origin, so `frame-ancestors null` admits framing from a document whose own origin the browser
 * has already discarded. The other three are already refused by the asterisk rule and are named
 * here anyway, so the refused vocabulary is one list a reader can check rather than something
 * they have to derive from two rules at once.
 */
const WILDCARD_TOKENS = new Set(["*", "'*'", "null", "*.*"]);

/**
 * True when a token may not be a framing ancestor: one of the named tokens, or anything carrying
 * an asterisk. Matching is exact, so `https://nullify.example` stays a perfectly good origin.
 *
 * @param {string} token
 * @returns {boolean}
 */
function isWildcard(token) {
  return WILDCARD_TOKENS.has(token) || token.includes("*");
}

/**
 * Origin of the API base the browser will actually call, so `connect-src` can name it.
 *
 * A rooted path is the SAME-ORIGIN deployment, which is what a host portal mounting this console
 * under its own route sets. There is no second origin to name there, and `'self'` already permits
 * it, so "" is the correct answer rather than an error: refusing it made the console answer 500
 * behind the portal, which is a working configuration reported as a broken one.
 *
 * A protocol-relative value is still refused. It names a DIFFERENT host while looking rooted, so
 * treating it as same-origin would drop a genuinely cross-origin API out of `connect-src`, which
 * is the silent-drop this function exists to prevent.
 *
 * @param {Record<string, string | undefined>} env
 * @returns {string} an origin to add to `connect-src`, or "" when same-origin
 */
function apiOrigin(env) {
  const raw = (env.NEXT_PUBLIC_API_BASE || DEFAULT_API_BASE).trim();
  if (!raw) return "";
  if (raw.startsWith("//")) {
    throw new Error(`NEXT_PUBLIC_API_BASE must name its scheme, got: ${raw}`);
  }
  if (raw.startsWith("/")) return "";
  try {
    return new URL(raw).origin;
  } catch {
    throw new Error(
      `NEXT_PUBLIC_API_BASE must be an absolute URL or a rooted same-origin path, got: ${raw}`,
    );
  }
}

/**
 * Who may frame this console, resolved in THREE states, never two.
 *
 * Unset means `'self'`: standalone, framed by nothing but its own origin. Present but blank
 * REFUSES: an operator who empties the allowlist has expressed an intent that names no parent, and
 * inheriting the shipped default instead reads that absence as consent, while making a deployment
 * that lost the variable indistinguishable from one that locked itself down on purpose. Present
 * and named is used as given. This is the backend's rule, character for character.
 *
 * @param {Record<string, string | undefined>} env
 * @returns {string} a non-empty directive value; an empty one is a CSP parse error browsers
 *   discard, which silently removes the restriction it looked like it was applying.
 */
export function frameAncestors(env) {
  const raw = env.NEXT_PUBLIC_FRAME_ANCESTORS;
  if (raw === undefined || raw === null) return "'self'";
  const named = String(raw).trim().split(/\s+/).filter(Boolean);
  const wildcards = named.filter(isWildcard);
  if (wildcards.length) {
    throw new WildcardOriginError(
      `NEXT_PUBLIC_FRAME_ANCESTORS origin policy must never contain a wildcard, got ` +
        `${JSON.stringify(wildcards)}. A wildcard lets any page frame the console and drive ` +
        "it as the signed-in user, a partial one (https://*.example) trusts every " +
        "subdomain including one an attacker took, and `null` is the origin a sandboxed iframe " +
        "presents, which is the same permission spelled without an asterisk. Name each " +
        "permitted origin in full.",
    );
  }
  if (named.length === 0) {
    throw new ConfiguredEmptyError(
      "NEXT_PUBLIC_FRAME_ANCESTORS is set but empty. An empty allowlist names no parent " +
        "origin, and inheriting the default would silently permit same-origin framing nobody " +
        "asked for. Unset NEXT_PUBLIC_FRAME_ANCESTORS to keep the 'self' default, name the " +
        "parent origins that may frame the checker UI, or set it to 'none' to refuse framing " +
        "outright.",
    );
  }
  return named.join(" ");
}

/**
 * The pre-CSP `X-Frame-Options` spelling of a framing policy, or `""` where none exists.
 *
 * A NAMED allowlist has no `X-Frame-Options` equivalent, so none is sent rather than a
 * `SAMEORIGIN` that would contradict the CSP in an older agent. Mirrors the backend's
 * `_LEGACY_FRAME_OPTIONS`.
 *
 * @param {string} ancestors the resolved `frame-ancestors` value
 */
export function frameOptions(ancestors) {
  if (ancestors === "'self'") return "SAMEORIGIN";
  if (ancestors === "'none'") return "DENY";
  return "";
}

/**
 * The full default-deny policy.
 *
 * `style-src` carries `'unsafe-inline'` because the Next runtime injects critical CSS and there is
 * no nonce path for it. `script-src` does NOT: it takes the per-request nonce plus
 * `'strict-dynamic'`. Passing no nonce yields the strict `'self'` form, which is correct for any
 * response that is not a Next-rendered document and wrong for one that is.
 *
 * @param {Record<string, string | undefined>} env
 * @param {string} [nonce] per-request nonce from {@link generateNonce}
 */
export function contentSecurityPolicy(env, nonce) {
  // Dev only: Turbopack's HMR client evaluates the module updates it receives and opens a
  // websocket back to the dev server. Without both relaxations `npm run dev` serves a page that
  // renders completely and never hydrates, which is the failure
  // `org-metadata/docs/demos/demo-inventory.md` records. Neither is ever emitted by a production
  // build: `next build` / `next start` set NODE_ENV=production, so the policy below comes out
  // byte-identical to the one this console shipped before the branch existed.
  const isDev = env.NODE_ENV !== "production";
  const connectSrc = ["'self'", apiOrigin(env), isDev ? "ws: wss:" : ""]
    .filter(Boolean)
    .join(" ");
  const scriptSrc = [
    "script-src 'self'",
    nonce ? `'nonce-${nonce}' 'strict-dynamic'` : "",
    isDev ? "'unsafe-eval'" : "",
  ]
    .filter(Boolean)
    .join(" ");
  return [
    "default-src 'self'",
    "base-uri 'self'",
    "form-action 'self'",
    "object-src 'none'",
    scriptSrc,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "font-src 'self' data:",
    `connect-src ${connectSrc}`,
    `frame-ancestors ${frameAncestors(env)}`,
  ].join("; ");
}

/** A fresh per-request nonce. Base64 of 16 random bytes from the Web Crypto global. */
export function generateNonce() {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return btoa(String.fromCharCode(...bytes));
}

/** Raised when the nonce policy and the rendering mode disagree, which serves un-hydratable HTML. */
export class UnhydratableCspError extends Error {}

/**
 * Refuse a build whose CSP mints a nonce the rendered HTML can never carry.
 *
 * Next can only stamp a per-request nonce onto the scripts of a DYNAMICALLY rendered route. A
 * statically prerendered page was built before the nonce existed, so it emits bare script tags
 * while the header advertises a nonce, and because `'strict-dynamic'` switches off the `'self'`
 * fallback, that combination blocks strictly MORE than the unfixed policy did. The failure is
 * invisible to every check that does not execute the page, so it is refused at build time.
 *
 * No I/O happens here: the caller passes the source as a string, which keeps this module
 * importable from the edge-runtime proxy.
 *
 * @param {string} layoutSource contents of `app/layout.tsx`
 */
export function assertHydratableCsp(layoutSource) {
  if (!/export\s+const\s+dynamic\s*=\s*["']force-dynamic["']/.test(layoutSource)) {
    throw new UnhydratableCspError(
      'app/layout.tsx must set `export const dynamic = "force-dynamic"`. The CSP mints a ' +
        "per-request nonce, and Next can only stamp it onto script tags for a dynamically " +
        "rendered route. Statically prerendered HTML was built before the nonce existed, so " +
        "every script is blocked and the page never hydrates.",
    );
  }
}
