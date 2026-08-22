# Adoption FAQ

For an engineering lead forking this repo as their institution's base. The step-by-step is
[`docs/ADOPTING.md`](../ADOPTING.md); this answers the "will it hurt later?" questions.

### How do I rebrand it for my institution?

`scripts/rename_fork.py` rewrites the package name (`trade_finance_checker`), the CLI entry
point (`trade-finance-checker`), the `TRADE_FINANCE_` env prefix, and the resource-id stem in
one pass (preview with `--dry-run`, apply with `--yes`). In this repo the CLI name, the
resource stem, and the pip distribution name are the one string `trade-finance-checker`, so a
fork normally passes the SAME value for `--cli` and `--resource`. Then recreate the venv,
`pip install -e ".[dev]"`, and run `make lint test eval`. The script does the mechanical
rename; the human decisions (region, IdP, PII pack, check policy, fixtures, eval golden set)
are the checklist in `ADOPTING.md`.

### If several banks fork this, how does each take upstream fixes?

Track upstream via **git tags** (semver). The repo declares a **core-vs-adopter-owned boundary** (ADOPTING §2): upstream owns
the generic ports under `ports/`, `tests/contract/`, the eval harness mechanics
(`eval/run_eval.py`), CI, the hexagon wiring (`config.py`, `api/deps.py`), and the pinned
`hex-service-kit` / `agent-eval-kit` / `review-kit` commons; you own `config/settings.yaml`
*values*, the local fixtures and the UCP600 rules snapshot, `adapters/onprem/*`, UI theming,
the golden eval dataset, and `COMPLIANCE.md` jurisdiction rows. Rebase your adopter-owned
changes onto each release rather than merging `main` continuously, so conflicts stay in files
you were told to expect.

### How do I add a new outbound dependency (a new port)?

There is a fixed touch list, and the contract test fails loudly if you miss part of it
(`tests/contract/test_port_parity.py::test_port_protocols_matches_settings_adapters` asserts
set-equality between `PORT_PROTOCOLS` and the settings adapter map, both drift directions):
define the `@runtime_checkable` Protocol under `ports/`, re-export it from `ports/__init__.py`,
implement one adapter per profile (at least `local` and `onprem`), bind all of them in
`config/settings.yaml` under `adapters:`, add the port to `PORT_PROTOCOLS`, add a
`cached_property` on the `Container`, and wire it in `api/deps.py`. See
[`CONTRIBUTING.md`](../../CONTRIBUTING.md) (note: the adapter / port extension touch list in
CONTRIBUTING is still being filled out, check G6 in
[`docs/practices-audit.md`](../practices-audit.md); the parity test is the enforcing contract
in the meantime).

### How do I change the check policy without touching code?

The numbers a trade-operations function owns live under `check:` in `config/settings.yaml`
(amount tolerance, description overlap, date and document rules), parsed into `CheckSettings`.
The `DiscrepancyDetector` accepts these as constructor params and a unit test overrides them.
One honest caveat: `settings.check` is **not yet threaded** from `api/deps.py` into the detector
(check B4, PARTIAL), so a `config/settings.yaml` override is inert end to end until you wire it
in `api/deps.py::build_trade_check_service`. Do that if your overrides must bite in the API and
CLI paths.

### How do I change the taxonomy (discrepancy kinds, doc types, severities)?

The vocabularies are `StrEnum`s (ten of them, via the shared `hex-service-kit`) and the engines
are typed on plain `str`, so members ARE their wire values and you extend the vocabulary
without editing engine code. Serialized JSON values are the enum strings. To replace the
taxonomy wholesale for a different vertical, edit the enums in `domain/models.py` and the label
maps in the UI.

### Will the demo rot after I diverge?

It is guarded, in two stages, and both are executable (checks F2 and F3, PASS, in
[`docs/practices-audit.md`](../practices-audit.md)). The renderer and the demo server emit
stable `data-*` evidence hooks for every load-bearing figure. `make demo-selftest`, which runs
inside `make check`, starts the REAL demo server on an ephemeral port, walks every presenter
step over HTTP and compares each hook in the served bytes against the value the running app
just computed, so a refactor that breaks a step or quietly stops recomputing a figure fails the
gate. `make demo-browser` adds the other half: headless Chromium loads the same served pages,
clicks the presenter's own Next button and reads the figures out of the live DOM. Playwright is
pinned in the `[demo]` extra rather than `[dev]`, because the browser binary is a network
download and the day-one offline install must not need one; that stage skips itself when the
extra is absent. Both stages have been proven able to go RED against a planted stale figure and
a stripped panel hook. If you diverge, keep the hooks: they are the contract both stages read.

### Does the CI run for my fork out of the box?

Yes. CI and the eval gate run on the `local` profile with **no cloud credentials and no org
secrets** (`ci.yaml` / `eval-gate.yaml` set `TRADE_FINANCE_PROFILE: local` and reference no
`secrets.`), so a fork's build is green immediately. You add secrets only when you wire the
`gcp` / `platform` profiles. Note the eval gate measures the *reference* trade-finance vertical
until you rebuild the golden set; that is an explicit adoption step, not a silent pass.
