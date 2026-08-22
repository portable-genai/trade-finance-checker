# Adopting this repo as your base

This repository is a **common base** that BFSI institutions (and other regulated industries)
fork to build their own document-diligence agents: trade-finance checking, CDD/KYC,
credit-memo review, insurance-claims triage, ESG due diligence. It ships a reusable
hexagonal core (a pure-stdlib domain, typed ports, swappable adapter profiles, a green
offline gate) plus a fully worked UCP600 trade-finance vertical (parse a Letter of Credit
and the presented document set, detect discrepancies against the LC terms and UCP600) you
can keep, replace, or learn from.

This guide is the step-by-step for making it yours. It has two halves: a **mechanical
rebrand** (one script) and the **human decisions** the script cannot make for you.

> Related reading: [`ARCHITECTURE.md`](../ARCHITECTURE.md), [`SPEC.md`](../SPEC.md),
> [`CONTRIBUTING.md`](../CONTRIBUTING.md) (adding a port / sub-service), the
> [`faq/`](faq/) directory.

---

## 1. What you keep vs what you rewrite

The domain is split so the boundary is (mostly) explicit:

| Layer | Where | For a new vertical |
|---|---|---|
| **Kernel** (vertical-neutral) | `domain/serialization.py`, the generic value types (`Citation`, `AuditEvent`, `EvalReport`, `Severity`, `GuardrailVerdict`, `LlmRequest`) plus the commons in `hex-service-kit` / `agent-eval-kit`, and the generic ports (extraction, generation, governance, identity, observability, rules, runtime, safety, review-router) | keep untouched |
| **Policy** (your numbers) | the `check:` section of `config/settings.yaml` parsed into `CheckSettings` (amount tolerance, description overlap, date rules) | change by config, not code |
| **Vertical** (trade-finance artifacts) | `domain/models.py` (LC + presentation + `Discrepancy` + `DiscrepancyReport`), `domain/detector.py`, `domain/prompts.py`, the local fixtures, the eval golden set, the UI report views | rewrite for your artifacts |

If your product is another *document-diligence* vertical, most of the domain machinery and
the deterministic detector engine transfer directly; you replace the artifact models and the
prompts, and retune the policy and taxonomy.

> `domain/kernel.py` now names the neutral import surface, but it still re-exports definitions
> from the mixed `domain/models.py`. Audit check A7 remains PARTIAL until neutral definitions
> move into the kernel and vertical models import them.

## 2. Core-vs-adopter-owned files (so upstream merges stay mechanical)

Upstream keeps evolving these; avoid diverging from them so you can pull fixes cleanly:

- **Upstream-owned** (take our changes): the generic ports under `ports/`, `tests/contract/`,
  the eval harness mechanics (`eval/run_eval.py`), CI workflows, the hexagon wiring
  (`config.py` container, `api/deps.py`), and the pinned `hex-service-kit` / `agent-eval-kit`
  / `review-kit` commons.
- **Adopter-owned** (yours; expect to edit): `config/settings.yaml` *values*, the local
  fixtures and the UCP600 rules snapshot, `adapters/onprem/*`, UI theming/branding, the
  golden eval dataset, `COMPLIANCE.md` jurisdiction rows.

Track upstream via git tags; rebase your adopter-owned
changes onto each release rather than merging `main` continuously.

## 3. The mechanical rebrand (one script)

`scripts/rename_fork.py` rewrites the package name, CLI entry point, `TRADE_FINANCE_` env
prefix, and resource ids across the tree in one pass. In this repo the CLI name, the
resource-id stem, and the pip distribution name are the one stem `trade-finance-checker`, so
a fork normally passes the SAME value for `--cli` and `--resource`. Preview first, then
apply:

```bash
# Preview (writes nothing):
python scripts/rename_fork.py --package acme_tf_agent --cli acme-tf \
    --env-prefix ACME --resource acme-tf --dry-run

# Apply:
python scripts/rename_fork.py --package acme_tf_agent --cli acme-tf \
    --env-prefix ACME --resource acme-tf --yes

# Then recreate the environment (the distribution name changed) and prove it is green:
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
make lint test eval
```

