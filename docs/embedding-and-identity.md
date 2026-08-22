# Embedding and identity: client integration guide (B4 trade-finance-checker)

This guide shows how an enterprise client runs the B4 Trade-Finance Document Checker and, when
desired, embeds its UI inside an existing web application with secure single sign-on (SSO) so
users never see a second login. It is grounded in what the codebase implements today, and it
clearly separates that from further hardening layers that are documented but not yet built.

Two reading conventions are used throughout:

- **Implemented today.** Backed by code on `main`: the FastAPI backend (`src/trade_finance_checker/api/`),
  the `IdentityPort` and its per-profile adapters (`ports/identity.py`,
  `adapters/{local,gcp,onprem}/identity.py`), the embedding-surface controls in `api/app.py`
  (per-tenant CORS + CSP `frame-ancestors`), the UI build knobs (`ui/next.config.mjs`,
  `ui/app/layout.tsx`), and the profile bindings in `config/settings.yaml`.
- **Further layers (not built here).** Capabilities the architecture is ready to receive; see
  the closing section. The reference implementation with the fuller build is
  `cdd-sow-research`.

For the deployment shapes below that use only implemented-today features, no application code
changes are required to integrate: the work is operational (choose a profile, set environment
variables, add a proxy route + iframe tag).

---

## 1. The identity contract

The checker **never trusts a client-asserted identity.** There is no `actor` field on any
request body (it was removed from `POST /v1/check` and `POST /v1/extract`). Instead:

- `api/security.py` `get_principal` builds a `RequestContext` from the (lower-cased) request
  headers and calls the active profile's `IdentityPort.resolve(ctx)`, which returns a verified
  `Principal(subject, principals, tenant, assurance, source)` or raises `IdentityError`.
- An `IdentityError` becomes an HTTP **401**. Every artifact route depends on
  `CurrentPrincipal`, so an unauthenticated caller cannot reach the domain service.
- The verified `Principal.actor` (the subject) is threaded into `TradeCheckService.check(...)`
  / `.extract(...)` as the **audit actor** written to the WORM trail (non-repudiation, MAS TRM
  / MAS 626 / CPS 234). `Principal.principals` and `Principal.tenant` are available for
  per-user / per-tenant authorization.

The identity decision is swappable by profile, exactly like every other port (P-02):

| Profile           | IdentityPort adapter          | How identity is established                                  |
| ----------------- | ----------------------------- | ------------------------------------------------------------ |
| `local`           | `LocalPersonaIdentityAdapter` | Seeded dev personas, no IdP; selected by `X-Dev-Persona`     |
| `gcp` / `platform`| `IapIdentityAdapter`          | Verifies the Cloud IAP `x-goog-iap-jwt-assertion` header     |
| `onprem`          | `OnPremIdentityAdapter`       | Fail-fast placeholder for the client's own IdP (OIDC/SAML)   |

---

## 2. Three deployment shapes

### Shape A: embedded, same-origin reverse-proxy (recommended for a host app)

The host serves the checker under its **own** origin at a sub-path (for example
`portal.client.com/trade-finance/*`) via a reverse proxy, and iframes it. Because the iframe is
first-party, there is no third-party-cookie problem and no CORS. The host's edge (IAP, Apigee,
or the client's own gateway) authenticates the user once; the checker verifies the injected
assertion server-side.

### Shape B: standalone behind IAP (no host app)

The checker is deployed on its own (Cloud Run behind an HTTPS load balancer + IAP) and users
visit it directly. IAP authenticates and injects the signed assertion; the `gcp` profile
verifies it. This is the plain "run it as its own product" shape.

### Shape C: local dev, no auth

`TRADE_FINANCE_PROFILE=local` runs the whole pipeline offline with seeded personas and no IdP,
so demos and tests need no cloud and no login. The UI shows a "Demo identity" persona picker.

---

## 3. Run locally (no auth)

```bash
make install                 # venv + pip install -e ".[dev]" (no GCP SDK)
make run-api                 # FastAPI on :8094, profile=local
make run-ui                  # Next.js UI on :3000
```

In `local` the UI calls `GET /v1/personas`, shows the persona picker, and sends the chosen id
in the `X-Dev-Persona` header. The backend resolves that to a seeded `Principal`; that persona's
subject is the audit actor. Seeded personas (all fictional):

| id             | subject                        | tenant       | entitlements                                             |
| -------------- | ------------------------------ | ------------ | -------------------------------------------------------- |
| `analyst`      | `demo.analyst@bank.example`    | `demo-bank`  | `group:trade-analyst`, `group:trade-finance`             |
| `approver`     | `demo.approver@bank.example`   | `demo-bank`  | + `group:trade-approver`                                 |
| `auditor`      | `demo.auditor@bank.example`    | `demo-bank`  | `group:trade-audit`                                      |
| `other-tenant` | `user@other-tenant.example`    | `other-bank` | `group:trade-analyst` (proves per-tenant isolation)      |

An unknown `X-Dev-Persona` is a 401 (an unverified identity is never accepted, even in local).

---

## 4. Secure deploy on GCP with IAP

