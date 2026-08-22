# trade-finance-checker

The shared working agreement is [`.github/AGENTS.md`](https://github.com/portable-genai/.github/blob/main/AGENTS.md).
It carries the architecture rules, the gate contract, the fleet invariants, the
falsification discipline, versions and house style, and it holds in every repository
here. Read it first. This file carries only what is specific to this one.

## What this is

Catalog id **Doc4**. Letter-of-credit vs UCP600 discrepancy detection across the
document set.

## Concrete bindings

| | |
|---|---|
| Catalog id | `Doc4` |
| Package | `src/trade_finance_checker/` |
| Profile variable | `TRADE_FINANCE_PROFILE` |
| Adapter families | `gcp`, `live`, `local`, `onprem`, `platform` |
| Gate | `make check` |

That variable is read in one module and resolved in three states: unset is no choice,
set-and-empty raises rather than inheriting the unset behaviour, and an unknown value
raises. Both raises happen before the process can serve a request.

## What this repository still owes

The `Capability gaps` cell on this repository's row in the maintainer's system tracker
is the authoritative list. Its verdict against the shared checks, including the ones it
does not pass, is in [`docs/practices-audit.md`](docs/practices-audit.md).
