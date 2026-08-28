// Unit cover for `lib/csp.mjs`: everything about the policy that a STRING can decide.
//
// These are NOT sufficient, and saying so is the point. The defect that made this module
// necessary passed every string assertion anybody wrote: the header was correct, the build
// succeeded, the page rendered, and React never attached because the markup and the header
// disagreed about the nonce. A string cannot see that. Only `scripts/assert-hydratable.mjs`,
// which starts the BUILT server and reads the served document, can, and it is the last step of
// the ui gate for that reason. What follows covers the half that is decidable here: which
// directives exist, that none of them is ever empty, and the three-state framing rule.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  ConfiguredEmptyError,
  DEFAULT_API_BASE,
  WildcardOriginError,
  contentSecurityPolicy,
  frameAncestors,
  frameOptions,
  generateNonce,
  UnhydratableCspError,
  assertHydratableCsp,
} from "../lib/csp.mjs";

/** Parse a policy string into {directive: value}. */
function directives(csp) {
  return Object.fromEntries(
    csp
      .split(";")
      .map((part) => part.trim())
      .filter(Boolean)
      .map((part) => {
        const [name, ...value] = part.split(/\s+/);
        return [name, value.join(" ")];
      }),
  );
}

const REQUIRED = [
  "default-src",
  "base-uri",
  "form-action",
  "object-src",
  "script-src",
  "style-src",
  "img-src",
  "font-src",
  "connect-src",
  "frame-ancestors",
];

test("the policy carries every directive that makes it default-deny", () => {
  const parsed = directives(contentSecurityPolicy({}, "n0nce"));
  for (const name of REQUIRED) {
    assert.ok(name in parsed, `missing directive ${name}`);
  }
  assert.equal(parsed["default-src"], "'self'");
  assert.equal(parsed["object-src"], "'none'");
  assert.equal(parsed["base-uri"], "'self'");
});

test("no directive is ever empty, in any framing state", () => {
  // An empty directive is a CSP parse error: the browser discards it, which silently removes
  // the restriction it looked like it was applying.
  for (const env of [{}, { NEXT_PUBLIC_FRAME_ANCESTORS: "'none'" }]) {
    for (const [name, value] of Object.entries(directives(contentSecurityPolicy(env, "n0nce")))) {
      assert.notEqual(value, "", `directive ${name} rendered empty for ${JSON.stringify(env)}`);
    }
  }
});

test("script-src takes the nonce and strict-dynamic ONLY when a nonce is supplied", () => {
  assert.equal(
    directives(contentSecurityPolicy({}, "abc123"))["script-src"],
    "'self' 'nonce-abc123' 'strict-dynamic'",
  );
  // No nonce means no document to hydrate, so no inline allowance either.
  assert.equal(directives(contentSecurityPolicy({}))["script-src"], "'self'");
});

test("frame-ancestors is three-state, mirroring the backend's own resolution", () => {
  assert.equal(frameAncestors({}), "'self'");
  assert.equal(frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: "'none'" }), "'none'");
  assert.equal(
    frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: "https://portal.client.example" }),
    "https://portal.client.example",
  );
});

test("a set-but-empty allowlist REFUSES rather than inheriting the default", () => {
  // Two states would make a variable somebody deliberately emptied indistinguishable from one
  // that went missing, and would read that absence as consent to same-origin framing.
  for (const blank of ["", "   ", "\t", "\n "]) {
    assert.throws(
      () => frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: blank }),
      ConfiguredEmptyError,
      `blank ${JSON.stringify(blank)} did not refuse`,
    );
  }
});

test("X-Frame-Options is emitted only for the two policies it can express", () => {
  assert.equal(frameOptions("'self'"), "SAMEORIGIN");
  assert.equal(frameOptions("'none'"), "DENY");
  // A named allowlist has no X-Frame-Options spelling; sending SAMEORIGIN would contradict the
  // CSP in an older agent.
  assert.equal(frameOptions("https://portal.client.example"), "");
});

test("connect-src widens to the API ORIGIN, never the full URL", () => {
  const parsed = directives(
    contentSecurityPolicy({ NEXT_PUBLIC_API_BASE: "https://api.client.example/v1/check?x=1" }),
  );
  assert.equal(parsed["connect-src"], "'self' https://api.client.example");
});

test("connect-src default agrees with the client's own default base URL", () => {
  // Drift here is invisible until the demo's first fetch is blocked by the policy meant to
  // protect it, so the two literals are compared rather than trusted.
  const api = readFileSync(new URL("../lib/api.ts", import.meta.url), "utf8");
  assert.ok(
    api.includes(DEFAULT_API_BASE),
    `lib/api.ts no longer mentions ${DEFAULT_API_BASE}; update DEFAULT_API_BASE in lib/csp.mjs`,
  );
  assert.equal(directives(contentSecurityPolicy({}))["connect-src"], `'self' ${DEFAULT_API_BASE}`);
});

