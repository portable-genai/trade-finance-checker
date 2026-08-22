"""Safety ports : the A1 Guardrail Gateway concerns, expressed as interfaces.

Primary GCP adapters: **Model Armor** (prompt-injection / jailbreak / RAI / malicious
URL screening via ``sanitizeUserPrompt`` / ``sanitizeModelResponse`` on the regional
host) and **Sensitive Data Protection / DLP** (``deidentifyContent``) for GA-grade PII
redaction before any model call or audit write (P-04, minimise data to the model).

B4 handles trade-party PII (beneficiary, applicant, account numbers), so rule **R1**
applies: the full A1 pipeline (redact then guardrail INPUT, then guardrail OUTPUT)
runs on every check. Two interchangeable adapters sit behind each port: a *direct-GCP*
adapter (so the checker runs standalone) and a *remote-platform* client that delegates
to the ``agent-guardrail-gateway`` service when deployed inside the full platform.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import Direction, GuardrailVerdict, RedactionResult


@runtime_checkable
class GuardrailPort(Protocol):
    def screen(self, text: str, direction: Direction) -> GuardrailVerdict:
        """Screen inbound prompt or outbound response; may sanitise in place."""
        ...


@runtime_checkable
class PIIRedactionPort(Protocol):
    def redact(self, text: str) -> RedactionResult:
        """De-identify PII so the result is safe to send to a model or audit sink."""
        ...
