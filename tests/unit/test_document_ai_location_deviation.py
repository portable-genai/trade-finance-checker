"""Document AI may sit in a named multi-region, and in nothing else.

`infra/terraform/variables.tf` has validated `docai_location` since the region move: the
deploy region or a named multi-region, `global` refused by name. The runtime carried no such
check, so the two halves of one decision disagreed. An operator who set
`TRADE_FINANCE_DOCAI_LOCATION=global` got an unlocated processor silently: the value reached
the adapter, `/healthz` still reported `asia-southeast1`, and LC and presentation bytes were
parsed somewhere the residency record cannot name. `global` is precisely what someone reaches
for to make a failing single-region call succeed, which is why refusing it has to happen where
the value is read rather than only where the processor is created.

The rule is the one `loan-document-intelligence` already enforces, and the one Terraform
already enforces beside it:

* the deploy region is allowed, and is the preferred state;
* a named MULTI-REGION is allowed, because it names one jurisdiction and carries Google's
  ML-processing commitment for that geography;
* everything else is refused, including `global`, which names no jurisdiction, and including
  another single region, which is neither the deploy region nor a multi-region commitment.

Document AI is the only field this binds. `models.location` is a separate axis with its own
stated deviation, and this must not reach it.
"""

from __future__ import annotations

import pytest

from trade_finance_checker.config import DocumentAiSettings, ModelSettings, Settings


def _settings(location: str) -> Settings:
    return Settings(document_ai=DocumentAiSettings(location=location))


def test_the_region_itself_is_allowed() -> None:
    assert _settings("asia-southeast1").document_ai.location == "asia-southeast1"


@pytest.mark.parametrize("multi_region", ["us", "eu"])
def test_a_named_multi_region_is_allowed_as_a_stated_deviation(multi_region: str) -> None:
    assert _settings(multi_region).document_ai.location == multi_region


def test_global_is_refused_because_it_names_no_jurisdiction() -> None:
    with pytest.raises(ValueError, match="global"):
        _settings("global")


@pytest.mark.parametrize("elsewhere", ["us-central1", "europe-west2", "asia-northeast1"])
def test_another_single_region_is_refused(elsewhere: str) -> None:
    """A different single region is neither the deploy region nor a multi-region commitment."""
    with pytest.raises(ValueError):
        _settings(elsewhere)


def test_an_empty_location_is_refused_rather_than_inheriting_the_region() -> None:
    """Set-and-empty is not unset: it names nothing, so it must not take the documented default."""
    with pytest.raises(ValueError):
        _settings("")


def test_the_shipped_settings_file_still_loads() -> None:
    """The guard must refuse `global`, not the configuration this repository actually ships."""
    assert Settings.load().document_ai.location == "us"


def test_the_model_location_is_a_separate_axis_and_is_untouched() -> None:
    """Vertex serves its own set of locations; this guard binds Document AI only."""
    assert Settings(models=ModelSettings(location="us")).models.location == "us"
