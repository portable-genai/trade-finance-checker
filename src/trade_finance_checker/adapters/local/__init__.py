"""Local deployment profile adapters : a WORKING, offline laptop stack.

The ``local`` profile is the third deployment option alongside ``gcp`` (managed
Google Cloud services) and ``onprem`` (fail-fast Google Distributed Cloud migration
placeholders). Unlike ``onprem``, every adapter here is a *real, deterministic*
implementation that runs the whole B4 trade-finance check pipeline end to end with **no
Google Cloud, no API key, and no running emulators by default**:

* Rules retrieval (UCP600) -> a ``sqlite3`` **FTS5** index over the governed article set.
* LLM -> a deterministic, schema-driven generator (no model, no network).
* Guardrail -> a heuristic that blocks prompt-injection / jailbreak text.
* PII redaction -> regex de-identification driven by the configured jurisdiction packs
  (SG/HK/JP/AU by default) plus universal email / phone / account numbers.
* Document extraction -> a local plain-text / pypdf parser (Document AI stand-in).
* Audit -> an append-only local store (SQLite or in-memory), read-back supported.
* Tracer -> no-op spans.
* Registry / sessions / memory -> SQLite or in-process stores, seedable.
* Agent runtime -> an in-process check loop (not HTTP to a sibling service).
* Evaluation -> delegates to the in-repo offline eval gate.

Everything is **seedable** so the test suite stays deterministic, and the default code
path imports **no google-cloud package at module top level**. Optional higher-fidelity
local runs route to Google's official emulators when the standard ``*_EMULATOR_HOST``
env vars are set (the google client is imported lazily, only on that branch); see
:mod:`trade_finance_checker.adapters.local._emulator`.
"""
