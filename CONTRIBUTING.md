# Contributing to Doc4 Trade-Finance Document Checker

Thanks for your interest. This is a public engineering-portfolio reference build; the bar is
production-grade style, internal consistency, and a green offline gate.

## Ground rules

- **Keep the domain pure.** Nothing under `src/trade_finance_checker/domain/` may import
  Google Cloud, ADK, FastAPI, httpx, or pydantic : standard library only. The verdict and
  the discrepancy set must stay deterministic; the LLM only drafts prose.
- **Keep GCP imports lazy.** Every `google-cloud-*` / `google-adk` / `google-genai` import
  lives inside a method or `__init__` (or under `TYPE_CHECKING`), never at module top level,
  so the on-prem/test profile imports with no GCP SDK installed.
- **One adapter constructor shape:** `def __init__(self, settings: Settings) -> None`.
- **Cite every discrepancy.** A finding without a citation to the LC term / UCP600 article /
  document is not acceptable.
- **No secrets in code.** Region is pinned to `asia-southeast1`.

## Setup

```bash
make install                      # python3.12 -m venv .venv && pip install -e ".[dev]"
. .venv/bin/activate
export TRADE_FINANCE_PROFILE=onprem
```

No Google Cloud SDK is needed for development or tests : the core deps are framework-light
and the GCP SDKs live in the `[gcp]` extra.

## The gate (must be green before you push)

```bash
make lint        # ruff check + ruff format --check + mypy
make test        # pytest -m 'not integration' (unit + contract)
make eval        # the offline Hrz4 eval gate (exit 0)
```

`ruff check`, `ruff format --check`, and `pytest -m 'not integration'` passing are
mandatory. `mypy` and the eval gate should pass too.

## Adding a check

The discrepancy checks live in
[`domain/detector.py`](src/trade_finance_checker/domain/detector.py). To add one:

1. Add a `DiscrepancyKind` (and, if needed, a UCP600 article constant) in the detector.
2. Implement a `_check_*` method that returns `list[Discrepancy]`, each with citations to
   the LC term and the UCP600 article (use `_lc_citation` / `_ucp_citation` / `_doc_citation`).
3. Call it from `DiscrepancyDetector.detect`.
4. Add a unit test in `tests/unit/test_detector.py` with a clean case and a planted case.
5. Add a golden example to `eval/datasets/golden_presentations.jsonl` so the eval gate covers
   it.

## Markdown & diagrams

- Minimise em-dashes in markdown (use colons / commas / parentheses).
- Validate any mermaid diagram you add with the mermaid CLI before pushing.

## Tests

- `tests/contract/` proves the on-prem placeholders satisfy every Protocol.
- `tests/unit/` drives the domain (detector + service) against in-memory fakes.
- `tests/integration/` is marked `@pytest.mark.integration` and is deselected by default;
  it needs live GCP credentials and the `[gcp]` extra.

## Commits & PRs

- Commits are authored solely by the contributor; do not add co-author trailers.
- Keep PRs focused. Describe what changed and how you verified the gate is green.

## Adding an adapter or sub-service

For an adapter, update the typed port, implement every declared profile family, update
`config/settings.yaml`, and extend `tests/contract/test_port_parity.py` with set-equality
between ports and settings. For a new check or sub-service, add the pure domain service,
re-export it from `domain/services.py`, wire it in `api/deps.py`, add one test per finding,
threshold, ranking, and determinism case, add eval and audit/demo coverage, then update SPEC,
ARCHITECTURE, COMPLIANCE, runbook, model card, and changelog.
