# Common-base practices audit

- **Repo:** `trade-finance-checker`
- **Catalog id:** Doc4 (package `trade_finance_checker`, env prefix `TRADE_FINANCE`)
- **Authoritative source:** reconciled to the maintainer's cross-repository audit matrix, authoritative on verdicts.
- **Catalogue reference:** [`common-base-practices.md`](https://github.com/portable-genai/.github/blob/main/common-base-practices.md) (checks A1..G7)
- **Note:** This repo was audited against the reference build `cdd-sow-research` (Doc1). Each
  check below was re-run against the current tree (greps run, files opened, the offline gate
  executed), with this repo's package (`trade_finance_checker`) and env prefix (`TRADE_FINANCE`)
  substituted into every catalogue **Check** command.

Applicability: Doc4 ships a UI (`ui/`) and Terraform (`infra/terraform/`), so `[ui]` and
`[infra]` checks apply. C8 is `[ui]` but N-A because this repo does not own a login (identity is
IAP-verified at the edge, plus seeded local personas). **Load-bearing** checks (a FAIL breaks a
shared catalog guarantee) are A1-A6, C1-C5, D1-D3 and E1: all 15 are
PASS, with **no load-bearing PARTIAL or FAIL left**.

| Check | Verdict | Evidence / gap |
|---|---|---|
| **A1** Hexagonal core, stdlib-only domain `[all]` **(load-bearing)** | PASS | `grep -rE "google\|fastapi\|httpx\|pydantic\|boto3\|azure" src/trade_finance_checker/domain/` returns nothing; the suite imports and runs with no `google-cloud-*` installed (`import google.cloud` fails). |
| **A2** Ports are `@runtime_checkable` Protocols, re-exported once `[all]` **(load-bearing)** | PASS | All 14 ports carry `@runtime_checkable`; re-exported once from `ports/__init__.py`; `test_all_protocols_are_runtime_checkable` asserts it. Ports are grouped by concern (8 files: extraction/generation/governance/identity/observability/rules/runtime/safety) rather than one-file-each. |
| **A3** Swappable profiles by one config value `[all]` **(load-bearing)** | PASS | `TRADE_FINANCE_PROFILE = local\|gcp\|platform\|onprem`; per-port `adapters:` map in `config/settings.yaml`; `SDK_FREE_PROFILES=(local,onprem)` never fall back to gcp; offline suite runs on `pip install -e ".[dev]"` (104 passed, no GCP SDK). |
| **A4** One adapter constructor `Adapter(settings)` `[all]` **(load-bearing)** | PASS | `tests/contract/test_port_parity.py::test_adapter_constructs_with_single_settings_arg` parametrises over `SDK_FREE_PROFILES` x every port. |
| **A5** Lazy cloud imports in cloud adapters `[all]` **(load-bearing)** | PASS | `grep -n "^from google\|^import google" src/trade_finance_checker/adapters/gcp/*.py` returns nothing; the offline test leg imports every module with no SDK. |
| **A6** Contract tests enforce the hexagon; port map cannot drift `[all]` **(load-bearing)** | PASS | Both drift directions are guarded: `test_port_parity.py::test_port_protocols_matches_settings_adapters` asserts `set(PORT_PROTOCOLS) == set(settings.adapters)` (set-equality, stricter than the subset check in `test_serialization_and_config.py`), so a settings binding with no map entry (forward drift, silently untested) and a map entry with no binding (reverse drift) both fail loudly. `tests/contract/test_behavioral_parity.py` proves same-request behavioural parity for three ports with real `platform` httpx siblings (rules -> A2 `/v1/search`, guardrail -> A1 `/v1/guardrail/screen`, audit -> A5 `/v1/audit`), asserting `local == platform` via respx over the sibling HTTP contract plus local determinism across a re-run and the `onprem` fail-fast (`NotImplementedError`) contract for each, with an end-to-end proof that the full `TradeCheckService.check` pipeline runs under `local` and fails fast under `onprem` on a profile change alone. Structural parity + single-settings construction + fail-on-missing-binding remain in `test_port_parity.py`. |
| **A7** Kernel vs vertical split in the domain `[all]` | PASS | The arrow is inverted and executed, not asserted in prose: `domain/kernel.py` DEFINES the vertical-neutral machinery and imports nothing from `trade_finance_checker`; `domain/models.py` keeps the LC and presentation artifacts and re-exports every kernel name, so no import site changed. `tests/unit/test_kernel_boundary.py` proves the direction by importing the kernel in a FRESH interpreter and asserting `domain.models` never lands in `sys.modules`. RED proof: against a re-export shim the same file scores 15 failed / 24 passed; after the split, 39 pass. |
| **A8** Consume platform horizontals via thin delegates `[all]` | PASS | `adapters/platform/remote_*.py` are 52-121 lines, marshalling only; each horizontal concern (guardrail, rules/KB, audit, evaluation, registry) has a `platform` binding; the offline local stand-ins sit behind the same ports. |
| **B1** Consequential math is deterministic, pure, replayable `[agentic]` | PASS | `domain/detector.py::DiscrepancyDetector` computes the verdict and every discrepancy by pure stdlib code over the parsed LC + extracts; unit-tested in `test_detector.py`; the LLM only drafts the narrative and never overrides a finding. |
| **B2** Every claim carries a citation; empty retrieval is a hard error `[agentic]` | PASS | Every discrepancy carries deterministic LC, rule and document citations; empty or failed UCP600 retrieval raises `RulesUnavailableError`, so no apparently compliant ungrounded report is emitted. |
| **B3** Maker-checker on every consequential output `[agentic]` | PASS | `domain/review_policy.py::TradeReviewPolicy.requires_review()` always returns `True`; `DiscrepancyReport.requires_human_review` defaults `True`; HIGH/CRITICAL escalate (`Decision.ESCALATED`); asserted in `test_trade_check_service.py`. |
| **B4** Bank-owned policy numbers in config, defaults = reference `[all]` | PASS | The composition root injects both `CheckSettings` values into the frozen deterministic detector; an end-to-end wiring test proves overrides reach the runtime service. |
| **B5** Open taxonomy: `StrEnum` vocabularies, engines typed on `str` `[all]` | PASS | All ten vocabularies are `StrEnum` (via the shared `hex-service-kit` commons): members ARE their wire values and `.value` call sites are unchanged. |
| **C1** Identity resolved server-side; client actor/ACL discarded `[all]` **(load-bearing)** | PASS | `api/schemas.py` `CheckRequest`/`ExtractRequest` carry no `actor` field (documented); `api/security.py::get_principal` (`CurrentPrincipal`) resolves a verified `Principal` from the `IdentityPort` on every route; the actor flows from the principal, never the body. |
| **C2** Object-level authz derived server-side; tenant isolation by data tags `[all]` **(load-bearing)** | PASS | `domain/entitlements.py` supplies a server-side owner registry (`AclPort` -> `ObjectOwner`) and a fail-closed `authorize_object` gate: an LC whose owner is unknown, or whose tenant/roles the verified `Principal` does not hold, is denied before any redaction, extraction or retrieval. Enforced in `TradeCheckService.check`, so the CLI and agent paths inherit it, and mapped to HTTP 403 at the API. Covered by `tests/unit/test_entitlements.py` + `test_api_identity.py`, including a cross-tenant denial that was RED before the fix. |
| **C3** Redact before everything `[agentic]` **(load-bearing)** | PASS | `TradeCheckService._check_inner` redacts the LC + documents (and each extract) as its first step, before guardrail/extraction/rules/LLM/audit; `AuditEvent` stores only `redacted_prompt` / `redacted_response`. |
| **C4** Jurisdiction-driven PII packs keep the gate honest `[agentic]` **(load-bearing)** | PASS | `domain/pii_patterns.py` holds one pattern source (SG/HK/JP/AU default, plus IN/GB; universal email / phone / bank account) read by the runtime redactor (`adapters/local/redaction.py`), the DLP custom info types (`adapters/gcp/dlp_redaction.py`) and the eval leak check. Selection is config: `pii.jurisdictions` in `config/settings.yaml`, overridable with `TRADE_FINANCE_PII_JURISDICTIONS` (verified: `Settings.load().pii.jurisdictions` follows the env, and a value naming NO jurisdiction is refused at settings load rather than silently disabling every national-id row. Both spellings are distinguished from each other: an empty string is not silently treated as inheriting the shipped pack, and `","` resolves to no jurisdictions rather than to the default, a three-state distinction proven by execution in `tests/unit/test_pii_jurisdictions_three_state.py`). JP/AU/bare-HK rows are checksum-gated, ported verbatim from `onprem-dlp`. `eval/run_eval.py` runs the REAL `LocalRegexRedactionAdapter` (the `FakeRedactionAdapter` is deleted); four golden presentations, one per market, each plant that market's OWN identifier in the trade parties. **Scored two ways, and the second is what makes the claim real:** the pack-driven scan catches PII the pipeline re-introduced, and a literal check of the planted identifier (`_planted_pii_leak`) catches the pack itself being wrong, which the first is blind to by construction (a row that fails to match cannot detect what it failed to mask). Proven not falsely-green **per market**, verified by execution: healthy 1.0; redaction disabled 0.0 on all four; and **that market's pack row made defective 0.0 on all four**, which the pack-driven scan alone scored a vacuous 1.0 while the raw identifier sat in the WORM audit record. Two guards raise rather than score a vacuous 1.0: a case whose market has no fixture, and a case whose market is not in the configured pack (both verified to fire). |
| **C5** Fail-closed defaults everywhere `[all]` **(load-bearing)** | PASS | `main()` binds via `hex_service_kit.resolve_bind_host` (loopback for any posture that authenticates no end user, unless `TRADE_FINANCE_ALLOW_INSECURE_DEMO=1`); CORS is `cors_allowlist` (explicit `TRADE_FINANCE_CORS_ORIGINS`, never `*`; dev-origin fallback ONLY under a deliberate local). The same bound also rides the APP OBJECT via `add_loopback_exposure_guard` (registered last, so outermost), because a bound reachable only from `main()` is a property of one entry point rather than of the application; both halves read the posture off the BOUND IDENTITY ADAPTER CLASS (`config.end_user_auth_kind`), which is why `live` (same seeded personas, non-local profile string) is bounded too. Proven by `tests/unit/test_netdefaults.py` and `tests/unit/test_serving_path_exposure.py`. |
| **C6** Security-header baseline on every surface `[ui]` | PASS | The nonce-based console CSP and hydration proof remain; the API adds `nosniff`, `no-referrer`, and managed-profile HSTS alongside its frame policy. |
| **C7** S2S calls authenticated, https-only outside loopback `[all]` | PASS | `adapters/platform/_s2s.py` sources `hex_service_kit.s2s`; all six platform delegates (`remote_audit`, `remote_guardrail`, `remote_entitlements`, `remote_registry`, `remote_rules`, `remote_evaluation`) validate their base URL at construction and attach the S2S bearer + optional signed actor (headers `X-Tf-Actor`/`-Sig`). |
| **C8** Web login flow hardening `[ui]` | N-A | The repo does not own a login: identity is the IAP-injected assertion verified in `adapters/gcp/iap_identity.py` (plus seeded local personas). No `api/auth.py`, no `adapters/oidc/`, no PKCE/JWKS code. |
| **C9** Tamper-evident audit with honest limits `[all]` | PASS | `LocalAppendOnlyAuditAdapter` wraps the shared `hex_service_kit.audit.HashChainedAuditLog`: SHA-256 chain, UPDATE/DELETE triggers, JSONL export/restore, `verify_chain()`, honest-limits docstring. Proven by `tests/unit/test_audit_chain.py`. |
| **C10** No secret values in the repo `[all]` | PASS | `config/settings.yaml` stores only `${ENV_VAR:-default}` interpolation names and non-secret values (region, retention, model ids); a literal-secret grep is clean. |
| **D1** Locked, reproducible installs everywhere `[all]` **(load-bearing)** | PASS | `requirements-dev.lock` + `requirements-gcp.lock` are committed (uv pip compile); `ruff==0.15.18` is pinned exactly in `pyproject.toml`; CI and the Dockerfile install from the lockfiles. |
| **D2** Digest-pinned images, SHA-pinned Actions, dependabot, CI audit `[all]` **(load-bearing)** | PASS | Dockerfile build + runtime stages are `python:3.12-slim@sha256:423ed6ab...`; Actions are 40-char SHA-pinned (`actions/checkout@34e1148...`, `actions/setup-python@a26af69...`); `.github/dependabot.yml` present; CI has a `supply-chain` job running `pip-audit` over both lockfiles as a hard gate (`npm audit` is advisory pending the catalog-wide Next.js bump). |
| **D3** Whole gate runs offline, zero org secrets `[all]` **(load-bearing)** | PASS | `ci.yaml` + `eval-gate.yaml` set `TRADE_FINANCE_PROFILE: local`, reference no `secrets.`; empirically the offline suite (104 passed) and `python eval/run_eval.py` (GATE: PASS) run with no GCP SDK and no credentials. |
| **D4** Non-root, minimal, healthchecked container `[infra]` | PASS | `Dockerfile`: multi-stage, `USER appuser` (uid 10001), `HEALTHCHECK` against `/healthz`, `EXPOSE 8094`, `TRADE_FINANCE_PROFILE=gcp`; runtime stage copies only the venv (no build toolchain). |
| **D5** Deploy-time residency/sovereignty, parameterised `[infra]` | PASS | Singapore pinning, CMEK, VPC-SC and WORM controls are CI-gated by Terraform fmt/init/validate. Live enforcement still needs a named apply and evidence. |
| **E1** Offline eval smoke guards merge; Hrz4 owns promotion `[agentic]` **(load-bearing)** | PASS | `eval/run_eval.py` has the `--mode smoke|gate` split via the shared `agent-eval-kit` scaffold; `remote_evaluation.py` re-based on the shared `PromotionGateClient` (registered bundle `doc4-trade-finance` unchanged; the contract test's example-count fixture was corrected from the stale `n` key to the `n_examples` the Hrz4 server actually emits); gate mode refuses to run outside `TRADE_FINANCE_PROFILE=platform|gcp`. |
| **E2** Safety metric with strictest threshold, no false green `[agentic]` | PASS | `pii_safety >= 0.99` is the strictest threshold, and it is falsifiable: `eval/run_eval.py` runs the REAL `LocalRegexRedactionAdapter` rather than a stand-in that could mask exactly the literal tokens `score_pii_safety` scans for, which would let the metric pass regardless of what the production redactor does. The literal check itself is not the risk to guard against: a literal is a sound oracle against the REAL redactor, and it is deliberately kept (`_planted_pii_leak`) precisely because scoring off the shared pack alone reintroduces a subtler version of the same tautology (detector and redactor read one source, so neither sees a defect in that source). The two halves fail on different things, which is the point. Falsifiability is demonstrated per market against both a disabled redactor and a defective pack row (see C4), and the metric scans only DERIVED surfaces (the produced narrative, the audit records) never an echo of the planted input, so it measures the boundary rather than the fixture. |
| **E3** Fixtures and golden data obviously fictional `[all]` | PASS | `eval/datasets/golden_presentations.jsonl` is headed "Synthetic and clearly fictional" with fake LC ids (`LC-G-001`) and synthetic goods; fixtures use obviously-fictional trade parties. |
| **F1** Demo is code, offline, one command, presenter-paced `[all]` | PASS | `make demo` runs offline (`TRADE_FINANCE_PROFILE=local`) building the report JSON via the real `TradeCheckService` and rendering static audit-first HTML; `scripts/trade_finance_demo_playwright.py` + `scripts/trade_finance_demo_server.py` provide a live walkthrough; no cloud or API key. |
| **F2** Demo cannot rot silently `[all]` | PASS | Both halves execute. (1) Stable evidence hooks: the renderer and demo server emit `data-panel`, `data-report-*`, `data-discrepancy-*`, `data-summary-*`, `data-citation-source`, `data-officer-*` attributes carrying every load-bearing figure. (2) Served stage, inside `make check`: `scripts/demo_selftest.py` starts the REAL `ThreadingHTTPServer` on an ephemeral port, walks all four presenter steps over `POST /advance`, also fetches `/timeline`, and compares each hook in the SERVED bytes against what the RUNNING app computed. (3) Browser stage: `tests/browser/test_served_demo_ui.py` drives the same served pages through headless Chromium pinned by the `[demo]` extra (`playwright==1.62.0`), clicking the presenter's own Next button and reading figures from the LIVE DOM; `make demo-browser` runs it. RED proof: planting a stale hard-coded discrepancy count and stripping one `data-panel` hook failed BOTH stages, each defect independently; restoring made both green. Scope note: the browser stage self-skips when the `[demo]` extra is absent, so a day-one offline gate (D3) still installs and passes without a browser download; the served stage is unconditional. |
| **F3** Portability claim is executable `[all]` | PASS | `scripts/portability_demo.py` gates the offline suite, port parity, cloud-free domain and fail-closed exit seam while stating live GCP limits. |
| **G1** Declared doc authority order, kept true `[all]` | PASS | `README.md` declares the SPEC.md > ARCHITECTURE.md > COMPLIANCE.md hierarchy; `SPEC.md` has no stale "forthcoming/not built" describing a shipped feature. |
| **G2** Compliance mapping table + adopter-owned crosswalk `[all]` | PASS | COMPLIANCE includes an explicitly adopter-owned UCP600/MAS crosswalk with applicability, owner and evidence fields. |
| **G3** Documented, mechanised fork path `[all]` | PASS | `docs/ADOPTING.md` gives the kernel-vs-vertical boundary, the core-vs-adopter-owned file list, the mechanical-rebrand walkthrough and the human-decisions checklist; `scripts/rename_fork.py` rewrites the package (`trade_finance_checker`), the CLI (`trade-finance-checker`), the `TRADE_FINANCE_` env prefix, the resource stem and the distribution name in one pass, dry-run by default (docs swept only under `--include-docs`). Verified by execution: `--package x_test --cli x-test --env-prefix XTEST --resource x-test --dry-run` exits 0 with a sensible plan (55 files, 351 replacements) and writes nothing (git tree unchanged). |
| **G4** Retired `[all]` | N-A (retired) | Retired practice. Releases are tracked by git tag and the `pyproject.toml` version. |
| **G5** Role-specific FAQs referencing sibling systems `[all]` | PASS | `docs/faq/` carries a README index plus five role FAQs (security, portability, features, adoption, compliance), each naming the owning catalog id for adjacent capabilities (Hrz1 guardrail, Hrz2 UCP600 KB, Hrz3 registry, Hrz4 eval gate, Hrz5 audit, Hrz7 review console, Rsk1/Rsk3/Rsk6/Rgc9) rather than duplicating them, and each honest about this repo's own open items (C6 headers, A7 kernel split, B4 detector wiring, F2/F3, G2 crosswalk). |
| **G6** Contribution docs cover full extension touch list `[all]` | PASS | CONTRIBUTING lists adapter, check and sub-service touch points and names the enforcing parity test. |
| **G7** Markdown discipline: minimise em-dashes, validate mermaid `[all]` | PASS | 0 em-dashes across every `*.md` and `docs/*.md`; the repo uses the " : " convention consistently. |

**Verdict counts:** 39 PASS, 0 PARTIAL, 0 FAIL, 2 N-A. All 15
load-bearing checks PASS. Named GCP plan/apply and hosted identity remain external
deployment evidence, not a code-practice verdict. Headless-browser evidence is not part of
that external set: F2's browser stage runs locally against the repo's own demo server under
`make demo-browser`, and proves nothing about a deployed environment.

## Gaps carried to systems/

The following gaps should be recorded on the Doc4 row of
the maintainer's per-system register under
`Capability gaps`. Load-bearing gaps (break a shared catalog guarantee) are marked.

**Load-bearing:**

- **C4, D1, D2, C2.** See the rows above for the
  evidence; no load-bearing FAIL or PARTIAL remains.
- **A6.** A reverse set-equality drift guard
  (`test_port_protocols_matches_settings_adapters`, both drift directions) and
  `tests/contract/test_behavioral_parity.py` (respx `local == platform` parity for rules/guardrail/audit,
  local determinism re-run, `onprem` fail-fast, and an end-to-end profile-swap proof) guard this.
- **C5.** `main()` binds via
  `hex_service_kit.resolve_bind_host` (loopback under the no-auth local profile unless
  `TRADE_FINANCE_ALLOW_INSECURE_DEMO=1`) and CORS is an explicit `cors_allowlist`, never `*`;
  proven by `tests/unit/test_netdefaults.py`.
- **E1.** `eval/run_eval.py` has the
  `--mode smoke|gate` split via the shared `agent-eval-kit` scaffold, and `remote_evaluation.py`
  is based on the shared `PromotionGateClient`; gate mode refuses to run outside
  `TRADE_FINANCE_PROFILE=platform|gcp`.

**Quality-of-adoption:**

- **B4.** Both deterministic tolerances are injected from settings and tested.
- **B5.** All ten vocabularies are `StrEnum` via the
  shared `hex-service-kit`; members ARE their wire values and `.value` call sites are unchanged.
- **C7.** `adapters/platform/_s2s.py` sources
  `hex_service_kit.s2s`; all six platform delegates validate their base URL at construction and attach
  the S2S bearer plus optional signed actor.
- **C9.** `LocalAppendOnlyAuditAdapter` wraps
  `hex_service_kit.audit.HashChainedAuditLog` (SHA-256 chain, UPDATE/DELETE triggers, JSONL
  export/restore, `verify_chain()`, honest-limits docstring); proven by `tests/unit/test_audit_chain.py`.
- **C6 and D5.** API headers match the profile posture and CI validates Terraform.
- **E2.** The `pii_safety` gate runs the runtime redactor and detects with
  the same pattern source, so there is no false-green path.
- **F3 and G2.** Portability (`scripts/portability_demo.py`) and the adopter-owned
  UCP600/MAS crosswalk in COMPLIANCE ship.
- **F2.** Stable `data-*` hooks, a served
  self-test that drives the real HTTP server inside `make check`, and a pinned headless-browser
  walkthrough (`make demo-browser`, `playwright==1.62.0` in the `[demo]` extra) over the same
  served pages. Both stages are proven able to go RED against a planted stale figure and a
  stripped panel hook. The browser test reads through the session rather than caching
  `session.data` (which `reset()` rebinds), since caching it would compare the
  live DOM against a dead dict after `/restart`; the self-test is hardened
  the same way against the same latent trap.
- **G3.** `docs/ADOPTING.md` (kernel/vertical boundary +
  core-vs-adopter file list + rebrand walkthrough) and `scripts/rename_fork.py` (one-pass
  rebrand, dry-run verified: exit 0, 55 files / 351 replacements planned, nothing written) ship.
- **G4 : RETIRED.** A retired practice. Releases are tracked by git tag and the `pyproject.toml`
  version.
- **G5.** `docs/faq/` (README + five role FAQs naming the
  owning sibling catalog ids) ships.
- **G6.** CONTRIBUTING's extension checklist covers the full adapter / check / sub-service
  touch list and names the enforcing parity test.
- **A7.** The neutral types live in
  `domain/kernel.py`; `domain/models.py` imports and re-exports them, and a
  fresh-interpreter import probe proves the arrow points one way. RED before the split: 15 failed /
  24 passed.
