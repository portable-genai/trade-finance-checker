# Compliance FAQ

For compliance, MLRO, and model-risk teams assessing the repo's regulatory posture.
Cross-references: [`COMPLIANCE.md`](../../COMPLIANCE.md) (the full principle -> control map),
[`SPEC.md`](../../SPEC.md), and the audited evidence in
[`docs/practices-audit.md`](../practices-audit.md).

### Is this making examination decisions autonomously?

No. It is a **decision-support** agent: every consequential output requires human review
(maker-checker, P-06). The deterministic engine produces a documented, replayable examination
(the verdict and every discrepancy); a qualified officer disposes (pay / refuse / waive).
HIGH/CRITICAL discrepancies escalate to enhanced review and are routed to the `human-review-console`
maker-checker console (rule R8), never to auto-execution.

### How is trade-party PII handled?

Redact-before-everything (P-04): `TradeCheckService` redacts the LC and every document (and
each extract) before any model, index, span, or audit call, and the `AuditEvent` stores only
`redacted_prompt` / `redacted_response`. National-identifier detection is
**jurisdiction-driven** (`pii.jurisdictions` in `config/settings.yaml`, overridable with
`TRADE_FINANCE_PII_JURISDICTIONS`, patterns in `domain/pii_patterns.py`), defaulting to the
SG/HK/JP/AU pack (NRIC, HKID, My Number, TFN) plus IN/GB, so a corridor outside APAC scrubs and
gates on its own identifiers. One pattern source feeds the runtime redactor, the GCP DLP info
types and the eval leak check, so the three cannot silently disagree. The runtime
guardrail/DLP itself is the sibling `agent-guardrail-gateway`; this repo consumes it.

### How is the work auditable / reproducible?

Every check writes an immutable, already-redacted WORM `AuditEvent` with the decision and the
citation set (P-07). Every discrepancy carries a `Citation` (LC term + UCP600 article +
document, P-10). The consequential logic is deterministic, so an examiner can recompute any
finding from the same inputs. The enterprise WORM audit system is `agent-observability`; the in-repo
hash-chained store is the offline/local stand-in (see [security-faq.md](security-faq.md) for
its exact tamper-evidence limits).

### What is the model-risk story?

An offline eval gate (`eval/run_eval.py`) scores discrepancy recall / precision / citation
accuracy / `pii_safety` against a synthetic golden set on the `local` profile with no
credentials, failing the build below threshold (P-08). `pii_safety >= 0.99` is the strictest
threshold and is falsifiable: the gate runs the real redactor and plants a per-market
identifier, so a disabled redactor or a defective pack row scores 0.0 rather than a vacuous
1.0. The enterprise promotion gate and red-team harness are the sibling `model-quality-gate` system; this
repo's gate mirrors its thresholds so merges are guarded locally, and gate mode refuses to run
outside `TRADE_FINANCE_PROFILE=platform|gcp`, where the `model-quality-gate` promotion gate owns the decision.
A fork must rebuild the golden set for its own vertical, or the gate measures the wrong thing.

### Which regulators does this map to?

`COMPLIANCE.md` maps the internal P-01..P-12 principles and the R1..R6, R8 dependency rules to
concrete code, resources and file pointers, with the MAS (Singapore) residency posture as the
default. Honest status: a dedicated, adopter-owned per-regulator crosswalk *appendix* (FCA /
RBI / OJK / HKMA / APRA as swappable rows) is **not yet** carried here (check G2, PARTIAL, in
[`docs/practices-audit.md`](../practices-audit.md)); adding it is an adoption step, and the
`trade-finance-checker`-control column is stable across regulators. At scale, `compliance-advisory` and
its `domain/control_mapping/` module generate and maintain these crosswalks; a large estate
should integrate them rather than hand-maintain the table.

### Is data residency enforced?

Yes at deploy time, with one stated exception. A single in-country region (default
`asia-southeast1` / Singapore) is validated to fail fast in `infra/terraform/`, with regional
endpoints, CMEK (`kms.tf`), WORM logging (`logging_worm.tf`), a VPC-SC perimeter (`vpc_sc.tf`)
and least-privilege IAM (P-01, P-03, P-10). **Document AI is not in-country:** it serves
`asia-southeast1` only once Google grants single-region access, so document extraction routes
to the `us` multi-region until then. That is a jurisdiction, not a global endpoint, and it is
recorded in [`COMPLIANCE.md`](../../COMPLIANCE.md) rather than absorbed. The residency-violation CI gate is `architecture-validator`
(`domain/residency/`); the exit/concentration-risk plan is `operational-resilience-mapping` (`domain/concentration_exit/`). This repo enforces residency in
its own infra and is one of the systems those tools reason about. One honest gap: Terraform is
not yet `fmt`/`validate`-checked in CI (check D5, PARTIAL).

### Can we run it against real customer data today?

Not without your own legal, security, and model-risk sign-off. Every fixture and the bundled
UCP600 rules snapshot are obviously-fictional (fake LC ids like `LC-G-001`, synthetic goods),
and the docs state throughout that this is a reference build. The adoption checklist
([`docs/ADOPTING.md`](../ADOPTING.md) §4 and the checklist in §6) lists the steps that must
precede any live-data use: replace reference data, own the `check:` policy, wire your IdP, set
your PII pack, and rebuild the eval golden set.

### Which trade-finance scope does it cover, and which does it not?

It covers documentary-credit (LC) examination against the LC terms and UCP600 across the
presented document set. It does not own sanctions/dual-use screening of the goods and parties,
transaction-monitoring, or the broader financial-crime lifecycle: those are adjacent catalog
systems. See [features-faq.md](features-faq.md) for the boundary and
[the organization's repository index](https://github.com/portable-genai) for the current map.
