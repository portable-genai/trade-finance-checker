# Security FAQ

For an application-security team reviewing this repo before adopting it as a base. Answers
reflect the current code. Cross-references: [`ARCHITECTURE.md`](../../ARCHITECTURE.md)
(security principles), [`COMPLIANCE.md`](../../COMPLIANCE.md) (P-01..P-12 / R1..R6, R8),
[`docs/embedding-and-identity.md`](../embedding-and-identity.md) (embedding + identity threat
model), and the audited evidence in [`docs/practices-audit.md`](../practices-audit.md).

### How is a request authenticated? Can a client spoof its identity?

No. Identity is resolved **server-side** from the transport context by an `IdentityPort`
adapter (`api/security.py::get_principal` returns a `CurrentPrincipal`), never from the
request body. The request schemas (`api/schemas.py` `CheckRequest` / `ExtractRequest`) carry
no `actor` field, and any client-asserted actor or ACL is discarded. The audit actor and the
entitlement principals both come from the verified `Principal`. Per profile: `local` = seeded
dev personas (no IdP, offline only); `gcp` / `platform` = the Cloud IAP-injected signed
assertion verified in `adapters/gcp/iap_identity.py`; `onprem` = a client-IdP placeholder.
This repo does **not** own a login flow (no OIDC/PKCE code, no `api/auth.py`): identity is
verified at the edge (IAP) and consumed here.

### How is object-level authorization (multi-tenant isolation) enforced?

`domain/entitlements.py` supplies a server-side owner registry (`AclPort` -> `ObjectOwner`)
and a fail-closed `authorize_object` gate: a Letter of Credit whose owner is unknown, or
whose tenant/roles the verified `Principal` does not hold, is denied **before** any redaction,
extraction or retrieval. The gate is enforced inside `TradeCheckService.check`, so the CLI and
agent paths inherit it, and it maps to HTTP 403 at the API. Proven in
`tests/unit/test_entitlements.py` and `test_api_identity.py`, including a cross-tenant denial
that was RED before the fix.

### What about the service-to-service calls in the `platform` profile?

The platform adapters source their S2S helper from the shared `hex-service-kit` commons
(`adapters/platform/_s2s.py`): base URLs must be `https://` outside loopback (rejected at
adapter construction), a bearer credential is attached from `S2S_TOKEN`, and the verified
end-user actor is propagated as an HMAC-signed `X-Tf-Actor` / `X-Tf-Actor-Sig` pair (keyed by
`S2S_SIGNING_KEY`) rather than a trust-me JSON field. All six platform delegates
(`remote_audit`, `remote_guardrail`, `remote_entitlements`, `remote_registry`, `remote_rules`,
`remote_evaluation`) validate their base URL at construction. The receiving platform services
own verification.

### Is the demo/dev server safe? Does anything bind 0.0.0.0 by default?

No. The bound is enforced twice, and the second one is the load-bearing half.

**At start-up**, `main()` resolves the bind host via `hex_service_kit.resolve_bind_host` and
refuses a non-loopback interface for any posture that authenticates no end user, unless
`TRADE_FINANCE_ALLOW_INSECURE_DEMO=1` is set. Only a posture whose bound identity adapter
actually verifies the end user keeps the container-friendly `0.0.0.0` (ingress is fronted by
the platform).

**On the app object**, `hex_service_kit.web.add_loopback_exposure_guard` is registered LAST, so
it is the OUTERMOST middleware: a non-loopback peer is refused with a 503 before CORS, before
the header baseline and before any route or dependency runs. This exists because
`resolve_bind_host` bounds only the process that CALLS it: one
`uvicorn trade_finance_checker.api.app:app --host 0.0.0.0` never reaches `main()`, and nothing
in this repo writes that today but nothing on the app object used to prevent it either. The
same `TRADE_FINANCE_ALLOW_INSECURE_DEMO=1` is the single acknowledged opt-out, read per
request.

Both halves derive the posture from the **identity adapter the active binding names**, read off
the class without constructing it (`ports/identity.py`, `config.end_user_auth_kind`) - never
from the profile string and never from a service credential. That matters here: `config/settings.yaml`
binds the same seeded-persona adapter under `live` as under `local`, so a rule keyed on the
profile name would have read `live` as a production posture and served dev personas to the LAN.
`S2S_TOKEN` authenticates a calling service and no end user, so it cannot stand the guard
down either.

