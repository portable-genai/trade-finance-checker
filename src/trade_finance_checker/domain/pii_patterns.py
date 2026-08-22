"""Jurisdiction-driven PII pattern packs (the compliance-pack PII axis).

The redact-before-everything boundary (R1, P-04) and the eval gate's ``pii_safety`` metric
both need to know what a trade party's identifier LOOKS like, and that is
jurisdiction-specific: an exporter in Japan carries a My Number, one in Australia a TFN, one
in Singapore an NRIC, one in Hong Kong an HKID. Keeping the patterns here (pure stdlib) and
selecting by jurisdiction means a fork changes a config list, not code, and its
``pii_safety`` gate actually exercises its own identifiers instead of being falsely green.
B4's counterparties are APAC, so the SG / HK / JP / AU packs are the default.

Add a jurisdiction by adding a ``(info_type, regex, validator)`` row to
:data:`NATIONAL_ID_PATTERNS`. ``EMAIL``, ``PHONE`` and ``BANK_ACCOUNT_NUMBER`` are universal
and always applied: B4's PII is the trade parties themselves (beneficiary, applicant,
consignee, notify party) and the **account numbers** they settle through, so a bank account
number is first-class PII for this vertical rather than an extra (see ``ports/safety.py``
and ``_PII_FIELD_KEYS`` in ``domain/trade_check_service.py``).

Ordering is load-bearing, and differs from the sibling verticals
--------------------------------------------------------------
:func:`patterns_for` returns the rows in the order the redactor applies them, and the
``BANK_ACCOUNT_NUMBER`` row is deliberately LAST. It matches any contiguous 9-17 digit run,
which SUBSUMES the contiguous forms of both checksum-gated national ids (JP My Number is 12
digits, AU TFN is 9). Applied first it would mask a My Number as a bank account, so the
national-id rows run ahead of it and the account row takes only what is left over.

That subsumption also means the checksum validators buy something DIFFERENT here than in the
credit-memo assistant this pack is modelled on. There, the checksums stop a filing's bare
digit runs (facility amounts, invoice references) being masked out of the text the model
reasons over. Here they cannot: an unvalidated 9-digit run is not masked as an ``AU_TFN``
but is still masked as a ``BANK_ACCOUNT_NUMBER``, because for a trade-finance boundary that
IS what a bare account-shaped digit run is assumed to be. What the checksum-gated rows buy
in this repo is (a) the correct info type in the findings a reviewer reads, and (b) the
GROUPED forms (``123 456 782``, ``1234 5678 9018``), which the account row cannot see at
all and nothing else would mask. So this vertical masks strictly more than its siblings, on
purpose: over-redaction costs a figure in a narration, under-redaction leaks a trade party's
identifier.

That second point is why the JP row mirrors ``onprem-dlp`` verbatim rather than
narrowed to ``\\b\\d{12}\\b`` as the sibling verticals' packs have it. A bare ``\\b\\d{12}\\b``
misses ``1234 5678 9018``, the form a My Number card is actually printed in, and because the
eval gate scores its leak check off THESE SAME rows, a spaced My Number would be neither
masked nor detected: a vacuous 1.0. The siblings share that hole and should inherit this
row.

The residual, stated rather than hidden: a presentation figure of nine or more digits
without decimal places (``facility 250000000``) is masked. That is pre-existing B4
behaviour, not something this pack introduced, and it is pinned by
``tests/unit/test_redaction_service.py`` so a future reader meets it as a decision instead of
a surprise. ``onprem-dlp`` cuts this class of over-match with ``require_context``
hotwords; adopting that would change the SHARED pack every vertical's redactor and eval gate
score off, so it belongs in one cross-repo change rather than this rollout.

Each row is a 3-tuple ``(info_type, re.Pattern, validator | None)``; ``validator`` (when
present) is a ``str -> bool`` predicate applied to each raw match, so both the redactor and
the eval leak-check mask/detect a match only when it is a genuine identifier.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable

#: A single redaction rule: an info type, the regex that finds it, and an optional
#: checksum validator applied to each raw match before it is treated as a real identifier.
Pattern = tuple[str, re.Pattern[str], Callable[[str], bool] | None]


def hk_hkid_valid(value: str) -> bool:
    """Validate a Hong Kong Identity Card number: prefix + 6 digits + check character.

    Mirrors ``onprem-dlp`` (``onprem_dlp.domain.recognizers.hk_hkid_valid``). Only
    the BARE form needs this: ``A123456(3)`` is unambiguous and is masked on shape alone,
    but the keyed form ``A1234563`` has the same shape as a trade document reference
    (``BL1234567``), so it is masked only when the check character actually computes.
    """
    m = re.fullmatch(r"([A-Z]{1,2})(\d{6})\(?([0-9A])\)?", value.upper())
    if not m:
        return False
    prefix, digits, check = m.groups()
    vals = [36, ord(prefix) - 55] if len(prefix) == 1 else [ord(c) - 55 for c in prefix]
    vals.extend(int(c) for c in digits)
    s = sum(v * w for v, w in zip(vals, range(9, 1, -1), strict=True))
    r = (11 - s % 11) % 11
    return check == ("A" if r == 10 else str(r))


def jp_my_number_valid(value: str) -> bool:
    """Validate a Japanese Individual Number (My Number): 12 digits + check digit.

    Mirrors ``onprem-dlp`` (``onprem_dlp.domain.recognizers.jp_my_number_valid``),
    the catalog's authority on these recognizers, so a 12-digit run is reported as a My
    Number only when it genuinely is one and not an account or reference number. The check
    digit is computed over the first 11 digits.

    Separators are stripped with ``[\\s-]``, not the authority's ``[ -]``, because this
    pack's rows admit ``[\\s-]`` as a separator. Any mismatch there is a silent leak: a
    match the regex accepts but the validator cannot normalise fails ``isdigit()``, so it is
    neither masked nor (since the eval scores off these same rows) detected.
    """
    digits = re.sub(r"[\s-]", "", value)
    if not digits.isdigit() or len(digits) != 12:
        return False
    if len(set(digits)) == 1:
        return False  # an all-identical run is not a real My Number
    s = 0
    for n in range(1, 12):
        p = int(digits[11 - n])  # P_n: nth digit from the right of the first 11
        q = n + 1 if n <= 6 else n - 5
        s += p * q
    r = s % 11
    return int(digits[11]) == (0 if r <= 1 else 11 - r)


def au_tfn_valid(value: str) -> bool:
    """Validate an Australian Tax File Number: 9 digits, weighted checksum mod 11.

    Mirrors ``onprem-dlp`` (``onprem_dlp.domain.recognizers.au_tfn_valid``). Note
    the module docstring: a contiguous 9-digit run that fails this check is still masked by
    the ``BANK_ACCOUNT_NUMBER`` row, so what this validator decides is the info type a
    reviewer sees, plus whether the spaced ``123 456 782`` form is caught at all.

    Separators are stripped with ``[\\s-]`` rather than the authority's ``[ -]`` because
    this row's regex admits ``[\\s-]``. See :func:`jp_my_number_valid`: a TFN separated by a
    non-breaking space (which PDF text extraction routinely emits, and this redactor runs
    over parser output) would otherwise match the regex, fail the validator, and leak
    undetected.
    """
    digits = re.sub(r"[\s-]", "", value)
    if not digits.isdigit() or len(digits) != 9:
        return False
    weights = (1, 4, 3, 7, 5, 8, 6, 9, 10)
    # strict: the length check above pins digits to exactly the 9 weights.
    return sum(int(d) * w for d, w in zip(digits, weights, strict=True)) % 11 == 0


# Universal PII, applied for every jurisdiction.
_EMAIL: Pattern = (
    "EMAIL_ADDRESS",
    re.compile(r"\b[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}\b"),
    None,
)
_PHONE_INTL: Pattern = (
    "PHONE_NUMBER",
    re.compile(r"\+\d{1,3}[\s-]?\d(?:[\s-]?\d){6,13}\b"),
    None,
)
#: Trade-settlement account numbers: B4's own PII, not a bonus. Applied LAST because the
#: shape subsumes the contiguous JP / AU national-id forms (see the module docstring).
_BANK_ACCOUNT: Pattern = (
    "BANK_ACCOUNT_NUMBER",
    re.compile(r"\b\d{9,17}\b"),
    None,
)

#: Per-jurisdiction national-identifier patterns (ISO-3166 alpha-2 -> list of rows).
NATIONAL_ID_PATTERNS: dict[str, list[Pattern]] = {
    "SG": [
        # Case-insensitive, like the onprem-dlp recognizer: a lower-cased NRIC typed
        # into a free-text field is an NRIC, and an upper-only row would neither mask nor
        # detect it. No checksum: the shape does not collide with ordinary text, and recall
        # at the boundary is worth more than checksum precision.
        ("SG_NRIC_FIN", re.compile(r"\b[STFGMstfgm]\d{7}[A-Za-z]\b"), None),
        ("SG_PHONE", re.compile(r"\b(?:\+?65[\s-]?)?[689]\d{3}[\s-]?\d{4}\b"), None),
    ],
    "HK": [
        # Two rows, because the two forms carry different risks. The parenthesised form is
        # unambiguous, so it is masked on shape (any HKID, even one whose check character is
        # mistyped). The bare keyed form collides with trade document references
        # (``BL1234567`` has the identical shape), so it is checksum-gated instead of either
        # leaking or eating every B/L number.
        ("HK_HKID", re.compile(r"\b[A-Z]{1,2}\d{6}\([0-9A]\)"), None),
        ("HK_HKID", re.compile(r"\b[A-Z]{1,2}\d{6}[0-9A]\b"), hk_hkid_valid),
    ],
    "JP": [
        # Checksum-gated so a genuine My Number is reported as one; a 12-digit run that
        # fails the check is an account/reference number and the account row masks it.
        # The 4-4-4 grouping is the form a My Number card is printed in, and the account
        # row cannot see it, so this row is what covers it. The leading lookarounds also
        # reject a 12-digit prefix of a longer grouped run (e.g. the first 12 digits of a
        # 16-digit card PAN, which can pass the My Number checksum by chance). Both come
        # from the onprem-dlp recognizer this row mirrors.
        (
            "JP_MY_NUMBER",
            re.compile(r"(?<!\d)(?<!\d[- ])\d{4}[- ]?\d{4}[- ]?\d{4}(?![- ]?\d)"),
            jp_my_number_valid,
        ),
    ],
    "AU": [
        # Likewise a 9-digit run. The gate also decides whether the SPACED form is caught:
        # the account row only sees contiguous digits.
        ("AU_TFN", re.compile(r"\b\d{3}[\s-]?\d{3}[\s-]?\d{3}\b"), au_tfn_valid),
    ],
    "IN": [
        ("IN_PAN", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), None),
        ("IN_AADHAAR", re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"), None),
    ],
    "GB": [
        # National Insurance number (prefix rules simplified to a safe superset).
        ("GB_NINO", re.compile(r"\b[A-CEGHJ-PR-TW-Z]{2}\d{6}[A-D]\b"), None),
    ],
}

#: Reference default: B4's APAC trade corridors.
DEFAULT_JURISDICTIONS: tuple[str, ...] = ("SG", "HK", "JP", "AU")


#: RE2-safe equivalents, by info type, for rows whose Python regex uses syntax RE2 rejects.
#: Google Cloud DLP custom info types are matched with RE2, which has no lookaround, so the
#: JP row's lookarounds make DLP reject the whole inspect config with INVALID_ARGUMENT: the
#: managed profile would fail on every call rather than degrade. RE2 supports ``\b``, which
#: still rejects a 12-digit prefix of a longer CONTIGUOUS run; what is lost is only the
#: rejection of a 12-digit prefix of a longer GROUPED run, which merely masks more. That is
#: the same fail-safe direction as the missing checksum (see the DLP adapter's docstring),
#: and both live here so the two forms of a row cannot drift apart.
_RE2_OVERRIDES: dict[str, str] = {
    "JP_MY_NUMBER": r"\b\d{4}[- ]?\d{4}[- ]?\d{4}\b",
}


def re2_pattern_for(info_type: str, pattern: re.Pattern[str]) -> str:
    """The RE2-compatible source for a row, for consumers that cannot run Python regex."""
    return _RE2_OVERRIDES.get(info_type, pattern.pattern)


def patterns_for(jurisdictions: Iterable[str]) -> list[Pattern]:
    """The redaction rows for ``jurisdictions``, in the order they must be applied.

    Universal email/phone first, then each jurisdiction's national ids, then the
    ``BANK_ACCOUNT_NUMBER`` catch-all last so it takes only the digit runs the
    checksum-gated national-id rows left behind (see the module docstring).

    Unknown jurisdiction codes contribute no national-ID pattern (the universal rows still
    apply), so a partially-configured fork degrades safely rather than raising.

    De-duplication is keyed on the (info type, regex) pair, not the info type alone: two
    jurisdictions may legitimately share a row, but one jurisdiction may also carry the SAME
    info type under two shapes (HK's parenthesised and bare HKID forms), and keying on the
    name alone would silently drop the second.
    """
    national: list[Pattern] = []
    seen: set[tuple[str, str]] = {
        (row[0], row[1].pattern) for row in (_EMAIL, _PHONE_INTL, _BANK_ACCOUNT)
    }
    for code in jurisdictions:
        for row in NATIONAL_ID_PATTERNS.get((code or "").upper(), ()):
            key = (row[0], row[1].pattern)
            if key not in seen:
                national.append(row)
                seen.add(key)
    return [_EMAIL, _PHONE_INTL, *national, _BANK_ACCOUNT]
