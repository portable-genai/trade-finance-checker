"""Generation port : LLM text/reasoning for discrepancy explanation + report prose.

Primary GCP adapter: Gemini models on the Gemini Enterprise Agent Platform
(``gemini-3.5-flash`` for reasoning, ``gemini-3.5-flash`` for triage).

Important: the LLM only **explains** a discrepancy and **drafts** the report
narrative. It never overrides a deterministic discrepancy decision : the verdict and
the discrepancy set are computed by the pure-domain :class:`DiscrepancyDetector`.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import LlmRequest, LlmResponse


@runtime_checkable
class LLMPort(Protocol):
    def generate(self, request: LlmRequest) -> LlmResponse:
        """Generate a completion for ``request`` using the configured model."""
        ...

    def classify(self, text: str, labels: list[str]) -> str:
        """Cheap single-label classification (triage/routing tier model)."""
        ...
