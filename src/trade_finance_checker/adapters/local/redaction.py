"""Local PII redaction adapter (PIIRedactionPort) : regex de-identification.

The ``local`` profile's stand-in for **Sensitive Data Protection / DLP**: masks the national
identifiers for the configured jurisdiction(s) plus the universal email / phone / bank
account rows (the trade-party PII B4 handles, rule R1) with deterministic regexes, returning
findings. Trade-party PII is removed at the boundary before it reaches a model, a trace span
or the audit sink (P-04). The pattern set is jurisdiction-driven
(``settings.pii.jurisdictions``, default SG/HK/JP/AU) so a non-APAC corridor detects its own
identifiers by config, not a code change (see ``domain/pii_patterns.py``). There is no
Google emulator for DLP, so this path is unconditional and imports no google-cloud package.

Row order comes from the pack and is load-bearing: the ``BANK_ACCOUNT_NUMBER`` catch-all
runs last because its shape subsumes the contiguous JP My Number and AU TFN forms, which
would otherwise be masked under the wrong info type. The pack's module docstring explains
what the checksum-gated rows do and do not buy in this vertical.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from ...config import Settings
from ...domain.models import RedactionFinding, RedactionResult
from ...domain.pii_patterns import patterns_for

#: Digit-run rows that an amount or a tariff code can look like. A trade document is full of
#: both, so a match of one of these rows directly after a currency marker or an HS-code label
#: is left alone: "SGD 90000000" used to reach the model as "SGD [SG_PHONE]", and "HS code
#: 8471300000" as "HS code [BANK_ACCOUNT_NUMBER]". Each prefix is read up to the match only.
_DIGIT_RUN_ROWS: frozenset[str] = frozenset({"PHONE_NUMBER", "SG_PHONE", "BANK_ACCOUNT_NUMBER"})
_NOT_AN_IDENTIFIER_PREFIX = re.compile(
    r"(?:[$€£¥]|\b(?:SGD|USD|HKD|AUD|JPY|EUR|GBP|CNY|RMB)|\bHS(?:\s+code)?:?)\s?$",
    re.IGNORECASE,
)


def _mask(
    pattern: re.Pattern[str],
    info_type: str,
    validator: Callable[[str], bool] | None,
    text: str,
) -> tuple[str, int]:
    """Mask the matches of ``pattern`` in ``text`` that are identifiers; count them.

    A checksum-gated row masks only the matches that pass its ``validator``; a digit-run row
    skips a match that is an amount or an HS code by its prefix (see above).
    """
    count = 0

    def _repl(match: re.Match[str]) -> str:
        nonlocal count
        if validator is not None and not validator(match.group(0)):
            return match.group(0)
        if info_type in _DIGIT_RUN_ROWS and _NOT_AN_IDENTIFIER_PREFIX.search(
            match.string, 0, match.start()
        ):
            return match.group(0)
        count += 1
        return f"[{info_type}]"

    return pattern.sub(_repl, text), count


class LocalRegexRedactionAdapter:
    """Mask the configured jurisdictions' national ids + email/phone/account, like DLP."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._patterns = patterns_for(settings.pii.jurisdictions)

    def redact(self, text: str) -> RedactionResult:
        findings: list[RedactionFinding] = []
        redacted = text
        for info_type, pattern, validator in self._patterns:
            # Checksum-gated rows report only genuine identifiers under their info type.
            redacted, count = _mask(pattern, info_type, validator, redacted)
            if count:
                findings.append(RedactionFinding(info_type=info_type, count=count))
        return RedactionResult(text=redacted, findings=tuple(findings))