1. Deploy the app (`TRADE_FINANCE_PROFILE=gcp`) on Cloud Run behind an external HTTPS load
   balancer, and enable **Identity-Aware Proxy** on the backend service.
2. IAP authenticates the user against the configured IdP. For a client's corporate IdP, use
   **Workforce Identity Federation** so IAP trusts the client's OIDC/SAML IdP without a second
   login.
3. Set `TRADE_FINANCE_IAP_AUDIENCE` to the IAP-protected resource id (for an HTTPS LB + IAP:
   `/projects/<NUM>/global/backendServices/<ID>`). `IapIdentityAdapter` verifies the
   signature, audience, issuer, and expiry of the `x-goog-iap-jwt-assertion` header, derives
   `subject` from `email`/`sub` and `tenant` from the `hd` claim, and never logs the assertion.

Any verification failure raises `IdentityError` and is a 401. The assertion is verified on
**every** request (defense in depth: edge IAP, then this per-backend re-validation).

---

## 5. Embed via reverse-proxy (Shape A, worked example)

Build the UI with the sub-path and embed mode set:

```bash
# ui/.env.local (or build-time env)
NEXT_PUBLIC_BASE_PATH=/trade-finance
NEXT_PUBLIC_EMBED=1
NEXT_PUBLIC_API_BASE=/trade-finance/api
```

`ui/next.config.mjs` reads `NEXT_PUBLIC_BASE_PATH` and sets `basePath`/`assetPrefix`;
`ui/app/layout.tsx` drops the app header/chrome when `NEXT_PUBLIC_EMBED === "1"` so the host
owns the chrome.

nginx (same-origin: both UI and API under `portal.client.com`):

```nginx
location /trade-finance/api/ {
    proxy_pass http://trade-finance-backend:8094/;   # FastAPI
    proxy_set_header Host $host;
    # The client edge (IAP/gateway) has already authenticated; it injects the assertion
    # header the backend verifies. Do not let a client set it directly.
}
location /trade-finance/ {
    proxy_pass http://trade-finance-ui:3000/trade-finance/;   # Next.js
}
```

Host page iframe:

```html
<iframe
  src="https://portal.client.com/trade-finance/"
  title="Trade-Finance Document Checker"
  style="width:100%;height:900px;border:0"
></iframe>
```

Allow the host origin to frame the checker (CSP wins over `X-Frame-Options` for multi-origin):

```bash
TRADE_FINANCE_FRAME_ANCESTORS="'self' https://portal.client.com"
```

`api/app.py` emits `Content-Security-Policy: frame-ancestors <allowlist>` on every response,
and adds `X-Frame-Options` only for the two policies the legacy header can express: `'self'`
becomes `SAMEORIGIN` and `'none'` becomes `DENY`. A multi-origin allowlist has no
`X-Frame-Options` spelling, so none is sent rather than one that contradicts the CSP.

The variable is read in three states. Unset keeps the `'self'` default; a value is used as
given; **set but empty refuses at boot** (`ConfiguredEmptyError` from the module-level
resolver), so a deployment template that renders the variable to nothing fails loudly instead
of serving a framing policy nobody chose. To refuse framing outright, set it to `'none'`.

The UI mirrors this. `frame-ancestors` is honoured only on the response of the document the
browser actually frames, and that document is served by Next.js, not the API, so the console
emits the same policy from `NEXT_PUBLIC_FRAME_ANCESTORS` with the same three-state rule (an
empty value throws at config load, which `next build` and `next start` both evaluate). Set
both to the same origins.

### 5a. The console's own Content-Security-Policy

A console that ships `frame-ancestors` and nothing else has no policy worth the name. That is an anti-clickjacking
rule, not a policy: with no `default-src`, no `script-src`, no `object-src` and no `base-uri`,
every fetch the page could make was default-allow. It now serves a full default-deny policy
built in exactly one place, `ui/lib/csp.mjs`.

One place is the requirement, not a tidiness preference. A CSP emitted by two layers gives the
browser two policies to intersect, and the stricter one wins per directive, so a second copy
silently overrides the first. `ui/next.config.mjs` therefore emits no CSP at all; its
`headers()` table keeps only what is genuinely static (`X-Content-Type-Options: nosniff`,
`Referrer-Policy: no-referrer`).

There are two enforcement points and they do different jobs:

- **`ui/proxy.ts`** mints a fresh per-request nonce and sets the policy on BOTH the request
  headers (where Next reads the nonce it stamps onto every `<script>` tag) and the response
  headers (what the browser enforces). Either one alone is broken: request-only proves nothing
  to the browser, response-only advertises a nonce no tag carries.
- **`ui/next.config.mjs`** refuses at build and boot: once for a set-but-empty framing
  allowlist, once for a layout that is not `force-dynamic`.

