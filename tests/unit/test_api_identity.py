"""API-boundary identity tests: the server-verified Principal is the audit actor.

The request body no longer carries an ``actor`` (removed from the schemas). Instead the
active IdentityPort resolves a verified :class:`Principal` from the request headers and the
API threads ``principal.actor`` into the domain service. These tests prove:

* an unknown ``X-Dev-Persona`` selector is a 401 (unverified identity is never accepted), and
* the default (and a selected) persona subject is what lands in the WORM audit trail.

``deps.get_container`` is ``lru_cache``d, so we monkeypatch it to inject an in-memory
container (with a recording audit adapter) rather than mutating global env / cache state.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from tests.conftest import LOOPBACK_PEER

from trade_finance_checker.adapters.local.audit import LocalAppendOnlyAuditAdapter
from trade_finance_checker.api import deps
from trade_finance_checker.api.app import app
from trade_finance_checker.config import Container, LocalSettings, Settings
from trade_finance_checker.domain.models import AuditEvent

_SAMPLE_BODY = {
    "lc": {
        "lc_number": "LC-TEST-0001",
        "amount": 50000.0,
        "currency": "USD",
        "expiry_date": "2026-07-31",
        "latest_shipment": "2026-06-30",
        "incoterm": "CIF",
        "terms": {"goods_description": "500 cartons organic green tea"},
    },
    "documents": [
        {
            "doc_type": "invoice",
            "fields": {"amount": "50000.00", "currency": "USD"},
        }
    ],
}


class _RecordingAudit(LocalAppendOnlyAuditAdapter):
    """Local append-only audit that also keeps the AuditEvent objects for assertions."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.events: list[AuditEvent] = []

    def record(self, event: AuditEvent) -> None:
        self.events.append(event)
        super().record(event)


@pytest.fixture
def container() -> Container:
    """A real local Container with an in-memory, recording audit adapter."""
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
    c = Container(settings)
    # cached_property stores on the instance __dict__; seed it before first access so the
    # recorder is the one the service uses.
    c.__dict__["audit"] = _RecordingAudit(settings)
    return c


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, container: Container) -> TestClient:
    monkeypatch.setattr(deps, "get_container", lambda: container)
    return TestClient(app, client=LOOPBACK_PEER)


def test_unknown_dev_persona_is_401(client: TestClient) -> None:
    resp = client.post("/v1/check", json=_SAMPLE_BODY, headers={"X-Dev-Persona": "does-not-exist"})
    assert resp.status_code == 401


def test_empty_governed_rules_are_an_explicit_503(
    client: TestClient, container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    class EmptyRules:
        def retrieve_rules(self, query: str, top_k: int = 8):
            return ()

    container.__dict__["rules"] = EmptyRules()
    # Rebuild the request-scoped service after replacing the adapter.
    monkeypatch.setattr(
        deps,
        "get_trade_check_service",
        lambda: deps.build_trade_check_service(container),
    )
    response = client.post("/v1/check", json=_SAMPLE_BODY)
    assert response.status_code == 503
    assert response.json()["detail"] == "governed UCP600 rule evidence is unavailable"


def test_default_persona_is_the_audit_actor(client: TestClient, container: Container) -> None:
    # No X-Dev-Persona header => the first seeded persona (analyst) is the verified identity.
    resp = client.post("/v1/check", json=_SAMPLE_BODY)
    assert resp.status_code == 200
    events = container.__dict__["audit"].events
    assert events, "the check must write an audit event"
    assert events[-1].actor == "demo.analyst@bank.example"


def test_selected_persona_is_the_audit_actor(client: TestClient, container: Container) -> None:
    resp = client.post("/v1/check", json=_SAMPLE_BODY, headers={"X-Dev-Persona": "approver"})
    assert resp.status_code == 200
    events = container.__dict__["audit"].events
    assert events, "the check must write an audit event"
    assert events[-1].actor == "demo.approver@bank.example"


def test_body_actor_is_ignored(client: TestClient, container: Container) -> None:
    # A client that still sends a body ``actor`` must not influence the audit actor: the
    # field is dropped by the schema and the verified persona wins.
    body = {**_SAMPLE_BODY, "actor": "attacker@evil.example"}
    resp = client.post("/v1/check", json=body)
    assert resp.status_code == 200
    events = container.__dict__["audit"].events
    assert events[-1].actor == "demo.analyst@bank.example"


# --------------------------------------------------------------------------- #
# Object-level authorization (C2): the LC in the body is server-side owned by
# ``demo-bank`` (adapters/local/entitlements.py). An authenticated caller from a
# DIFFERENT tenant is not entitled to it: fail-closed 403 BEFORE any processing.
# --------------------------------------------------------------------------- #
def test_cross_tenant_persona_is_denied_403_without_audit_or_report(
    client: TestClient, container: Container
) -> None:
    # ``other-tenant`` (tenant other-bank) is authenticated but NOT entitled to a
    # demo-bank-owned LC. The check must be denied with 403.
    resp = client.post("/v1/check", json=_SAMPLE_BODY, headers={"X-Dev-Persona": "other-tenant"})
    assert resp.status_code == 403
    # Fail-closed: the deny happens before extraction/audit, so NO check audit event
    # is written and NO report body is returned (a 403 error payload, never findings).
    events = container.__dict__["audit"].events
    assert [e for e in events if e.action == "check"] == []
    body = resp.json()
    assert "discrepancies" not in body
    assert "verdict" not in body


def test_entitled_demo_bank_personas_are_allowed_200(
    client: TestClient, container: Container
) -> None:
    # The analyst and approver personas belong to demo-bank and hold a permitted role,
    # so they are entitled to the demo-bank-owned LC and get a 200 report.
    for persona, subject in (
        ("analyst", "demo.analyst@bank.example"),
        ("approver", "demo.approver@bank.example"),
    ):
        resp = client.post("/v1/check", json=_SAMPLE_BODY, headers={"X-Dev-Persona": persona})
        assert resp.status_code == 200, f"{persona} should be entitled to the demo-bank LC"
        assert container.__dict__["audit"].events[-1].actor == subject


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