Add `--include-docs` to sweep Markdown prose too (this also rewrites the repo/folder name
`trade-finance-checker` in clone URLs and CI badges to the `--dist` value, which defaults to
the `--resource` value). The script
deliberately does NOT touch the human decisions below.

## 4. The human decisions (the script can't make these)

1. **Region / residency.** Set the Terraform `region`/`tfvars` and the `TRADE_FINANCE_KMS_KEY`
   to your in-country region. The build defaults to `asia-southeast1` (MAS / Singapore) and
   validates it fail-fast. See [`docs/runbook.md`](runbook.md) and
   [`infra/terraform/`](../infra/terraform/).
2. **Identity / IdP.** Secure identity is the Cloud IAP-injected assertion, verified
   server-side in `adapters/gcp/iap_identity.py`; set `TRADE_FINANCE_IAP_AUDIENCE` to your
   IAP-protected resource. The `local` profile uses seeded dev personas with no IdP. See
   [`docs/embedding-and-identity.md`](embedding-and-identity.md).
3. **PII / jurisdiction pack.** Set `pii.jurisdictions` (and `TRADE_FINANCE_PII_JURISDICTIONS`
   for the eval gate) so redaction and the `pii_safety` metric detect YOUR national
   identifiers, not just the shipped SG/HK/JP/AU pack. Add a pattern pack to
   `domain/pii_patterns.py` if your jurisdiction is not yet listed.
4. **Check policy.** Own the numbers under `check:` in `config/settings.yaml` (amount
   tolerance, description overlap, date and document rules), parsed into `CheckSettings`. The
   defaults are a reference, not your policy. The shared composition root threads
   `settings.check` into both API and agent detector paths, with override tests preventing drift.
5. **Reference data is fictional.** The bundled UCP600 rules snapshot and every fixture use
   obviously-fake LC ids and synthetic goods. Replace them with your own synthetic data.
   **Do not run against live customer data without your own legal, security and model-risk
   sign-off.**
6. **Eval golden set.** Rebuild `eval/datasets/` and the rubrics for your vertical: a fork
   inherits a green gate that measures the WRONG thing until you do. The gate structure is
   generic; the golden cases are yours.
7. **Deployment posture.** Review the Dockerfile (digest-pinned base, non-root, healthcheck),
   `infra/terraform/` (Org Policy, CMEK, VPC-SC, WORM), and the loopback-by-default binding
   before you expose anything.

## 5. Do not duplicate the platform

This repo is one system in a catalog of composable GRC systems. Several concerns it
*touches* are owned by sibling platform services, and you should integrate rather than
rebuild them (see [`docs/faq/features-faq.md`](faq/features-faq.md) for the full map): the
guardrail gateway (Hrz1), the governed UCP600 knowledge base (Hrz2), the agent registry
(Hrz3), the AI-quality / eval gate (Hrz4), observability + WORM audit (Hrz5), the
human-review and maker-checker console (Hrz7, via `review-kit`, rule R8), and the
compliance assistant (Rsk1). The `platform` profile's adapters are already thin HTTP clients
to those services.

## 6. Adoption checklist

- [ ] Ran `scripts/rename_fork.py`, recreated the venv, `make lint test eval` green.
- [ ] Set region + Terraform tfvars + KMS key to your in-country region.
- [ ] Wired your IAP audience (or `onprem` IdP placeholder); confirmed no client-asserted actor is trusted.
- [ ] Set `pii.jurisdictions` + added a pattern pack if needed; `pii_safety` exercises your ids.
- [ ] Owned the `check:` numbers with your trade-operations function.
- [ ] Replaced the UCP600 rules snapshot and every synthetic fixture.
- [ ] Rebuilt the eval golden set + rubrics for your vertical.
- [ ] Reviewed the deploy posture (Dockerfile, Terraform, bind address).
- [ ] Decided which sibling platform services you integrate vs stub.
- [ ] Recorded your baseline upstream tag so you can take future fixes.
