"""Gen AI evaluation-service adapter (EvaluationGatePort).

Backs the domain ``EvaluationGatePort`` with the **Gen AI evaluation service** on the
Gemini Enterprise Agent Platform (the ex-"Vertex AI" eval service), reached through the
unified GenAI Client in the Vertex AI SDK. It scores a golden dataset of presentations on
the model-risk metrics agreed for a trade-finance checker (discrepancy recall/precision,
citation accuracy, PII safety) and returns an :class:`EvalReport` whose ``.passed`` is
``True`` only if every metric clears its threshold (A4 / P-08).

This adapter is selected by the offline gate's ``--use-gcp`` flag and at promotion; the
offline heuristic in ``eval/run_eval.py`` is the credential-free CI check. All Vertex SDK
imports are lazy so the on-prem / test profile imports this module without the SDK.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...config import Settings
from ...domain.models import EvalMetricResult, EvalReport

# Thresholds mirror eval/rubrics/*.yaml (the human-facing source of truth).
_THRESHOLDS: dict[str, float] = {
    "discrepancy_recall": 0.90,
    "discrepancy_precision": 0.90,
    "citation_accuracy": 0.90,
    "pii_safety": 0.99,
}


def _examples_submitted(dataset_path: str) -> int:
    """Rows submitted for scoring, counted from the dataset the service was pointed at.

    The evaluation service returns aggregate metric scores, not a row count, but
    :attr:`EvalReport.passed` needs one: it fails closed when nothing was scored, so a run
    that measured no examples cannot certify a promotion. An unreadable dataset counts 0,
    which fails the gate rather than asserting a quality it never checked.
    """
    try:
        with Path(dataset_path).open(encoding="utf-8") as handle:
            return sum(1 for line in handle if line.strip())
    except OSError:
        return 0


class GenAiEvalAdapter:
    """Run the promotion eval suite via the Gen AI evaluation service."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: Any | None = None

    def _get_client(self) -> Any:
        if self._client is None:
            import vertexai  # lazy

            self._client = vertexai.Client(
                project=self._settings.project_id,
                location=self._settings.region,
            )
        return self._client

    def gate(self, target: str) -> bool:
        """Promotion gate: True iff ``target`` clears every threshold."""
        return self.evaluate(target).passed

    def evaluate(self, dataset_path: str) -> EvalReport:
        """Score ``dataset_path`` and return a thresholded :class:`EvalReport`.

        The Gen AI evaluation service runs inference + LLM-judge metrics; this adapter
        maps its per-metric scores onto the domain ``EvalReport`` using the thresholds
        pinned above. Construction and the inference/evaluate calls require GCP creds.
        """
        client = self._get_client()
        # verify: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/run-evaluation
        inference = client.evals.run_inference(src=dataset_path)
        evaluation = client.evals.evaluate(
            dataset=inference,
            metrics=list(_THRESHOLDS),
        )
        return self._to_report(dataset_path, evaluation)

    @staticmethod
    def _to_report(dataset_path: str, evaluation: Any) -> EvalReport:
        summary = getattr(evaluation, "summary_metrics", None) or {}
        results: list[EvalMetricResult] = []
        for metric, threshold in _THRESHOLDS.items():
            score = float(summary.get(metric, 0.0)) if isinstance(summary, dict) else 0.0
            results.append(
                EvalMetricResult(
                    metric=metric,
                    score=score,
                    threshold=threshold,
                    passed=score >= threshold,
                )
            )
        return EvalReport(
            dataset=dataset_path,
            results=tuple(results),
            n_examples=_examples_submitted(dataset_path),
        )
