"""PII redaction adapter tests (the redact-before-everything boundary, R1, P-04).

Prove the jurisdiction-driven local redactor masks B4's APAC national identifiers (SG NRIC,
HK HKID, JP My Number, AU TFN) plus the universal email / phone / bank-account rows; that
the checksum-gated rows report only genuine identifiers; and that an unknown jurisdiction
degrades safely to the universal rows rather than raising. Same pattern source as the eval
gate, so what these tests mask is exactly what the gate detects.

The load-bearing tests for THIS vertical are the ones about the ``BANK_ACCOUNT_NUMBER``
catch-all, because it makes B4 behave differently from the sibling verticals that share this
pack. An account number IS the PII here, so the row matches any contiguous 9-17 digit run
and therefore subsumes the contiguous JP My Number and AU TFN shapes. Two consequences are
pinned below rather than left to be rediscovered: the row order decides which info type a
reviewer sees (``test_national_ids_win_over_the_account_catch_all``), and an ordinary
presentation figure of nine or more digits is masked too
(``test_long_presentation_figures_are_masked_as_accounts``). The second is pre-existing B4
behaviour, not something the jurisdiction pack introduced.
"""

from __future__ import annotations

from trade_finance_checker.adapters.local.redaction import LocalRegexRedactionAdapter
from trade_finance_checker.config import PiiSettings, Settings

# FICTIONAL identifiers. The JP My Number and AU TFN carry VALID check digits; the paired
# "_INVALID" values share the shape but fail the checksum.
_SG_NRIC = "S1234567A"
_HK_HKID = "A123456(3)"
_JP_MYNUMBER_VALID = "123456789018"
_JP_MYNUMBER_INVALID = "123456789012"
_AU_TFN_VALID = "123 456 782"
_AU_TFN_INVALID = "123 456 781"
_EMAIL = "ops@example.com"
_PHONE = "+81 90 1234 5678"


def _redactor(*jurisdictions: str) -> LocalRegexRedactionAdapter:
    return LocalRegexRedactionAdapter(Settings(pii=PiiSettings(jurisdictions=jurisdictions)))


def test_default_jurisdictions_are_the_apac_trade_corridors() -> None:
    # The pack B4 ships with; the eval gate's golden cases mirror exactly these.
    assert Settings().pii.jurisdictions == ("SG", "HK", "JP", "AU")


def test_sg_nric_and_email_and_phone_masked() -> None:
    r = _redactor("SG", "HK", "JP", "AU")
    out = r.redact(f"NRIC {_SG_NRIC}, email {_EMAIL}, phone {_PHONE}")
    assert _SG_NRIC not in out.text
    assert _EMAIL not in out.text
    assert _PHONE not in out.text
    info = {f.info_type for f in out.findings}
    assert {"SG_NRIC_FIN", "EMAIL_ADDRESS", "PHONE_NUMBER"} <= info


def test_hk_hkid_masked_in_both_written_forms() -> None:
    """The parenthesised form on shape, the bare keyed form on its checksum.

    The bare form is the one a database or a keyed field carries, and an upstream pack that
    required the parens masked neither it nor (since the eval reads the same rows) detected
    it. It cannot simply be added on shape though: it collides exactly with a trade document
    reference, which is what the checksum separates.
    """
    r = _redactor("HK")
    for form in (_HK_HKID, "A1234563"):
        out = r.redact(f"HKID {form} on file.")
        assert form not in out.text, form
        assert "HK_HKID" in {f.info_type for f in out.findings}, form


def test_bill_of_lading_reference_is_not_an_hkid() -> None:
    """`BL1234567` has the bare HKID shape; only the checksum keeps it out of the mask."""
    r = _redactor("HK")
    out = r.redact("Presented under BL1234567 and MSKU1234567.")
    assert "BL1234567" in out.text
    assert "HK_HKID" not in {f.info_type for f in out.findings}


def test_sg_nric_masked_case_insensitively() -> None:
    """A lower-cased NRIC is an NRIC; an upper-only row leaks it silently."""
    r = _redactor("SG")
    out = r.redact("nric s1234567a on file.")
    assert "s1234567a" not in out.text
    assert "SG_NRIC_FIN" in {f.info_type for f in out.findings}


def test_bank_account_number_masked() -> None:
    """B4's own PII: the account a presentation settles through (ports/safety.py)."""
    r = _redactor("SG", "HK", "JP", "AU")
    out = r.redact("Settle to account 4455667788 at the advising bank.")
    assert "4455667788" not in out.text
    assert "[BANK_ACCOUNT_NUMBER]" in out.text
    assert "BANK_ACCOUNT_NUMBER" in {f.info_type for f in out.findings}


