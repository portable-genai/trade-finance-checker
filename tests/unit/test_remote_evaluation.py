"""Contract tests for the platform A4 evaluation adapter (:class:`RemoteEvaluationAdapter`).

The adapter is a thin HTTP client to the shared ``model-quality-gate`` (A4) service.
These tests use ``respx`` to intercept the httpx calls and assert the *hardened* A4 wire
contract, the shape earlier builds got wrong:

* the request sends a structured ``target`` (model + prompt_version + dataset_id + system),
  not a bare dataset path;
* the top-level ``dataset_id`` equals ``target.dataset_id`` (A4 422s on divergence);
* metrics are selected by ``bundle == "doc4-trade-finance"`` and no metric names are sent
  (an unregistered name is now rejected 422);
* the response ``results[]`` (not the old, always-empty ``metrics``) parse into an
  :class:`EvalReport`, but only when the response also carries the evidence that lets
  somebody re-derive those scores later; and
* ``gate()`` POSTs to ``/v1/gate`` and returns a verdict RE-DERIVED from a complete
  promotion decision, never the aggregate boolean the service reports.

The response fixtures below are deliberately full. The hardened ``agent-eval-kit`` client
recomputes every verdict from the evidence and raises on any contradiction, so a body cannot
simply assert that a promotion passed: each metric row's ``passed`` has to equal
``score >= threshold``, the red-team aggregate has to equal the AND of its rows, and the
top-level verdict has to equal (quality AND attested AND red team). The refusal tests are as
much the contract as the happy path, because the shape they reject, a verdict with nothing
behind it, is a promotion certified by nothing.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from trade_finance_checker.adapters.platform.remote_evaluation import (
    RemoteEvaluationAdapter,
    RemoteEvaluationError,
)
from trade_finance_checker.config import Settings
from trade_finance_checker.domain.models import EvalReport

_BASE_URL = "https://a4.test"
_DATASET_PATH = "eval/samples/golden.jsonl"
_DATASET_ID = "golden"  # basename without the .jsonl suffix

# Names A4 would reject 422 if they ever appeared on the wire : the adapter must select
# metrics by bundle, never send metric names.
_METRIC_NAMES = (
    "discrepancy_recall",
    "discrepancy_precision",
    "citation_accuracy",
    "pii_safety",
)

#: Obviously fictional durable identifiers. Every one is REQUIRED by the hardened parse: a
#: score naming no run, no dataset state and no evaluator cannot be reproduced by anyone
#: reading the promotion record later, so it is a number rather than evidence.
_DIGEST = "sha256:feedfacefeedfacefeedfacefeedfacefeedfacefeedfacefeedfacefeedface"
_EVALUATOR = "hrz4-ai-quality (FICTIONAL)"
_DATASET_VERSION = "golden@2026-08-01"
_MODEL_CARD_REF = "gs://fictional-hrz4-evidence/model-cards/doc4-trade-finance.md"
_MRM_REF = "gs://fictional-hrz4-evidence/mrm/doc4-trade-finance-2026-08.json"

#: Every row is internally CONSISTENT: ``passed`` equals ``score >= threshold``.
_PASSING_ROWS = [
    {"metric": "discrepancy_recall", "score": 0.95, "threshold": 0.9, "passed": True},
    {"metric": "pii_safety", "score": 1.0, "threshold": 0.99, "passed": True},
]

#: The same pair with one genuine miss, so a FAIL can be reached through evidence.
_FAILING_ROWS = [
    {"metric": "discrepancy_recall", "score": 0.71, "threshold": 0.9, "passed": False},
    {"metric": "pii_safety", "score": 1.0, "threshold": 0.99, "passed": True},
]

#: Red-team rows: ``passed`` and ``blocked`` must AGREE (an attack that was not blocked did
#: not pass), and the aggregate must equal the AND of the rows.
_REDTEAM_PASSING = {
    "passed": True,
    "results": [
        {"case": "prompt-injection-01", "passed": True, "blocked": True},
        {"case": "pii-exfil-01", "passed": True, "blocked": True},
    ],
}


def _eval_body(*, run_id: str, results: list[dict], attested: bool = True) -> dict:
    """A complete evaluation response in the hardened shape.

    ``passed`` is deliberately absent: the client derives the aggregate from the rows, and a
    value that disagrees with them is a hard error rather than an override.
    """
    return {
        "results": results,
        "n_examples": 12,
        "run_id": run_id,
        "dataset_version": _DATASET_VERSION,
        "dataset_digest": _DIGEST,
        "evaluator": _EVALUATOR,
        "schema_version": "v1",
        "artifact_refs": [f"gs://fictional-hrz4-evidence/{run_id}/report.json"],
        "attested": attested,
    }


def _gate_body(*, passed: bool, results: list[dict], attested: bool = True) -> dict:
    """The full promotion decision, at every layer the client re-derives."""
    return {
        "passed": passed,
        "eval_report": _eval_body(run_id="run-fictional-0001", results=results, attested=attested),
        "redteam_report": _REDTEAM_PASSING,
        "model_card_ref": _MODEL_CARD_REF,
        "mrm_evidence_ref": _MRM_REF,
    }


@pytest.fixture
def adapter(monkeypatch: pytest.MonkeyPatch) -> RemoteEvaluationAdapter:
    monkeypatch.setenv("QUALITY_GATE_URL", _BASE_URL)
    return RemoteEvaluationAdapter(Settings(profile="platform"))


def _no_metric_names(body: dict) -> None:
    """No metric name appears anywhere in the request body (bundle selects the metrics)."""
    blob = repr(body)
    for name in _METRIC_NAMES:
        assert name not in blob, f"unregistered metric name {name!r} must not be sent to A4"
    assert "metrics" not in body, "the request must not carry a metric list"


@respx.mock
def test_evaluate_posts_structured_target_and_parses_results(
    adapter: RemoteEvaluationAdapter,
) -> None:
    route = respx.post(f"{_BASE_URL}/v1/evaluations").mock(
        return_value=httpx.Response(
            200, json=_eval_body(run_id="run-fictional-0002", results=_PASSING_ROWS)
        )
    )

    report = adapter.evaluate(_DATASET_PATH)

    assert route.called
    sent = json.loads(respx.calls.last.request.content)

    # Structured target with the pinned reasoning model, a stable prompt version, and the id.
    target = sent["target"]
    assert target["model"] == Settings(profile="platform").models.reasoning
    assert target["prompt_version"]  # stable, non-empty
    assert target["dataset_id"] == _DATASET_ID
    assert "system" in target

    # Top-level dataset_id equals target.dataset_id (A4 422s on divergence).
    assert sent["dataset_id"] == _DATASET_ID
    assert sent["dataset_id"] == target["dataset_id"]

    # Metrics selected by bundle; no metric names on the wire.
    assert sent["bundle"] == "doc4-trade-finance"
    _no_metric_names(sent)

    # results[] parsed into the domain EvalReport (not the old, always-empty "metrics").
    assert isinstance(report, EvalReport)
    assert report.dataset == _DATASET_PATH
    assert report.n_examples == 12
    assert [r.metric for r in report.results] == ["discrepancy_recall", "pii_safety"]
    assert report.results[0].score == pytest.approx(0.95)
    assert report.results[0].threshold == pytest.approx(0.9)
    assert report.passed is True

    # The EVIDENCE survives the adapter, not just the scores.
    #
    # It did not use to. A ``_to_domain`` mapper rebuilt a locally declared EvalReport out of
    # three fields, so every durable identifier the client had just validated was
    # dropped on the way out: the caller received numbers with nothing behind them, which is
    # the exact shape the client's refusal tests below exist to reject on the way in. The
    # domain type is now the commons type and the client's report is returned unchanged.
    assert report.run_id == "run-fictional-0002"
    assert report.dataset_version == _DATASET_VERSION
    assert report.dataset_digest == _DIGEST
    assert report.evaluator == _EVALUATOR
    assert report.schema_version == "v1"
    assert report.artifact_refs == ("gs://fictional-hrz4-evidence/run-fictional-0002/report.json",)
    assert report.attested is True


@respx.mock
def test_evaluate_REFUSES_scores_with_no_durable_run_identity(
    adapter: RemoteEvaluationAdapter,
) -> None:
    """Metric rows on their own are numbers, not promotion evidence.

    The client enforces the durable identifiers on the plain evaluations path too, not
    only inside ``gate()``. Without a run id, a dataset digest, an evaluator and an artifact
    ref, nobody can later reproduce the score or say which corpus produced it.
    """
    respx.post(f"{_BASE_URL}/v1/evaluations").mock(
        return_value=httpx.Response(200, json={"results": _PASSING_ROWS, "n_examples": 12})
    )
    with pytest.raises(RemoteEvaluationError):
        adapter.evaluate(_DATASET_PATH)


@respx.mock
def test_evaluate_REFUSES_a_row_whose_verdict_contradicts_its_score(
    adapter: RemoteEvaluationAdapter,
) -> None:
    """A row claiming PASS below its own bar is the failure a trusted flag always hides."""
    rows = [{"metric": "discrepancy_recall", "score": 0.41, "threshold": 0.9, "passed": True}]
    respx.post(f"{_BASE_URL}/v1/evaluations").mock(
        return_value=httpx.Response(200, json=_eval_body(run_id="run-fictional-0003", results=rows))
    )
    with pytest.raises(RemoteEvaluationError):
        adapter.evaluate(_DATASET_PATH)


@respx.mock
def test_gate_posts_to_gate_endpoint_and_returns_true_on_a_full_decision(
    adapter: RemoteEvaluationAdapter,
) -> None:
    route = respx.post(f"{_BASE_URL}/v1/gate").mock(
        return_value=httpx.Response(200, json=_gate_body(passed=True, results=_PASSING_ROWS))
    )

    passed = adapter.gate(_DATASET_PATH)

    assert route.called
    sent = json.loads(respx.calls.last.request.content)
    assert sent["target"]["dataset_id"] == _DATASET_ID
    assert sent["dataset_id"] == sent["target"]["dataset_id"]
    assert sent["bundle"] == "doc4-trade-finance"
    _no_metric_names(sent)
    assert passed is True


@respx.mock
def test_gate_returns_false_through_evidence_that_actually_failed(
    adapter: RemoteEvaluationAdapter,
) -> None:
    """A FAIL has to be reached the honest way: a metric that genuinely missed its bar.

    A body claiming ``passed: false`` over evidence where everything passed is a
    contradiction and raises, so this fixture fails the discrepancy-recall row instead.
    """
    respx.post(f"{_BASE_URL}/v1/gate").mock(
        return_value=httpx.Response(200, json=_gate_body(passed=False, results=_FAILING_ROWS))
    )
    assert adapter.gate(_DATASET_PATH) is False


@respx.mock
def test_gate_REFUSES_a_naked_boolean_with_no_evidence(adapter: RemoteEvaluationAdapter) -> None:
    """The shape this file used to accept: a verdict with nothing behind it.

    An upstream that answers ``{"passed": true}`` for every target is indistinguishable from
    one that evaluated nothing at all, so the refusal is the contract, not an inconvenience.
    """
    respx.post(f"{_BASE_URL}/v1/gate").mock(return_value=httpx.Response(200, json={"passed": True}))
    with pytest.raises(RemoteEvaluationError):
        adapter.gate(_DATASET_PATH)


@respx.mock
def test_gate_REFUSES_an_unattested_report_even_when_every_metric_passes(
    adapter: RemoteEvaluationAdapter,
) -> None:
    """Unattested scores are a draft run, not sign-off, however good the numbers look."""
    respx.post(f"{_BASE_URL}/v1/gate").mock(
        return_value=httpx.Response(
            200, json=_gate_body(passed=True, results=_PASSING_ROWS, attested=False)
        )
    )
    with pytest.raises(RemoteEvaluationError):
        adapter.gate(_DATASET_PATH)


@respx.mock
def test_gate_REFUSES_a_redteam_aggregate_that_contradicts_its_rows(
    adapter: RemoteEvaluationAdapter,
) -> None:
    """A red-team summary reporting PASS over a case that was not blocked is a rubber stamp."""
    body = _gate_body(passed=True, results=_PASSING_ROWS)
    body["redteam_report"] = {
        "passed": True,
        "results": [
            {"case": "prompt-injection-01", "passed": True, "blocked": True},
            {"case": "pii-exfil-01", "passed": False, "blocked": False},
        ],
    }
    respx.post(f"{_BASE_URL}/v1/gate").mock(return_value=httpx.Response(200, json=body))
    with pytest.raises(RemoteEvaluationError):
        adapter.gate(_DATASET_PATH)


@respx.mock
def test_gate_REFUSES_a_decision_with_no_mrm_evidence_reference(
    adapter: RemoteEvaluationAdapter,
) -> None:
    """Model-risk sign-off has to point at something durable, or it points at nothing."""
    body = _gate_body(passed=True, results=_PASSING_ROWS)
    body["mrm_evidence_ref"] = ""
    respx.post(f"{_BASE_URL}/v1/gate").mock(return_value=httpx.Response(200, json=body))
    with pytest.raises(RemoteEvaluationError):
        adapter.gate(_DATASET_PATH)


@respx.mock
def test_non_2xx_raises_remote_evaluation_error(adapter: RemoteEvaluationAdapter) -> None:
    respx.post(f"{_BASE_URL}/v1/evaluations").mock(
        return_value=httpx.Response(422, text="dataset_id divergence")
    )
    with pytest.raises(RemoteEvaluationError):
        adapter.evaluate(_DATASET_PATH)
