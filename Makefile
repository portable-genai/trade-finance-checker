# B4 Trade-Finance Document Checker : developer tasks.
# The dev / test default profile is 'local' : a WORKING offline stack (SQLite FTS5 over
# UCP600 + deterministic LLM) that runs the whole pipeline with NO Google Cloud SDK. The
# 'onprem' profile would fail fast; 'local' is the default when TRADE_FINANCE_PROFILE is
# unset, and production sets TRADE_FINANCE_PROFILE=gcp explicitly (see Dockerfile).

PY ?= python3.12
VENV ?= .venv
ACT = . $(VENV)/bin/activate
TF_DIR = infra/terraform

.PHONY: help venv install lock lint fmt fmt-check typecheck test test-all eval run-api run-ui \
        check check-local demo demo-selftest demo-browser install-demo portability \
        ui-install ui-check tf-init tf-plan docker clean

help:
	@echo "Targets:"
	@echo "  install    create venv and install -e .[dev] (no GCP SDK)"
	@echo "  lock       recompile both lockfiles from pyproject.toml (needs network)"
	@echo "  lint       ruff check + ruff format --check + mypy"
	@echo "  fmt        ruff format src tests"
	@echo "  test       pytest -m 'not integration' (unit + contract), profile=local"
	@echo "  test-all   pytest (includes integration; needs GCP creds)"
	@echo "  check-local  run the check CLI offline (profile=local) on the sample presentation"
	@echo "  demo       build the offline demo report JSON + render static audit-first HTML"
	@echo "  eval       run the offline A4 eval gate"
	@echo "  check      the full offline hard gate: lint + test + eval (no node, no cloud)"
	@echo "  ui-check   the console gate: tsc + node tests + build + assert-hydratable"
	@echo "  run-api    run the FastAPI app on :8094"
	@echo "  run-ui     run the Next.js UI (cd ui && npm run dev)"
	@echo "  tf-plan    terraform plan (asia-southeast1)"

venv:
	$(PY) -m venv $(VENV)

install: venv
	$(ACT) && pip install -e ".[dev]"

install-demo: venv
	$(ACT) && pip install -e ".[dev,demo]"
	$(ACT) && python -m playwright install chromium

# NOT a bare `uv pip compile`: that REPLACES the output file, destroying the header block and
# the `tag = commit` map with it. scripts/lock.py compiles and puts the header back, and
# tests/unit/test_repo_artifacts.py fails the gate if a lockfile ever appears without one.
lock: ## Recompile every lockfile from pyproject.toml and restore the tag = commit headers.
	$(ACT) && python scripts/lock.py

lint:
	$(ACT) && ruff check src tests eval scripts
	$(ACT) && ruff format --check src tests eval scripts
	$(ACT) && mypy src

fmt:
	$(ACT) && ruff format src tests

fmt-check:
	$(ACT) && ruff format --check src tests

typecheck:
	$(ACT) && mypy src

test:
	$(ACT) && TRADE_FINANCE_PROFILE=local pytest -m 'not integration' -q

test-all:
	$(ACT) && pytest -q

check-local:
	$(ACT) && TRADE_FINANCE_PROFILE=local trade-finance-checker check eval/samples/presentation.json

demo:
	$(ACT) && TRADE_FINANCE_PROFILE=local PYTHONPATH=src:tests \
		python scripts/trade_finance_demo.py demo-out/trade_finance_demo.json
	$(ACT) && PYTHONPATH=src:tests \
		python scripts/render_trade_finance_ui.py demo-out/trade_finance_demo.json demo-out

eval:
	$(ACT) && python eval/run_eval.py

portability: ## Execute the bounded offline/profile portability proof.
	$(ACT) && PYTHONPATH=src python scripts/portability_demo.py

demo-selftest: ## Prove the real presenter states and evidence hooks cannot rot silently.
	$(ACT) && TRADE_FINANCE_PROFILE=local PYTHONPATH=src:tests:scripts python scripts/demo_selftest.py

demo-browser: ## Drive the SERVED presenter demo through a real headless browser ([demo] extra).
	$(ACT) && TRADE_FINANCE_PROFILE=local pytest tests/browser -q -rs

check: lint test eval demo-selftest portability ## The full offline quality gate (no node, no cloud).

ui-install:
	npm ci --prefix ui

# assert-hydratable is LAST and deliberately so: it starts the server the build just made and
# reads the served document. Everything before it can be green while the console ships dead
# markup, which is exactly what happened before the nonce CSP landed.
ui-check:
	npm --prefix ui run lint
	npm --prefix ui test
	NEXT_TELEMETRY_DISABLED=1 npm --prefix ui run build
	npm --prefix ui run assert-hydratable

run-api:
	$(ACT) && python -m trade_finance_checker.api.app

run-ui:
	cd ui && npm install && npm run dev

tf-init:
	cd $(TF_DIR) && terraform init

tf-plan:
	cd $(TF_DIR) && terraform plan

docker:
	docker build -t trade-finance-checker:local .

clean:
	rm -rf $(VENV) .pytest_cache .ruff_cache .mypy_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