def test_national_ids_win_over_the_account_catch_all() -> None:
    """Row order is load-bearing: a My Number must not be reported as a bank account.

    The ``BANK_ACCOUNT_NUMBER`` row matches any contiguous 9-17 digit run, which subsumes
    the JP (12-digit) and AU (9-digit) shapes. The pack orders the national ids first so the
    finding a reviewer reads names the identifier that was actually found.
    """
    r = _redactor("JP", "AU")
    out = r.redact(f"My Number {_JP_MYNUMBER_VALID} and TFN 123456782 on file.")
    assert _JP_MYNUMBER_VALID not in out.text
    assert "[JP_MY_NUMBER]" in out.text
    assert "[AU_TFN]" in out.text
    info = {f.info_type for f in out.findings}
    assert {"JP_MY_NUMBER", "AU_TFN"} <= info
    assert "BANK_ACCOUNT_NUMBER" not in info


def test_jp_my_number_checksum_decides_the_info_type_not_the_masking() -> None:
    """A 12-digit run that fails the checksum is an account number, and is masked as one.

    Unlike the sibling verticals, the failing run does NOT survive: B4 treats a bare
    account-shaped digit run as a trade party's account number. The checksum decides what it
    is CALLED, which is what a reviewer acts on.
    """
    r = _redactor("JP")
    valid = r.redact(f"My Number {_JP_MYNUMBER_VALID} on file.")
    assert "[JP_MY_NUMBER]" in valid.text
    assert {"JP_MY_NUMBER"} <= {f.info_type for f in valid.findings}

    invalid = r.redact(f"Remittance reference {_JP_MYNUMBER_INVALID} quoted.")
    assert _JP_MYNUMBER_INVALID not in invalid.text
    assert "[BANK_ACCOUNT_NUMBER]" in invalid.text
    assert {f.info_type for f in invalid.findings} == {"BANK_ACCOUNT_NUMBER"}


def test_jp_my_number_grouped_form_needs_the_jp_row() -> None:
    """The 4-4-4 form a My Number card is printed in; nothing else in the pack sees it.

    The regression behind porting the ``onprem-dlp`` regex verbatim instead of the
    ``\\b\\d{12}\\b`` the sibling packs narrowed it to. The account catch-all only matches
    contiguous digits, so without this row a spaced My Number is masked by nothing, and
    (since the eval leak check reads these same rows) detected by nothing either.
    """
    r = _redactor("SG", "HK", "JP", "AU")
    for grouped in ("1234 5678 9018", "1234-5678-9018"):
        out = r.redact(f"My Number {grouped} on file.")
        assert grouped not in out.text, grouped
        assert "[JP_MY_NUMBER]" in out.text, grouped
        assert "JP_MY_NUMBER" in {f.info_type for f in out.findings}, grouped


def test_jp_row_ignores_a_twelve_digit_prefix_of_a_longer_run() -> None:
    """A 16-digit card PAN is not a My Number, even when its first 12 digits check out.

    The lookarounds carry this, and it is why the row is not simply ``\\d{4}[- ]?...``. The
    PAN is still masked, as the account number shape it is.
    """
    r = _redactor("JP")
    out = r.redact("Card 1234567890181234 on file.")
    assert "1234567890181234" not in out.text
    assert {f.info_type for f in out.findings} == {"BANK_ACCOUNT_NUMBER"}


def test_au_tfn_spaced_form_needs_the_tfn_row() -> None:
    """The account catch-all cannot see a spaced TFN, so the AU row is what covers it.

    The contiguous form would be masked either way; ``123 456 782`` is masked only because
    the AU pack is configured and its checksum passes. A spaced run that fails the checksum
    is not an identifier and no row claims it.
    """
    r = _redactor("AU")
    valid = r.redact(f"TFN {_AU_TFN_VALID} recorded.")
    assert _AU_TFN_VALID not in valid.text
    assert "AU_TFN" in {f.info_type for f in valid.findings}

    invalid = r.redact(f"Invoice {_AU_TFN_INVALID} settled.")
    assert _AU_TFN_INVALID in invalid.text
    assert not invalid.findings


def test_tfn_separated_by_a_non_breaking_space_is_still_masked() -> None:
    """The regex admits any whitespace, so the validator must strip any whitespace.

    A seam between the two is a silent leak, and the realistic one: PDF text extraction
    emits U+00A0 for spaces, and the redactor runs over that parser output
    (``_redact_extract``). A TFN the regex matched but the validator could not normalise
    would be neither masked nor detected.
    """
    r = _redactor("AU")
    for sep in (" ", "\t", " "):
        out = r.redact(f"TFN 123{sep}456{sep}782 recorded.")
        assert "782" not in out.text.split("recorded")[0], repr(sep)
        assert "AU_TFN" in {f.info_type for f in out.findings}, repr(sep)


