# B4 Trade-Finance Document Checker : console

A thin Next.js console over the FastAPI backend. It renders a documentary-credit presentation,
the discrepancies found against the LC terms and UCP600, and the citation behind each one. All
demo data is fictional.

## Source map

| Path | What it owns |
| --- | --- |
| `app/layout.tsx` | Page chrome, and `export const dynamic = "force-dynamic"` (required by the CSP, see below) |
| `app/page.tsx` | The console itself |
| `components/` | Report, discrepancy card, citation chip, shared primitives |
| `lib/api.ts` | Thin client for the backend; base URL from `NEXT_PUBLIC_API_BASE` |
| `lib/csp.mjs` | **The one place the Content-Security-Policy is built.** Framing allowlist, nonce minting, and the build refusals |
| `proxy.ts` | Mints a per-request nonce and sets the policy on the request AND response headers |
| `next.config.mjs` | Static headers, base path, and the build/boot refusals from `lib/csp.mjs`. Emits NO CSP |
| `tests/csp.test.mjs` | What a policy STRING can decide |
| `scripts/assert-hydratable.mjs` | What only the served document can decide |

## The CSP, in one paragraph

`script-src` carries a per-request nonce plus `'strict-dynamic'`, because Next serves its
hydration bootstrap as an inline script and a bare `script-src 'self'` blocks it, leaving a page
that renders perfectly and does nothing. Next can only stamp a per-request nonce onto a
dynamically rendered route, so `app/layout.tsx` sets `force-dynamic` and `next.config.mjs`
refuses to build without it. The policy is built in `lib/csp.mjs` and emitted only by `proxy.ts`;
a CSP set in two layers is two policies the browser intersects, and the stricter one wins per
directive. Full rationale in [`docs/embedding-and-identity.md`](../docs/embedding-and-identity.md).

## Config

| Env var | Default | Purpose |
| --- | --- | --- |
| `NEXT_PUBLIC_API_BASE` | `http://localhost:8094` | Backend base URL. Its origin is what `connect-src` widens to |
| `NEXT_PUBLIC_FRAME_ANCESTORS` | `'self'` when unset | Who may frame the console. Set-but-empty REFUSES at build/boot; `'none'` refuses all framing |
| `NEXT_PUBLIC_BASE_PATH` | (empty) | Mount under a reverse-proxy sub-path |
| `NEXT_PUBLIC_EMBED` | (empty) | `1` drops the app chrome so a host page owns it |

## Gate

From the repository root:

```bash
make ui-install   # npm ci
make ui-check     # tsc + node tests + build + assert-hydratable
```

`assert-hydratable` runs LAST and against the artefact the build just made. It starts the
production server, fetches the document a browser would fetch, and asserts that the response CSP
carries every required directive, that none of them is empty, and that every `<script>` tag in
the document carries the response nonce. Everything cheaper than that has been fooled: the header
is byte identical in the working case and in the case where nothing hydrates.