That second refusal is the sharp edge. `script-src` carries `'nonce-...' 'strict-dynamic'`
because Next serves its hydration bootstrap as an inline script, and a bare `script-src 'self'`
blocks it: `__next_f` never fills, React never attaches and the console renders its controls as
dead markup while headers, types, build and tests all stay green. But Next can only stamp a
per-request nonce onto a DYNAMICALLY rendered route, so a nonce on a statically prerendered
page blocks strictly more than the unfixed policy did, `'strict-dynamic'` having switched off
the `'self'` fallback that was at least loading the chunk scripts. Hence
`export const dynamic = "force-dynamic"` in `ui/app/layout.tsx`, and hence
`ui/scripts/assert-hydratable.mjs`, which starts the BUILT server and asserts every script tag
in the served document carries the served nonce. A header assertion cannot see this: the header
is byte-identical in the working case and the broken one.

If (and only if) the UI is served from a **different** origin than the API, set an explicit
CORS allowlist (never `"*"`):

```bash
TRADE_FINANCE_CORS_ORIGINS="https://portal.client.com"
```

`allow_methods` is `GET, POST, OPTIONS`; `allow_headers` includes `Content-Type`,
`Authorization`, and `X-Dev-Persona`.

---

## 6. Config knobs

| Env var                        | Default                | Purpose                                                        |
| ------------------------------ | ---------------------- | -------------------------------------------------------------- |
| `TRADE_FINANCE_PROFILE`        | (unset: no choice)     | `local` \| `live` \| `gcp` \| `platform` \| `onprem`. Unset binds the SDK-free `local` adapters but refuses every relaxation: no seeded personas, no localhost CORS grant. Name one deliberately. |
| `TRADE_FINANCE_IAP_AUDIENCE`   | (empty)                | IAP-protected resource id; required to verify the assertion    |
| `TRADE_FINANCE_CORS_ORIGINS`   | dev origins            | Comma-separated cross-origin allowlist (never `"*"`)           |
| `TRADE_FINANCE_FRAME_ANCESTORS`| `'self'` when UNSET    | CSP `frame-ancestors`: which parents may iframe the UI. Set-but-empty refuses at boot; `'none'` refuses all framing |
| `NEXT_PUBLIC_FRAME_ANCESTORS`  | `'self'` when UNSET    | Same allowlist for the framed document itself (Next.js serves it). Build-time, same three-state rule |
| `NEXT_PUBLIC_API_BASE`         | `http://localhost:8094`| UI to backend base URL. Its ORIGIN is what the console's `connect-src` widens to, so a cross-origin API needs no separate CSP knob |
| `NEXT_PUBLIC_BASE_PATH`        | (empty)                | Mount the UI under a reverse-proxy sub-path                     |
| `NEXT_PUBLIC_EMBED`            | (empty)                | `1` drops app chrome so the host owns it                       |
| `X-Dev-Persona` (header)       | first persona          | `local` only: selects the seeded persona                       |

---

## 7. Client integration checklist

- [ ] Pick a deployment shape (A embedded, B standalone, C local dev).
- [ ] Choose the profile (`local` for demo/test; `gcp`/`platform` for secure).
- [ ] For secure: enable IAP and set `TRADE_FINANCE_IAP_AUDIENCE`; federate the client IdP via
      Workforce Identity Federation if a corporate login is required.
- [ ] For embedding: build the UI with `NEXT_PUBLIC_BASE_PATH` + `NEXT_PUBLIC_EMBED=1`, add the
      proxy routes, and add the iframe.
- [ ] Set `TRADE_FINANCE_FRAME_ANCESTORS` and `NEXT_PUBLIC_FRAME_ANCESTORS` to the host
      origin(s), or leave both UNSET (not empty) for the `'self'` default; set
      `TRADE_FINANCE_CORS_ORIGINS` only if truly cross-origin.
- [ ] Confirm the client cannot set the IAP assertion header directly (the edge must inject it).

## 8. Security checklist

- [ ] No `actor` is accepted from the client: the audit actor is the verified `Principal`.
- [ ] The IdentityPort is enforced on every artifact route (`CurrentPrincipal`), returning 401
      on any resolution failure.
- [ ] IAP assertions are verified (signature, audience, issuer, expiry) and never logged.
- [ ] CSP `frame-ancestors` and per-tenant CORS are set to the host origins, not `"*"`.
- [ ] Trade-party PII is redacted before any model, trace, or audit write (P-04), independent
      of identity.
- [ ] Region stays pinned to `asia-southeast1` with CMEK.

---

## 9. Further layers (not built in this repo)

These are the next hardening steps; document them, do not assume they exist here:

- **Per-hop OAuth2 token-exchange (OBO) + Workload Identity + mTLS** from this service to the
  Hrz platform services, so the user identity propagates end to end rather than stopping at the
  edge.
- **Cross-origin embedding** for hosts that cannot run a reverse proxy: a versioned front-end
  loader, a `postMessage` contract, auto-resize, and an `Authorization: Bearer` identity adapter
  that verifies a host-minted token against the host's JWKS (a pure adapter addition, since
  `get_principal` already reads arbitrary headers and CORS already permits `Authorization`).
- **A launch-in-new-tab OIDC session-login mode** for a standalone deployment with no edge IdP.
- **DPoP / step-up (acr/amr)** for high-value actions, and **KB tenant-partition + fail-closed
  ACL** on any governed retrieval.

The reference implementation carrying several of these is `cdd-sow-research`; mirror from
there when extending.
