"""Contract for the canonical fictional presentation used by the Doc4 UI.

The UI imports ``eval/samples/presentation.json`` directly, so this test exercises the
same request a user submits with "Check presentation".  It guards against changing the
canonical LC without changing the fail-closed local entitlement registry and proves the
sample still produces a useful cited discrepancy report.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from tests.conftest import LOOPBACK_PEER

from trade_finance_checker.adapters.local.entitlements import LocalAclAdapter
from trade_finance_checker.api import deps
from trade_finance_checker.api.app import app
from trade_finance_checker.config import Container, LocalSettings, Settings

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PRESENTATION_PATH = _REPO_ROOT / "eval" / "samples" / "presentation.json"


def _container() -> Container:
    """Build an ephemeral local container for the UI demo contract."""
    base = Settings.load("config/settings.yaml")
    settings = Settings(
        project_id=base.project_id,
        region=base.region,
        profile="local",
        kms_key=base.kms_key,
        models=base.models,
        document_ai=base.document_ai,
        rules_kb=base.rules_kb,
        model_armor=base.model_armor,
        dlp=base.dlp,
        logging=base.logging,
        agent_engine=base.agent_engine,
        check=base.check,
        local=LocalSettings(rules_db_path=":memory:", audit_path=":memory:"),
        adapters=base.adapters,
    )
    return Container(settings)


def test_canonical_ui_presentation_is_authorized_and_returns_cited_report(
    monkeypatch,
) -> None:
    presentation = json.loads(_PRESENTATION_PATH.read_text(encoding="utf-8"))
    lc_number = presentation["lc"]["lc_number"]
    container = _container()

    assert LocalAclAdapter(container.settings).owner(f"lc:{lc_number}") is not None

    monkeypatch.setattr(deps, "get_container", lambda: container)
    response = TestClient(app, client=LOOPBACK_PEER).post("/v1/check", json=presentation)

    assert response.status_code == 200
    report = response.json()
    assert report["lc_number"] == lc_number
    assert report["discrepancies"]
    assert all(discrepancy["citations"] for discrepancy in report["discrepancies"])
