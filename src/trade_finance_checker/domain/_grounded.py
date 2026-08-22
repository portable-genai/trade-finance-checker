"""Shared LLM-narrative helper (private to the domain layer).

The check pipeline calls the LLM exactly once, to draft the examiner narrative for a
report whose verdict and discrepancy set were already decided deterministically. This
module factors out that machinery : rendering the findings into the prompt context,
building the structured-output ``LlmRequest``, defensively parsing the JSON reply, and a
deterministic fallback narrative when the model is unavailable or returns nothing usable.

It is ``_``-prefixed and not part of the public domain API. Pure domain code : talks only
to models, no Google Cloud / ADK imports.
"""

from __future__ import annotations

import json
from typing import Any

from .models import (
    ComplianceVerdict,
    Discrepancy,
    LetterOfCredit,
    LlmMessage,
    LlmRequest,
    LlmResponse,
    ThinkingLevel,
)
from .prompts import FINDING_BLOCK


def render_findings(discrepancies: tuple[Discrepancy, ...]) -> str:
    """Render detected discrepancies into the findings context block for the prompt.

    Each line names the kind, document, field, expected/found, severity and the UCP600
    article so the model can echo the article reference exactly and never invent one.
    """
    if not discrepancies:
        return "(no discrepancies were detected)"
    lines: list[str] = []
    for disc in discrepancies:
        lines.append(
            FINDING_BLOCK.format(
                kind=disc.kind.value,
                doc_type=disc.doc_type.value,
                field=disc.field,
                expected=disc.expected,
                found=disc.found,
                severity=disc.severity.value,
                ucp600_article=disc.ucp600_article,
            )
        )
    return "\n".join(lines)


def parse_structured(response: LlmResponse) -> dict[str, Any]:
    """Parse an LLM structured-output response into a dict, defensively.

    The GCP adapter returns the structured JSON as ``LlmResponse.text`` when a
    ``response_schema`` is set. We ``json.loads`` it; on any failure (plain text,
    truncation, a fenced block) we fall back to extracting the first balanced JSON
    object, and finally to an empty dict so callers degrade gracefully rather than
    raising on a malformed model reply.
    """
    text = (response.text or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {"items": parsed}
    except (json.JSONDecodeError, ValueError):
        pass

    snippet = _extract_json_object(text)
    if snippet is not None:
        try:
            parsed = json.loads(snippet)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass
    return {}


def _extract_json_object(text: str) -> str | None:
    """Return the first balanced ``{...}`` block in ``text``, or None."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def build_llm_request(
    system_instruction: str,
    user_content: str,
    model: str | None,
    response_schema: dict | None,
    thinking: ThinkingLevel = ThinkingLevel.HIGH,
    temperature: float = 0.2,
    max_output_tokens: int = 4096,
) -> LlmRequest:
    """Assemble an ``LlmRequest`` with a single user message and a system prompt.

    ``model=None`` lets the adapter pick its configured default (the reasoning model,
    ``gemini-3.5-flash``); thinking defaults to HIGH for the examiner narrative.
    """
    return LlmRequest(
        messages=(LlmMessage(role="user", content=user_content),),
        system_instruction=system_instruction,
        model=model,
        thinking=thinking,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        response_schema=response_schema,
    )


def fallback_narrative(
    lc: LetterOfCredit,
    verdict: ComplianceVerdict,
    discrepancies: tuple[Discrepancy, ...],
) -> str:
    """A deterministic narrative used when the LLM is unavailable or returns nothing.

    Keeps the report self-describing without the model, so the report is never
    presentation-less. It restates the deterministic verdict and lists each finding.
    """
    head = f"Letter of Credit {lc.lc_number}: examination result is {verdict.value.upper()}. "
    if not discrepancies:
        return head + (
            "No discrepancies were detected; the presentation appears to comply on its "
            "face, subject to officer review."
        )
    body = "; ".join(
        f"{d.doc_type.value} {d.field}: expected {d.expected}, found {d.found} ({d.ucp600_article})"
        for d in discrepancies
    )
    return head + f"{len(discrepancies)} discrepancy(ies) detected: {body}."


def maybe_record_usage(tracer: Any, response: Any) -> None:
    """Emit token usage to the tracer for FinOps, defensively (never fatal)."""
    try:
        usage = getattr(response, "usage", None)
        model = getattr(response, "model", "") or ""
        if usage is not None and hasattr(tracer, "record_token_usage"):
            tracer.record_token_usage(usage, model)
    except Exception:  # noqa: BLE001 - metrics must never break a generation path
        return


def as_str_list(value: Any) -> list[str]:
    """Coerce an arbitrary model value into a list of stripped non-empty strings."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return []