CORS never uses `*`: origins come from an explicit `TRADE_FINANCE_CORS_ORIGINS` allowlist
(`hex_service_kit.cors_allowlist`), with a localhost dev-origin fallback that applies only under
a deliberately chosen `local` profile. Proven by `tests/unit/test_netdefaults.py` and
`tests/unit/test_serving_path_exposure.py`.

### What HTTP security headers are set?

The two surfaces differ, and the honest answer differs with them.

**The console** serves a full default-deny CSP, built once in `ui/lib/csp.mjs` and emitted by
`ui/proxy.ts`: `default-src 'self'`, `base-uri 'self'`, `form-action 'self'`,
`object-src 'none'`, `script-src` with a per-request nonce plus `'strict-dynamic'`,
`style-src 'self' 'unsafe-inline'` (the Next runtime injects critical CSS and there is no nonce
path for it), `img-src`/`font-src` `'self' data:`, a `connect-src` scoped to the API origin,
and `frame-ancestors`. Plus `X-Content-Type-Options: nosniff` and `Referrer-Policy:
no-referrer` from the static header table. The nonce is not cosmetic: without it the browser
blocks Next's inline hydration bootstrap and the console is dead markup, so
`ui/scripts/assert-hydratable.mjs` starts the built server and asserts every script tag in the
served document carries the served nonce.

**The API** (`api/app.py`) still emits only the embedding headers: CSP `frame-ancestors` from
`TRADE_FINANCE_FRAME_ANCESTORS` plus a conditional `X-Frame-Options` (`SAMEORIGIN` for
`'self'`, `DENY` for `'none'`). `X-Content-Type-Options: nosniff`, `Referrer-Policy` and HSTS
on secure profiles are **not yet set** there (check C6 in
[`docs/practices-audit.md`](../practices-audit.md)); a fork exposing that surface should add
them at the app or the edge before going live.

Both framing allowlists are read in three states: unset keeps the `'self'` default,
set-and-empty refuses at boot rather than inheriting it, and a value is used as given.

### How tamper-evident is the audit trail? What are its limits?

The `local` audit store wraps the shared `hex_service_kit.audit.HashChainedAuditLog`
(`adapters/local/audit.py`): a SHA-256 chain (`entry_hash = SHA-256(prev_hash ‖ record)` over
canonical JSON) with SQLite `UPDATE`/`DELETE` triggers enforcing append-only, and JSONL
export/restore with the chain re-verified line by line. The module docstring states the
limits exactly: `verify_chain` catches in-place edits, interior deletions and reordering, but
cannot by itself detect a truncated tail or a full rewrite by an actor with file write access
(the chain carries no secret). In production the `gcp` profile writes to a locked Cloud Logging
WORM bucket, which provides non-rewritability itself. This repo does not *replace* the platform
audit system (Hrz5); see [features-faq.md](features-faq.md). Proven by
`tests/unit/test_audit_chain.py`.

### Supply chain: are dependencies pinned and scanned?

Yes. Committed lockfiles (`requirements-dev.lock`, `requirements-gcp.lock`) are installed in
CI and the Docker build; the base image is pinned by digest; GitHub Actions are 40-char
SHA-pinned; `.github/dependabot.yml` proposes bumps; and a CI `supply-chain` job runs
`pip-audit` over both lockfiles as a hard gate. `ruff` is pinned exactly (`ruff==0.15.18`).
`npm audit` on the UI is advisory pending the catalog-wide Next.js bump.

### Where are secrets? Are any committed?

No secret values are in the repo. `config/settings.yaml` stores only `${ENV_VAR:-default}`
interpolation names and non-secret values (region, retention, model ids); the S2S credentials
are read from env at construction (`S2S_TOKEN`, `S2S_SIGNING_KEY`) and never logged. A
literal-secret grep is clean. The bundled UCP600 rules snapshot and every fixture are
obviously-fictional.

### What is explicitly out of scope / a residual risk?

- The full security-header baseline (nosniff / Referrer-Policy / HSTS / a strict UI CSP) is
  not yet emitted (C6, PARTIAL).
- There is no in-app rate limit; edge rate limiting (IAP / Apigee / LB) is expected in
  production.
- The hash chain needs the WORM bucket (or an external head anchor) to resist tail truncation
  and full rewrite.
- The runtime guardrail (PII redaction, prompt-injection / jailbreak defense) is the sibling
  **Hrz1** gateway; this repo consumes it rather than owning it.
- This is a reference build: run your own pen-test, threat model, and model-risk review before
  any live-data deployment (stated throughout the docs).