def test_long_presentation_figures_are_masked_and_labelled() -> None:
    """Long figures are masked, and the finding names what the pack actually decided.

    ``agent/callbacks.py`` redacts the prose the model is about to read, so a large facility
    figure written without decimals is masked out of that prose. Over-redaction is the
    deliberate direction at this boundary (a masked figure degrades a narration, a missed
    identifier leaks a trade party), and the honest fix is context words on the SHARED pack
    rather than a looser rule in one repo. See the note in ``domain/pii_patterns.py``.

    The label is asserted, not merely "something was masked": 250000000 passes the TFN
    checksum by coincidence, so it is reported as an `AU_TFN` rather than as the account
    number a reader would assume. That is the residual the checksum cannot remove, and a
    reviewer sees the surprising label rather than a comfortable one.
    """
    r = _redactor("SG", "HK", "JP", "AU")
    out = r.redact("Facility drawn to 250000000 at year end.")
    assert "250000000" not in out.text
    assert "[AU_TFN]" in out.text
    assert {f.info_type for f in out.findings} == {"AU_TFN"}


def test_presentation_amounts_survive_but_an_eight_digit_integer_part_does_not() -> None:
    """The amounts a presentation actually carries stay intact, with one known exception.

    Ordinary amounts are written with decimals and are shorter than the account shape, so no
    row sees them. The exception is deliberate and pinned rather than discovered later: the
    SG_PHONE row matches an 8-digit run starting 6/8/9, which is exactly the integer part of
    a large JPY amount, so a JPY LC loses its figure from the audited prompt. Over-redaction
    is the accepted direction here, and the fix is context words on the shared pack.
    """
    r = _redactor("SG", "HK", "JP", "AU")
    figures = "Invoice USD 98000.00 against LC 100000.00; net leverage 2.5x, DSCR 1.40x."
    unchanged = r.redact(figures)
    assert unchanged.text == figures
    assert not unchanged.findings

    jpy = r.redact("LC amount JPY 85000000.00 payable at sight.")
    assert "[SG_PHONE]" in jpy.text  # the known collision, not a silent one


def test_iso_dates_are_never_masked() -> None:
    """Dates must survive: the detector's expiry / shipment reasoning is dated.

    Guards the shape of the account row. A hyphen-tolerant variant (the one the DLP adapter
    carries privately) matches ``2026-06-15`` and would strike the dates out of the
    audited prompt.
    """
    r = _redactor("SG", "HK", "JP", "AU")
    dated = "Shipment 2026-06-05, expiry 2026-07-31, presented 2026-06-10."
    out = r.redact(dated)
    assert out.text == dated
    assert not out.findings


def test_all_market_ids_masked_together() -> None:
    r = _redactor("SG", "HK", "JP", "AU")
    out = r.redact(f"{_SG_NRIC} / {_HK_HKID} / {_JP_MYNUMBER_VALID} / {_AU_TFN_VALID} / {_EMAIL}")
    for raw in (_SG_NRIC, _HK_HKID, _JP_MYNUMBER_VALID, _AU_TFN_VALID, _EMAIL):
        assert raw not in out.text
    assert out.redacted


def test_every_dlp_pattern_is_re2_compatible() -> None:
    """DLP matches custom info types with RE2, which has no lookaround.

    A row shipped with a lookaround makes DLP reject the whole inspect config
    (INVALID_ARGUMENT), so the managed profile fails on every call instead of degrading, and
    no SDK-free test would see it. The pack keeps an RE2-safe form per affected row; this
    asserts the DLP adapter only ever emits those. Checked structurally (RE2 rejects exactly
    the Perl operators `(?=`, `(?!`, `(?<=`, `(?<!`) so the test needs no RE2 dependency.
    """
    from trade_finance_checker.adapters.gcp.dlp_redaction import DlpRedactionAdapter

    forbidden = ("(?=", "(?!", "(?<=", "(?<!")
    for market in (*Settings().pii.jurisdictions, "IN", "GB"):
        adapter = DlpRedactionAdapter(Settings(pii=PiiSettings(jurisdictions=(market,))))
        for custom in adapter._custom_info_types():
            pattern = custom["regex"]["pattern"]
            name = custom["info_type"]["name"]
            assert not any(op in pattern for op in forbidden), f"{market}/{name}: {pattern}"


def test_re2_pattern_falls_back_to_the_row_itself() -> None:
    """Only rows that need an override carry one, so the two forms cannot drift silently."""
    from trade_finance_checker.domain.pii_patterns import NATIONAL_ID_PATTERNS, re2_pattern_for

    info_type, pattern, _ = NATIONAL_ID_PATTERNS["SG"][0]
    assert re2_pattern_for(info_type, pattern) == pattern.pattern

    jp_type, jp_pattern, _ = NATIONAL_ID_PATTERNS["JP"][0]
    assert re2_pattern_for(jp_type, jp_pattern) != jp_pattern.pattern  # lookarounds dropped


def test_unknown_jurisdiction_degrades_to_the_universal_rows_only() -> None:
    r = _redactor("XX")  # unknown ISO code: no national-id pack, universal PII still applies
    out = r.redact(f"NRIC {_SG_NRIC}, email {_EMAIL}")
    # The national id survives (its pack was not configured) ...
    assert _SG_NRIC in out.text
    # ... but the universal email is still masked, and the adapter never raises.
    assert _EMAIL not in out.text
    assert {f.info_type for f in out.findings} == {"EMAIL_ADDRESS"}
