"""Model Armor guardrail adapter (A1 Guardrail Gateway, primary GCP backend).

Implements :class:`GuardrailPort` against **Model Armor**, the runtime AI-safety service of
the Gemini Enterprise Agent Platform. Inbound prompts are screened with
``:sanitizeUserPrompt`` and outbound model responses with ``:sanitizeModelResponse`` on the
regional endpoint ``modelarmor.asia-southeast1.rep.googleapis.com`` so all screening stays
inside Singapore for Transaction Banking data residency.

The adapter parses ``sanitizationResult.filterResults`` : the prompt-injection / jailbreak,
Sensitive Data Protection (SDP), malicious-URI and Responsible-AI (RAI) filters : into
:class:`GuardrailFinding` records.

FAIL CLOSED. The verdict is ALLOWED only when ``sanitizationResult.filterMatchState`` is
``NO_MATCH_FOUND`` AND ``sanitizationResult.invocationResult`` is ``SUCCESS``. Everything
else blocks: ``MATCH_FOUND``; ``FILTER_MATCH_STATE_UNSPECIFIED``; a missing or empty
``sanitizationResult``; and ``NO_MATCH_FOUND`` from a screen whose ``invocationResult`` is
``PARTIAL`` (some filters skipped or failed), ``FAILURE`` (all of them did), unspecified or
absent. A skipped filter reports no match, so "no match" from a screen that did not run is
refused rather than passed: padding a prompt past the prompt-injection filter's token limit
must not get it through unscreened. The REST call carries a deadline, and an HTTP error or
timeout propagates to the caller rather than becoming a verdict.

All Google Cloud / auth SDK imports are lazy (inside ``__init__`` / methods) so the on-prem
and test profiles import this module with no GCP SDK installed.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ...domain.models import (
    Direction,
    GuardrailCategory,
    GuardrailFinding,
    GuardrailVerdict,
)

_MATCH_FOUND = "MATCH_FOUND"
_NO_MATCH_FOUND = "NO_MATCH_FOUND"
_SUCCESS = "SUCCESS"
# The deadline on every sanitize call; a timeout raises, it never becomes an allow.
_TIMEOUT_SECONDS = 30.0

# RAI sub-type key (as returned by Model Armor) -> domain GuardrailCategory.
_RAI_CATEGORY: dict[str, GuardrailCategory] = {
    "hate_speech": GuardrailCategory.HATE,
    "harassment": GuardrailCategory.HARASSMENT,
    "sexually_explicit": GuardrailCategory.SEXUAL,
    "dangerous": GuardrailCategory.DANGEROUS,
}


class ModelArmorGuardrailAdapter:
    """Screen prompts and responses through Model Armor's REST API."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._armor = settings.model_armor
        self._project = settings.project_id
        self._region = settings.region
        # httpx and google-auth are resolved lazily on first screen() call.
        self._client: Any | None = None
        self._credentials: Any | None = None
        self._auth_request: Any | None = None

    # -- public API -------------------------------------------------------- #
    def screen(self, text: str, direction: Direction) -> GuardrailVerdict:
        """Screen ``text`` and return a verdict. Raises if Model Armor cannot answer."""
        verb = "sanitizeUserPrompt" if direction is Direction.INPUT else "sanitizeModelResponse"
        payload = self._build_payload(text, direction)
        url = (
            f"https://{self._armor.host}/v1/projects/{self._project}"
            f"/locations/{self._region}/templates/{self._armor.template_id}:{verb}"
        )
        response = self._post(url, payload)
        return self._parse(response, direction, text)

    # -- request construction ---------------------------------------------- #
    def _build_payload(self, text: str, direction: Direction) -> dict[str, Any]:
        # The request body keys the data object by direction.
        # verify: https://docs.cloud.google.com/model-armor/sanitize-prompts-responses
        if direction is Direction.INPUT:
            return {"userPromptData": {"text": text}}
        return {"modelResponseData": {"text": text}}

    def _post(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        client = self._http_client()
        token = self._bearer_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        resp = client.post(url, json=payload, headers=headers, timeout=_TIMEOUT_SECONDS)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        return data

    def _http_client(self) -> Any:
        import httpx  # lazy

        if self._client is None:
            self._client = httpx.Client()
        return self._client

    def _bearer_token(self) -> str:
        # google.auth.default() yields ADC credentials; refresh via a transport request
        # to mint a short-lived OAuth2 bearer token for the REST call.
        import google.auth  # lazy
        from google.auth.transport.requests import Request  # lazy

        if self._credentials is None:
            self._credentials, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            self._auth_request = Request()
        if not self._credentials.valid:
            self._credentials.refresh(self._auth_request)
        token: str = self._credentials.token
        return token

    # -- response parsing -------------------------------------------------- #
    def _parse(self, response: Any, direction: Direction, original_text: str) -> GuardrailVerdict:
        """Map a sanitize response to a verdict: allowed ONLY on a complete, clean screen."""
        raw = response.get("sanitizationResult") if isinstance(response, dict) else None
        result: dict[str, Any] = raw if isinstance(raw, dict) else {}
        raw_filters = result.get("filterResults")
        filter_results: dict[str, Any] = raw_filters if isinstance(raw_filters, dict) else {}

        findings: list[GuardrailFinding] = []
        findings.extend(self._parse_pi_jailbreak(filter_results))
        findings.extend(self._parse_sensitive_data(filter_results))
        findings.extend(self._parse_malicious_uris(filter_results))
        findings.extend(self._parse_rai(filter_results))

        match_state = result.get("filterMatchState")
        invocation = result.get("invocationResult")
        if match_state == _NO_MATCH_FOUND and invocation == _SUCCESS:
            return GuardrailVerdict(
                allowed=True,
                direction=direction,
                findings=tuple(findings),
                sanitized_text=self._extract_sanitized_text(filter_results, original_text),
                reason="No blocking Model Armor filter matched.",
            )

        if match_state == _MATCH_FOUND:
            reason = self._blocked_reason(findings)
            detail = "Model Armor reported a filter match."
        elif match_state == _NO_MATCH_FOUND:
            reason = "Blocked: Model Armor returned no complete filter decision."
            detail = f"invocationResult={invocation or 'absent'}: not every filter ran."
        else:
            reason = "Blocked: Model Armor returned no usable verdict."
            detail = f"filterMatchState={match_state or 'absent'}: no verdict to act on."
        if not findings:
            findings.append(
                GuardrailFinding(category=GuardrailCategory.OTHER, confidence="high", detail=detail)
            )
        return GuardrailVerdict(
            allowed=False,
            direction=direction,
            findings=tuple(findings),
            sanitized_text=None,
            reason=reason,
        )

    @staticmethod
    def _is_match(node: dict[str, Any] | None) -> bool:
        if not node:
            return False
        return node.get("matchState") == _MATCH_FOUND

    def _parse_pi_jailbreak(self, filter_results: dict[str, Any]) -> list[GuardrailFinding]:
        node = (filter_results.get("pi_and_jailbreak") or {}).get(
            "piAndJailbreakFilterResult"
        ) or {}
        if not self._is_match(node):
            return []
        confidence = str(node.get("confidenceLevel", "")).lower() or "high"
        return [
            GuardrailFinding(
                category=GuardrailCategory.PROMPT_INJECTION,
                confidence=confidence,
                detail="Model Armor prompt-injection / jailbreak filter matched.",
            )
        ]

    def _parse_sensitive_data(self, filter_results: dict[str, Any]) -> list[GuardrailFinding]:
        inspect = (filter_results.get("sdp") or {}).get("sdpFilterResult", {}).get(
            "inspectResult"
        ) or {}
        if not self._is_match(inspect):
            return []
        info_types = sorted(
            {
                str(f.get("infoType", ""))
                for f in (inspect.get("findings") or [])
                if f.get("infoType")
            }
        )
        detail = (
            f"Sensitive data detected: {', '.join(info_types)}."
            if info_types
            else "Model Armor Sensitive Data Protection filter matched."
        )
        return [
            GuardrailFinding(
                category=GuardrailCategory.SENSITIVE_DATA,
                confidence="high",
                detail=detail,
            )
        ]

    def _parse_malicious_uris(self, filter_results: dict[str, Any]) -> list[GuardrailFinding]:
        node = (filter_results.get("malicious_uris") or {}).get("maliciousUriFilterResult")
        if not self._is_match(node):
            return []
        return [
            GuardrailFinding(
                category=GuardrailCategory.MALICIOUS_URL,
                confidence="high",
                detail="Model Armor malicious-URI filter matched.",
            )
        ]

    def _parse_rai(self, filter_results: dict[str, Any]) -> list[GuardrailFinding]:
        rai = (filter_results.get("rai") or {}).get("raiFilterResult") or {}
        if not self._is_match(rai):
            return []
        sub_results = rai.get("raiFilterTypeResults", {}) or {}
        findings: list[GuardrailFinding] = []
        for key, category in _RAI_CATEGORY.items():
            sub = sub_results.get(key) or {}
            if not self._is_match(sub):
                continue
            confidence = str(sub.get("confidenceLevel", "")).lower() or "medium"
            findings.append(
                GuardrailFinding(
                    category=category,
                    confidence=confidence,
                    detail=f"Model Armor Responsible-AI filter matched: {key}.",
                )
            )
        if not findings:
            # RAI matched but no recognised sub-type : record a generic finding.
            findings.append(
                GuardrailFinding(
                    category=GuardrailCategory.OTHER,
                    confidence="medium",
                    detail="Model Armor Responsible-AI filter matched.",
                )
            )
        return findings

    def _extract_sanitized_text(
        self, filter_results: dict[str, Any], original_text: str
    ) -> str | None:
        # When SDP de-identification is configured on the template, Model Armor returns
        # the redacted text under sdp.sdpFilterResult.deidentifyResult.data.
        deidentify = (
            (filter_results.get("sdp") or {}).get("sdpFilterResult", {}).get("deidentifyResult")
        )
        if isinstance(deidentify, dict):
            data = deidentify.get("data") or {}
            text = data.get("text")
            if isinstance(text, str) and text:
                return text
        return original_text

    @staticmethod
    def _blocked_reason(findings: list[GuardrailFinding]) -> str:
        categories = ", ".join(sorted({f.category.value for f in findings}))
        return f"Blocked by Model Armor: {categories}." if categories else "Blocked by Model Armor."
