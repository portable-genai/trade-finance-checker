# Portability FAQ

For architecture, cloud-governance, and exit-planning teams. The claim this repo makes is
"no vendor lock-in" (General Principle P-02 / P-12), designed to be *shown* by profile swap,
not merely asserted. Cross-references: [`ARCHITECTURE.md`](../../ARCHITECTURE.md) (portability
principles), [`docs/onprem-migration.md`](../onprem-migration.md),
[`docs/ADOPTING.md`](../ADOPTING.md).

### What does "portable" actually mean here?

Three axes: **compute** (the whole stack migrates by a one-line profile change, no domain
edits), **data** (the audit trail exports in an open, documented format and reloads elsewhere
with integrity re-verified), and **identity** (identity resolves across hosts by an adapter
swap, not a rewrite). The profile swap and the `local == platform` behavioural parity are
proven by the contract suite (`tests/contract/test_behavioral_parity.py`), which runs offline
in CI with no cloud SDK.

### How does the profile switch work?

The pure-domain core speaks only to `typing.Protocol` **ports**; four **adapter families**
implement them, and `config/settings.yaml` binds one adapter per port per profile. Setting
`TRADE_FINANCE_PROFILE` (or `profile:` in the settings) rebinds the entire stack:

- `local`: a WORKING offline stack (SQLite FTS5 UCP600 rules index, deterministic LLM, regex
  DLP, hash-chained audit). No Google Cloud SDK. The default for dev/test/CI.
- `gcp`: real managed services (Document AI, Agent Search / File Search, Gemini, Model Armor,
  DLP, Cloud Logging WORM, Cloud Trace, Gen AI Evals).
- `platform`: thin HTTP clients delegating to the sibling horizontal-platform and
  de-risking services.
- `onprem`: fail-fast placeholder stubs that still satisfy every Protocol (the sovereign-exit
  target); a primary CLI command exits non-zero by design.

No `domain/` code changes across any of these. `tests/contract/test_port_parity.py` proves
both `local` and `onprem` construct and satisfy every port with a single `Settings` arg and no
cloud SDK installed, and asserts `set(PORT_PROTOCOLS) == set(settings.adapters)` (both drift
directions), so a binding with no port, or a port with no binding, fails loudly.

### Does the kernel/vertical split affect portability?

The intent is that the vertical-neutral machinery (`Citation`, `AuditEvent`, `EvalReport`,
`Severity`, `GuardrailVerdict`, `LlmRequest`) plus the commons is reusable across products,
while `domain/models.py` and `domain/detector.py` hold the trade-finance vertical. That split
holds today, and audit check A7 is PASS. `domain/kernel.py` DEFINES the
neutral types and imports nothing from `trade_finance_checker`; `domain/models.py` imports the
kernel and re-exports every one of those names, so a fork can import the kernel without
dragging in the LC and presentation artifacts it is about to rewrite, and no existing import
site had to change. The direction is proven by execution, not by prose:
`tests/unit/test_kernel_boundary.py` imports the kernel in a fresh interpreter and asserts
`domain.models` never reaches `sys.modules`. The keep-vs-rewrite rule is in
[`docs/ADOPTING.md`](../ADOPTING.md) §1. Neither the domain nor the ports import a cloud SDK or
a framework, so the portability guarantees hold regardless.

### How do we get our data out?

The audit trail is a hash chain that exports to / restores from JSON Lines with the chain
re-verified line by line (`hex_service_kit.audit.HashChainedAuditLog` behind the audit port).
Records rehydrate to first-class `AuditEvent` objects via `domain/serialization.py`. The exit
story for the audit trail is "copy the JSONL file and re-verify", not "migrate a product".
Reports and extracts serialize the same way via `to_jsonable`. (Note: this is a library-level
capability today; there is no `trade-finance-checker audit` CLI subcommand yet.)

### Is on-prem / sovereign deployment real or aspirational?

The `onprem` adapters are deliberate fail-fast placeholders (they raise `NotImplementedError`)
that nonetheless satisfy every Protocol and construct with a single `Settings` arg, so the
*interface contract* for a sovereign migration is proven and enforced by CI today. The actual
on-prem implementations are the migration work, scoped in
[`docs/onprem-migration.md`](../onprem-migration.md). This repo is not the sovereign-exit
*planner* (that is **Rgc9** `operational-resilience-mapping` and its `domain/concentration_exit/`
module: APRA CPS 230, MAS/HKMA outsourcing); this repo is one of the systems whose exit that
planner reasons about.

### Does residency compromise portability?

No: residency is a deploy-time pin (the region, an Org Policy resource-location allowlist,
CMEK, VPC-SC), and portability is the ability to change *where* the stack runs by
configuration. They are orthogonal. `infra/terraform/` pins `var.region` to `asia-southeast1`
with a fail-fast validation, and a second enterprise or a second region is a tfvars change,
not a fork. The residency-violation CI gate is **Rsk3** `architecture-validator` and its
`domain/residency/` module, which a fork should run rather than re-implement.

### What is NOT yet portable / an executable claim?

The exit-code-gated portability script runs inside `make check` (check F3, PASS):
`scripts/portability_demo.py` gates the offline suite, port parity, the cloud-free domain and the
fail-closed exit seam in one command. What it deliberately does NOT prove, and what no offline
gate can: live GCP calls, hosted identity, managed durability, CMEK / VPC-SC / Org Policy
enforcement, performance parity, or a completed on-premises adapter. Those need deployment
evidence, and the script says so in its own output rather than letting a green exit code imply
them.
