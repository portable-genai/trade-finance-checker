"""Local LLM adapter (LLMPort) : a deterministic, schema-driven generator.

The ``local`` profile's stand-in for **Gemini**: no model, no network, fully
reproducible. It reads ``request.response_schema`` (the JSON schema the calling service
asks for) and emits a deterministic JSON object whose keys match it. The B4 check service
asks for a flat ``{narrative, cited_articles}`` object to draft the examiner narrative;
the adapter inspects the declared properties and emits exactly those fields, so it stays
correct if the schema changes. There is no Google emulator for Gemini, so this path is
unconditional.

The schema-driven ``FakeLLM`` is a real, registered adapter rather than a test fixture, so
the in-memory implementation lives once under ``adapters/local`` and drives both the offline
tests and the CLI. The
LLM only drafts prose; it can never override the deterministic verdict or discrepancy set.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ...config import Settings
from ...domain.models import LlmRequest, LlmResponse, TokenUsage

# Recover the UCP600 article references the prompt's findings block names so the drafted
# narrative cites only governed articles actually in play, never an invented one.
_ARTICLE_RE = re.compile(r"UCP600 Art\.\s*\d+[A-Za-z]?")


def _schema_properties(schema: dict | None) -> dict[str, Any]:
    if not schema:
        return {}
    props = schema.get("properties")
    return props if isinstance(props, dict) else {}


class LocalDeterministicLLMAdapter:
    """Deterministic LLM whose ``generate`` returns JSON matching the request schema."""

    REASONING_MODEL = "gemini-3.5-flash"
    TRIAGE_MODEL = "gemini-3.5-flash"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._reasoning_model = settings.models.reasoning or self.REASONING_MODEL
        self._triage_model = settings.models.triage or self.TRIAGE_MODEL

    # ------------------------------------------------------------------ #
    # LLMPort
    # ------------------------------------------------------------------ #
    def generate(self, request: LlmRequest) -> LlmResponse:
        articles = self._articles_from_request(request)
        body = self._body_for_schema(request.response_schema, articles)
        return LlmResponse(
            text=json.dumps(body),
            usage=TokenUsage(input_tokens=128, output_tokens=64, thinking_tokens=32),
            model=request.model or self._reasoning_model,
            raw=body,
        )

    def classify(self, text: str, labels: list[str]) -> str:
        # Deterministic triage: first label (the service only uses this for routing).
        return labels[0] if labels else ""

    # ------------------------------------------------------------------ #
    # Schema-driven body
    # ------------------------------------------------------------------ #
    def _articles_from_request(self, request: LlmRequest) -> list[str]:
        user = ""
        for message in reversed(request.messages):
            if message.role == "user":
                user = message.content
                break
        seen: list[str] = []
        for art in _ARTICLE_RE.findall(user):
            normalised = re.sub(r"\s+", " ", art).strip()
            if normalised not in seen:
                seen.append(normalised)
        return seen

    def _flat_field(self, name: str, articles: list[str]) -> Any:
        return {
            "narrative": (
                "Examiner narrative drafted from the deterministic findings; the verdict "
                "and discrepancy set are decided by the detector, not this prose."
            ),
            "cited_articles": list(articles),
        }.get(name, "")

    def _body_for_schema(self, schema: dict | None, articles: list[str]) -> dict[str, Any]:
        props = _schema_properties(schema)
        if not props:
            return {
                "narrative": self._flat_field("narrative", articles),
                "cited_articles": list(articles),
            }
        return {name: self._flat_field(name, articles) for name in props}