test("a rooted API base stays same-origin rather than being refused", () => {
  // A host portal mounting this console under its own route sets exactly this. Same-origin is
  // already covered by 'self', so it widens nothing, and refusing it answered 500 on a working
  // deployment. What must never happen is the value being dropped while it names a real origin,
  // which is the case below.
  const parsed = directives(contentSecurityPolicy({ NEXT_PUBLIC_API_BASE: "/apps/doc4/api" }));
  assert.equal(parsed["connect-src"], "'self'");
});

test("a protocol-relative API base is refused rather than read as same-origin", () => {
  assert.throws(
    () => contentSecurityPolicy({ NEXT_PUBLIC_API_BASE: "//api.example/v1" }),
    /must name its scheme/,
  );
});

test("an API base that is neither absolute nor rooted is refused", () => {
  assert.throws(
    () => contentSecurityPolicy({ NEXT_PUBLIC_API_BASE: "api.example/v1" }),
    /NEXT_PUBLIC_API_BASE/,
  );
});

test("nonces are unique and base64", () => {
  const seen = new Set();
  for (let i = 0; i < 50; i += 1) {
    const nonce = generateNonce();
    assert.match(nonce, /^[A-Za-z0-9+/]+={0,2}$/);
    seen.add(nonce);
  }
  assert.equal(seen.size, 50, "a reused nonce is a predictable nonce");
});

test("the build refuses a layout that is not force-dynamic", () => {
  assert.throws(() => assertHydratableCsp("export const metadata = {};"), UnhydratableCspError);
  assert.doesNotThrow(() =>
    assertHydratableCsp('export const dynamic = "force-dynamic";\nexport default function L() {}'),
  );
});

test("the SHIPPED layout is force-dynamic", () => {
  // The assertion above proves the rule; this one proves the artefact still satisfies it, so a
  // layout rewrite cannot quietly reintroduce the statically prerendered trap.
  assert.doesNotThrow(() =>
    assertHydratableCsp(readFileSync(new URL("../app/layout.tsx", import.meta.url), "utf8")),
  );
});

// The FOURTH framing state: a value that names EVERYBODY. It is not the emptied state, because it
// resolves to a directive a browser will happily honour, and the header this module emits is the
// one a browser enforces for the DOCUMENT. A console that accepted a wildcard while the backend
// refused it would be the permissive half of the posture, and the permissive half governs what a
// page can actually be framed by. `next.config.mjs` calls `frameAncestors` at module scope, so
// each refusal below is a build and boot refusal rather than a surprise on a later request.

test("a wildcard framing allowlist refuses, bare and partial alike", () => {
  // A partial wildcard is no safer than a bare one: `https://*.example` trusts every subdomain,
  // including one an attacker obtains by takeover and one that serves user content. Refusing any
  // asterisk turns away nothing a deployment could correctly hold, because a real origin never
  // contains the character.
  for (const value of ["*", "'*'", "*.*", "https://*.example", "*.example", "https://*"]) {
    assert.throws(
      () => frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: value }),
      WildcardOriginError,
      `frameAncestors accepted ${JSON.stringify(value)}`,
    );
    // A mixed list is the dangerous shape: one valid origin makes the value look configured,
    // while the entry beside it is the one that actually widens the policy.
    const mixed = `https://portal.bank.example ${value}`;
    assert.throws(
      () => frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: mixed }),
      WildcardOriginError,
      `frameAncestors accepted ${JSON.stringify(mixed)}`,
    );
    assert.throws(
      () => contentSecurityPolicy({ NEXT_PUBLIC_FRAME_ANCESTORS: value }, "n"),
      WildcardOriginError,
      `contentSecurityPolicy emitted ${JSON.stringify(value)}`,
    );
  }
});

test("the literal null is refused, though it carries no asterisk", () => {
  // The refusal tested `token.includes("*")`, which catches every wildcard that is SPELLED as one
  // and cannot see this one. A sandboxed iframe presents a null origin, so `frame-ancestors null`
  // admits framing from a document whose own origin the browser has already discarded, which is
  // exactly the framing the directive exists to refuse. A wildcard by behaviour, not by spelling.
  for (const value of ["null", "https://portal.bank.example null", "null https://a.example"]) {
    assert.throws(
      () => frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: value }),
      WildcardOriginError,
      `frameAncestors accepted ${JSON.stringify(value)}`,
    );
    assert.throws(
      () => contentSecurityPolicy({ NEXT_PUBLIC_FRAME_ANCESTORS: value }, "n"),
      WildcardOriginError,
      `contentSecurityPolicy emitted ${JSON.stringify(value)}`,
    );
  }
});

test("the wildcard refusal leaves every legitimate value resolving", () => {
  // A refusal that also refuses valid input is an outage rather than a control. Matching is
  // exact-token, so an origin whose hostname merely contains one of the words is untouched, and
  // the unset, emptied and named states keep the answers they already gave.
  assert.equal(frameAncestors({}), "'self'");
  assert.throws(() => frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: "" }), ConfiguredEmptyError);
  assert.equal(frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: "'none'" }), "'none'");
  assert.equal(
    frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: "https://nullify.example https://a.example" }),
    "https://nullify.example https://a.example",
  );
});
