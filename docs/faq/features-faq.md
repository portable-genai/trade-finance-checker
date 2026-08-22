# Features FAQ

For product, compliance, and delivery teams: what this agent does, what is deterministic vs
LLM, and, importantly, where its responsibilities **stop** and a sibling catalog system takes
over. Cross-references: [`README.md`](../../README.md), [`DEMO.md`](../../DEMO.md),
[`COMPLIANCE.md`](../../COMPLIANCE.md).

### What does Doc4 actually produce?

A cited **discrepancy report** (`DiscrepancyReport`). From a parsed Letter of Credit and the
presented document set (invoice, bill of lading, insurance certificate, packing list, ...) it
computes an examination verdict and every `Discrepancy` against the LC terms and UCP600:
amount tolerance, description overlap, dates (latest shipment, presentation period, expiry),
and document rules. Each finding carries `Citation`s (the LC term, the UCP600 article, and the
document it came from), so an ungrounded finding is structurally impossible. Every report sets
`requires_human_review=True` and writes an immutable, already-redacted WORM `AuditEvent`.

### What is deterministic vs done by the LLM?

The consequential logic is **deterministic and replayable** (pure stdlib, unit-tested):
`domain/detector.py::DiscrepancyDetector` computes the verdict and every discrepancy by code
over the parsed LC and the presented extracts. The LLM only **narrates** (drafts the
explanation and report prose) and **triages/classifies** (doc-type routing). It never
overrides a finding. An examiner can recompute every discrepancy without the model. This is by
design (the "deterministic domain service" pattern), tested in `test_detector.py`.

### Is anything auto-approved?

No. Every report sets `requires_human_review=True` (maker-checker, P-06); the agent proposes
and a qualified officer disposes (pay / refuse / waive). HIGH/CRITICAL discrepancies *raise*
the bar (`Decision.ESCALATED`); they never lower it and never auto-execute. The escalation is
**routed** to the Hrz7 Human-Review and Maker-Checker Console (rule R8, via `review-kit`),
not terminated in a per-repo boolean.

### Which capabilities does this repo own vs integrate from the catalog?

This is one system in a catalog of composable GRC systems. It **owns** the trade-finance
examination logic and its outputs. It **integrates** (via the `platform` profile's HTTP
adapters) several cross-cutting concerns owned by sibling platform systems; do not rebuild
these in a fork:

| Concern | Owned by (catalog id / repo) | Doc4's role |
|---|---|---|
| Runtime guardrail: PII redaction, prompt-injection / jailbreak defense | **Hrz1** `agent-guardrail-gateway` | consumes it on every check (input + output screen), rule R1 |
| Governed UCP600 rule set / ACL-aware RAG with citations | **Hrz2** `enterprise-knowledge-base` | retrieves UCP600 articles from it, never vendors them (rule R3) |
| Agent registry, versioning, identity, entitlements | **Hrz3** `agent-registry` | publishes its A2A AgentCard for discovery |
| AI-quality / eval / model-risk promotion gate | **Hrz4** `model-quality-gate` | its eval metrics gate promotion (P-08); the offline gate mirrors it |
| Observability + immutable WORM prompt/response audit | **Hrz5** `agent-observability` | writes audit events to it; traces spans through it (rule R2) |
| Human-review & maker-checker console | **Hrz7** `human-review-console` | routes every `requires_human_review` escalation to it (rule R8) |
| Regulatory Q&A / control checklists | **Rsk1** `compliance-advisory` | consumes it for regulatory compliance checks |
| On-prem, CPU-only DLP scrub before egress | **Rsk6** `onprem-dlp` | the sovereign-DLP option behind the redaction port (its checksum-gated packs are ported here) |

So the guardrail, knowledge base, audit sink, eval platform, and review console are
*dependencies*, not features of this repo.

### How does this relate to the other document-diligence systems in the catalog?

Doc4 is trade-finance document examination. It shares the hexagonal common base with the other
LND / document-diligence verticals: **Doc1** CDD + Source-of-Wealth (the reference build this
repo was audited against), **Doc2** credit-memo / underwriting assistant, and **Doc5**
loan / mortgage document intelligence. The reusable core (citations, grounding, the
deterministic engine, audit, eval, maker-checker) transfers between them; each replaces the
artifact models and prompts and retunes the policy/taxonomy. Check
[the organization's repository index](https://github.com/portable-genai) before building a
capability that may already have a home.

### Can I use this for a non-trade-finance document-diligence product?

Yes, that is the point of the kernel/vertical boundary (documented in
[`docs/ADOPTING.md`](../ADOPTING.md)). The reusable core transfers to credit-memo review,
CDD/KYC, claims triage, ESG due diligence, and similar. You replace the artifact models
(`domain/models.py`) and the prompts, retune the `check:` policy and the taxonomy, and rebuild
the eval golden set. See [adoption-faq.md](adoption-faq.md).

### How do I see it working?

`make demo` runs offline (`TRADE_FINANCE_PROFILE=local`), building the report JSON via the real
`TradeCheckService` and rendering static audit-first HTML, with no cloud and no API key.
[`DEMO.md`](../../DEMO.md) documents the offline examination walkthrough and the managed-GCP
one-shot demo. Everything runs on synthetic, fictional LC ids and goods.
