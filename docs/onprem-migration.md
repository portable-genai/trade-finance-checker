# On-prem migration checklist (P-12 exit story)

`trade-finance-checker`'s exit / portability promise is concrete, not aspirational: every managed-service port
has an on-prem placeholder adapter that **constructs cleanly and satisfies the same
Protocol** as the GCP adapter, and the contract tests prove it. Migrating to **Google
Distributed Cloud** (the on-prem target) is a matter of filling in those placeholders : the
domain core, the service, the API, the CLI, and the agent wiring do not change.

## What "switch the profile" means

The active adapter stack is chosen by `TRADE_FINANCE_PROFILE` (or `profile:` in
`config/settings.yaml`). Setting it to `onprem` rebinds all 13 ports to the
`adapters/onprem/*` family. With the placeholders unimplemented, every consequential call
raises `NotImplementedError` with a message that names the migration target, and the CLI
maps that to a clean exit code 2. Filling each placeholder in turns the system on-prem with
zero domain edits.

## Port-by-port migration

| Port | On-prem placeholder | What to implement on Google Distributed Cloud |
|------|---------------------|-----------------------------------------------|
| `DocumentExtractionPort` | `onprem/extraction.py` | An on-prem document parser for the LC and trade documents. |
| `RulesRetrievalPort` | `onprem/rules.py` | An on-prem search over the UCP600 article set. |
| `LLMPort` | `onprem/llm.py` | An on-prem model endpoint for the narrative + triage. |
| `GuardrailPort` | `onprem/guardrail.py` | An on-prem input/output safety screen. **Must not fail-open.** |
| `PIIRedactionPort` | `onprem/redaction.py` | An on-prem PII de-identifier. **Must not pass text through unredacted.** The jurisdiction packs in `domain/pii_patterns.py` are pure stdlib, so an on-prem implementation can reuse them (as `adapters/local/redaction.py` does) and stay consistent with what the eval gate scores. |
| `AuditSinkPort` | `onprem/audit.py` | An on-prem immutable (WORM) audit store. **Must not drop records.** |
| `ObservabilityTracerPort` | `onprem/tracer.py` | Already a safe no-op (tracing absent, not fatal); wire a collector later. |
| `EvaluationGatePort` | `onprem/evaluation.py` | An on-prem eval backend. **Must not wave a build through unevaluated.** |
| `AgentRegistryPort` | `onprem/registry.py` | An on-prem agent catalog. |
| `ToolCatalogPort` | `onprem/tool_catalog.py` | An on-prem MCP tool catalog. |
| `AgentRuntimePort` | `onprem/runtime.py` | An on-prem agent hosting surface. |
| `SessionPort` | `onprem/session.py` | An on-prem per-case session store. |
| `MemoryPort` | `onprem/memory.py` | An on-prem durable memory store. |

The safety / audit / eval placeholders deliberately **raise** rather than degrade silently:
an unimplemented guardrail, redactor, audit sink, or eval gate must never let traffic through
or drop a record. The tracer placeholder is the one exception (tracing is non-essential to
correctness, so it is a no-op).

## Verifying parity before and after

```bash
TRADE_FINANCE_PROFILE=onprem make test     # contract tests assert every port's parity
```

The contract suite (`tests/contract/test_port_parity.py`) constructs each on-prem adapter
with a single `Settings` argument, asserts it `isinstance` its runtime-checkable Protocol,
and asserts every Protocol member is declared. This is the test that makes the exit story
real: if a placeholder drifts from its port, CI fails.

## Residency note

Google Distributed Cloud keeps data on-premise, satisfying the strictest residency posture
(P-01). The region pin (`asia-southeast1`) and CMEK settings still apply to any managed
services you keep in the hybrid path.
