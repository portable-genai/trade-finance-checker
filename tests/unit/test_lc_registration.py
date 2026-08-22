"""LC registration (the audience-data path) and the presentation template.

The owner registry is fail-closed, so an audience-entered LC must be claimable: the
verified principal's tenant registers it (never the request body's say-so), another
tenant's LC cannot be hijacked, and an unregistered LC still denies at /v1/check.
Also pins the real ICC citation on the built-in rule set: the fictional example.test
URLs are gone, and the paraphrased rules point at the official ICC publication page.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tests.conftest import LOOPBACK_PEER

from trade_finance_checker.adapters.local._seed import ICC_UCP600_URL, SEED_RULES
from trade_finance_checker.adapters.local.entitlements import LocalAclAdapter
from trade_finance_checker.api import deps
from trade_finance_checker.api.app import app
from trade_finance_checker.config import Container, LocalSettings, Settings
from trade_finance_checker.domain.entitlements import ObjectOwner


@pytest.fixture
def container() -> Container:
    base = Settings.load("config/settings.yaml")
    settings = Settings(
        profile="local",
        models=base.models,
        rules_kb=base.rules_kb,
        check=base.check,
        local=LocalSettings(rules_db_path=":memory:", audit_path=":memory:"),
        adapters=base.adapters,
    )
    return Container(settings)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, container: Container) -> TestClient:
    monkeypatch.setattr(deps, "get_container", lambda: container)
    return TestClient(app, client=LOOPBACK_PEER)


_NEW_LC_BODY = {
    "lc": {
        "lc_number": "LC-AUDIENCE-0001",
        "amount": 50000.0,
        "currency": "USD",
        "expiry_date": "2099-07-31",
        "latest_shipment": "2099-06-30",
        "incoterm": "CIF",
        "terms": {"goods_description": "500 cartons organic green tea"},
    },
    "documents": [
        {
            "doc_type": "invoice",
            "fields": {
                "amount": "50000.00",
                "currency": "USD",
                "goods_description": "500 cartons organic green tea",
            },
        }
    ],
}


def test_unregistered_audience_lc_denies_then_registration_authorizes(
    client: TestClient,
) -> None:
    denied = client.post("/v1/check", json=_NEW_LC_BODY)
    assert denied.status_code == 403, "fail-closed: an unclaimed LC must deny"

    registered = client.post("/v1/lcs", json={"lc_number": "LC-AUDIENCE-0001"})
    assert registered.status_code == 201, registered.text
    body = registered.json()
    assert body["tenant"] == "demo-bank"
    assert body["already_registered"] is False

    # Idempotent within the owning tenant.
    again = client.post("/v1/lcs", json={"lc_number": "LC-AUDIENCE-0001"})
    assert again.status_code == 201
    assert again.json()["already_registered"] is True

    checked = client.post("/v1/check", json=_NEW_LC_BODY)
    assert checked.status_code == 200, checked.text
    assert checked.json()["lc_number"] == "LC-AUDIENCE-0001"


def test_an_lc_owned_by_another_tenant_cannot_be_hijacked(
    client: TestClient, container: Container
) -> None:
    acl = container.acl
    assert isinstance(acl, LocalAclAdapter)
    acl.register("lc:LC-OTHER-TENANT", ObjectOwner(tenant="other-bank"))
    response = client.post("/v1/lcs", json={"lc_number": "LC-OTHER-TENANT"})
    assert response.status_code == 409


def test_presentation_template_is_downloadable_json(client: TestClient) -> None:
    response = client.get("/v1/presentations/template")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert "attachment" in response.headers["content-disposition"]
    body = response.json()
    assert "lc" in body and "documents" in body


def test_rules_cite_the_official_icc_page_not_fiction() -> None:
    assert ICC_UCP600_URL.startswith("https://2go.iccwbo.org/")
    for rule in SEED_RULES:
        assert rule.url == ICC_UCP600_URL
        assert "example.test" not in rule.url
        assert rule.article.startswith("UCP600 Art.")


def test_a_retired_rule_set_on_disk_is_reseeded(tmp_path: Path) -> None:
    """The rules index outlives the code, so a stale shipped rule set must not persist.

    Before the ICC citation fix the seeded rules pointed at a fictional host. Because
    the adapter only seeded an EMPTY index, an upgraded install kept serving those URLs
    from disk forever, which is exactly the "demo still shows fake links" failure.
    """
    from trade_finance_checker.adapters.local.rules import LocalFtsRulesAdapter
    from trade_finance_checker.domain.models import Ucp600Rule

    db = str(tmp_path / "rules.db")
    settings = Settings(
        profile="local",
        local=LocalSettings(rules_db_path=db, audit_path=":memory:"),
        adapters=Settings.load("config/settings.yaml").adapters,
    )
    stale = LocalFtsRulesAdapter(settings)
    stale.seed(
        (
            Ucp600Rule(
                article="UCP600 Art. 14",
                title="Standard for examination of documents",
                requirement="Retired text.",
                url="https://example.test/ucp600/art14",
                score=0.9,
            ),
        )
    )

    refreshed = LocalFtsRulesAdapter(settings)
    urls = {rule.url for rule in refreshed.retrieve_rules("examination of documents", top_k=10)}
    assert urls, "the re-seeded index must serve rules"
    assert all("example.test" not in url for url in urls)
    assert urls == {ICC_UCP600_URL}
