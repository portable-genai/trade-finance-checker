"""DiscrepancyDetector : the deterministic heart of the trade-finance checker.

This module is the reason B4 is trustworthy: the verdict and the discrepancy set are
computed by **pure, deterministic** code over the parsed LC and the extracted document
fields, never by the LLM. The LLM only explains and drafts prose (see ``llm`` in the
service); it can never invent, suppress, or override a discrepancy decided here.

The detector runs two families of check:

1. **LC-vs-document checks** (no UCP600 rule set needed): the presented invoice amount
   does not exceed the LC amount, currencies match, the shipment date is on or before
   ``latest_shipment``, the presentation is within ``expiry_date``, the goods
   description is consistent across documents, and every required document is present.
2. **UCP600-article-tagged checks**: each finding is tagged with the UCP600 article it
   breaches (Art. 18 commercial invoice, Art. 14 examination/date, Art. 6 expiry, etc.)
   using the governed rule set retrieved via A2 so the article references are governed
   rather than hard-coded.

Every discrepancy carries the citations (LC term / UCP600 article / document) that back
it (P-07). Pure domain code : only models, no Google Cloud / framework imports.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from .models import (
    Citation,
    CitationType,
    Discrepancy,
    DiscrepancyKind,
    DocumentExtract,
    LetterOfCredit,
    Severity,
    TradeDocType,
    Ucp600Rule,
)

# UCP600 article references used by the deterministic checks. These are the articles a
# trade-finance examiner maps each discrepancy kind to; the governed rule set (A2) is
# used to enrich the citation with the article title/url when available.
_ART_EXPIRY = "UCP600 Art. 6"  # availability, expiry date and place for presentation
_ART_EXAMINATION = "UCP600 Art. 14"  # standard for examination of documents
_ART_INVOICE = "UCP600 Art. 18"  # commercial invoice (amount, currency, description)
_ART_TRANSPORT = "UCP600 Art. 19"  # transport documents (shipment date)
_ART_INSURANCE = "UCP600 Art. 28"  # insurance document and coverage

#: Documents an examiner expects in a standard CIF/CIP presentation unless the LC
#: explicitly lists a different set under the ``documents_required`` term.
_DEFAULT_REQUIRED_DOCS: tuple[TradeDocType, ...] = (
    TradeDocType.INVOICE,
    TradeDocType.BILL_OF_LADING,
)

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_NUM_RE = re.compile(r"[-+]?\d[\d,]*\.?\d*")
_WORD_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset({"the", "and", "of", "a", "an", "for", "to", "in", "with", "as", "per"})


def _parse_date(value: str | None) -> date | None:
    """Parse an ISO-ish date string into a ``date``, or ``None`` if unparseable."""
    if not value:
        return None
    match = _DATE_RE.search(value)
    if not match:
        return None
    try:
        y, m, d = (int(part) for part in match.group(0).split("-"))
        return date(y, m, d)
    except (ValueError, TypeError):
        return None


def _parse_amount(value: str | None) -> float | None:
    """Parse a money amount (tolerating thousands separators) into a float."""
    if value is None:
        return None
    match = _NUM_RE.search(str(value))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def _tokens(text: str | None) -> set[str]:
    """Lower-case content tokens of ``text`` with trivial stopwords removed."""
    if not text:
        return set()
    return {w for w in _WORD_RE.findall(text.lower()) if w not in _STOPWORDS}


def _overlap(a: str | None, b: str | None) -> float:
    """Jaccard-style token overlap between two goods descriptions, in [0, 1]."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


@dataclass(frozen=True, slots=True)
class DiscrepancyDetector:
    """Deterministic discrepancy detection across a presentation.

    Args:
        amount_tolerance_pct: allowed band above the LC amount (e.g. ``0.05`` for the
            UCP600 Art. 30 +/- tolerance). Default ``0.0`` (strict, no tolerance).
        description_min_overlap: token-overlap floor below which two goods descriptions
            are treated as inconsistent. Default ``0.6``.
        as_of: the presentation date used for the expiry check; defaults to the
            shipment date when omitted so the detector stays deterministic in tests.
    """

    amount_tolerance_pct: float = 0.0
    description_min_overlap: float = 0.6
    as_of: date | None = None

    def detect(
        self,
        lc: LetterOfCredit,
        extracts: list[DocumentExtract],
        rules: list[Ucp600Rule] | None = None,
    ) -> list[Discrepancy]:
        """Return every discrepancy between the presentation and the LC / UCP600."""
        rule_index = self._index_rules(rules or [])
        by_type = {e.doc_type: e for e in extracts}

        found: list[Discrepancy] = []
        found.extend(self._check_required_documents(lc, by_type, rule_index))
        found.extend(self._check_invoice(lc, by_type.get(TradeDocType.INVOICE), rule_index))
        found.extend(
            self._check_shipment_date(lc, by_type.get(TradeDocType.BILL_OF_LADING), rule_index)
        )
        found.extend(self._check_expiry(lc, extracts, rule_index))
        found.extend(self._check_description_consistency(lc, extracts, rule_index))
        found.extend(self._check_insurance(lc, by_type.get(TradeDocType.INSURANCE), rule_index))
        return found

    # ------------------------------------------------------------------ #
    # Individual checks
    # ------------------------------------------------------------------ #
    def _check_required_documents(
        self,
        lc: LetterOfCredit,
        by_type: dict[TradeDocType, DocumentExtract],
        rule_index: dict[str, Ucp600Rule],
    ) -> list[Discrepancy]:
        required = self._required_docs(lc)
        out: list[Discrepancy] = []
        for doc_type in required:
            if doc_type not in by_type:
                out.append(
                    Discrepancy(
                        kind=DiscrepancyKind.MISSING_DOCUMENT,
                        ucp600_article=_ART_EXAMINATION,
                        doc_type=doc_type,
                        field="presence",
                        expected=f"{doc_type.value} presented",
                        found="not presented",
                        severity=Severity.CRITICAL,
                        citations=(
                            self._lc_citation(lc, "documents_required"),
                            self._ucp_citation(_ART_EXAMINATION, rule_index),
                        ),
                    )
                )
        return out

    def _check_invoice(
        self,
        lc: LetterOfCredit,
        invoice: DocumentExtract | None,
        rule_index: dict[str, Ucp600Rule],
    ) -> list[Discrepancy]:
        if invoice is None:
            return []  # absence handled by the required-documents check
        out: list[Discrepancy] = []

        inv_amount = _parse_amount(invoice.fields.get("amount"))
        if inv_amount is not None:
            ceiling = lc.amount * (1.0 + max(self.amount_tolerance_pct, 0.0))
            if inv_amount > ceiling + 1e-9:
                out.append(
                    Discrepancy(
                        kind=DiscrepancyKind.AMOUNT_MISMATCH,
                        ucp600_article=_ART_INVOICE,
                        doc_type=TradeDocType.INVOICE,
                        field="amount",
                        expected=f"<= {lc.amount:.2f} {lc.currency}",
                        found=f"{inv_amount:.2f} {invoice.fields.get('currency', '')}".strip(),
                        severity=Severity.HIGH,
                        citations=(
                            self._lc_citation(lc, "amount"),
                            self._ucp_citation(_ART_INVOICE, rule_index),
                        ),
                    )
                )

        inv_currency = (invoice.fields.get("currency") or "").strip().upper()
        if inv_currency and lc.currency and inv_currency != lc.currency.strip().upper():
            out.append(
                Discrepancy(
                    kind=DiscrepancyKind.INCONSISTENT_DATA,
                    ucp600_article=_ART_INVOICE,
                    doc_type=TradeDocType.INVOICE,
                    field="currency",
                    expected=lc.currency.strip().upper(),
                    found=inv_currency,
                    severity=Severity.HIGH,
                    citations=(
                        self._lc_citation(lc, "currency"),
                        self._ucp_citation(_ART_INVOICE, rule_index),
                    ),
                )
            )
        return out

    def _check_shipment_date(
        self,
        lc: LetterOfCredit,
        transport: DocumentExtract | None,
        rule_index: dict[str, Ucp600Rule],
    ) -> list[Discrepancy]:
        if transport is None:
            return []
        shipped = _parse_date(
            transport.fields.get("shipment_date") or transport.fields.get("on_board_date")
        )
        latest = _parse_date(lc.latest_shipment)
        if shipped is None or latest is None:
            return []
        if shipped > latest:
            return [
                Discrepancy(
                    kind=DiscrepancyKind.LATE_SHIPMENT,
                    ucp600_article=_ART_TRANSPORT,
                    doc_type=TradeDocType.BILL_OF_LADING,
                    field="shipment_date",
                    expected=f"on or before {latest.isoformat()}",
                    found=shipped.isoformat(),
                    severity=Severity.HIGH,
                    citations=(
                        self._lc_citation(lc, "latest_shipment"),
                        self._ucp_citation(_ART_TRANSPORT, rule_index),
                    ),
                )
            ]
        return []

    def _check_expiry(
        self,
        lc: LetterOfCredit,
        extracts: list[DocumentExtract],
        rule_index: dict[str, Ucp600Rule],
    ) -> list[Discrepancy]:
        expiry = _parse_date(lc.expiry_date)
        if expiry is None:
            return []
        presented = self.as_of or self._presentation_date(extracts)
        if presented is None:
            return []
        if presented > expiry:
            return [
                Discrepancy(
                    kind=DiscrepancyKind.DATE_EXPIRED,
                    ucp600_article=_ART_EXPIRY,
                    doc_type=TradeDocType.OTHER,
                    field="presentation_date",
                    expected=f"on or before {expiry.isoformat()}",
                    found=presented.isoformat(),
                    severity=Severity.CRITICAL,
                    citations=(
                        self._lc_citation(lc, "expiry_date"),
                        self._ucp_citation(_ART_EXPIRY, rule_index),
                    ),
                )
            ]
        return []

    def _check_description_consistency(
        self,
        lc: LetterOfCredit,
        extracts: list[DocumentExtract],
        rule_index: dict[str, Ucp600Rule],
    ) -> list[Discrepancy]:
        lc_desc = lc.terms.get("goods_description", "")
        if not lc_desc:
            return []
        out: list[Discrepancy] = []
        for extract in extracts:
            doc_desc = extract.fields.get("goods_description")
            if not doc_desc:
                continue
            score = _overlap(lc_desc, doc_desc)
            if score < self.description_min_overlap:
                article = (
                    _ART_INVOICE if extract.doc_type is TradeDocType.INVOICE else _ART_EXAMINATION
                )
                out.append(
                    Discrepancy(
                        kind=DiscrepancyKind.DESCRIPTION_MISMATCH,
                        ucp600_article=article,
                        doc_type=extract.doc_type,
                        field="goods_description",
                        expected=lc_desc,
                        found=doc_desc,
                        severity=Severity.MEDIUM,
                        citations=(
                            self._lc_citation(lc, "goods_description"),
                            self._ucp_citation(article, rule_index),
                            self._doc_citation(extract),
                        ),
                    )
                )
        return out

    def _check_insurance(
        self,
        lc: LetterOfCredit,
        insurance: DocumentExtract | None,
        rule_index: dict[str, Ucp600Rule],
    ) -> list[Discrepancy]:
        # Insurance is only material when the LC incoterm requires the seller to
        # insure (CIF / CIP). Otherwise its absence is not a discrepancy.
        incoterm = (lc.incoterm or "").strip().upper()
        if incoterm not in {"CIF", "CIP"}:
            return []
        if insurance is None:
            return [
                Discrepancy(
                    kind=DiscrepancyKind.MISSING_DOCUMENT,
                    ucp600_article=_ART_INSURANCE,
                    doc_type=TradeDocType.INSURANCE,
                    field="presence",
                    expected=f"insurance document required for incoterm {incoterm}",
                    found="not presented",
                    severity=Severity.HIGH,
                    citations=(
                        self._lc_citation(lc, "incoterm"),
                        self._ucp_citation(_ART_INSURANCE, rule_index),
                    ),
                )
            ]
        # UCP600 Art. 28(f): insured amount must be at least 110% of the invoice/CIF value.
        insured = _parse_amount(insurance.fields.get("insured_amount"))
        if insured is not None and insured < lc.amount * 1.10 - 1e-9:
            return [
                Discrepancy(
                    kind=DiscrepancyKind.UCP600_RULE_BREACH,
                    ucp600_article=_ART_INSURANCE,
                    doc_type=TradeDocType.INSURANCE,
                    field="insured_amount",
                    expected=f">= {lc.amount * 1.10:.2f} {lc.currency} (110% of CIF value)",
                    found=f"{insured:.2f}",
                    severity=Severity.HIGH,
                    citations=(
                        self._ucp_citation(_ART_INSURANCE, rule_index),
                        self._doc_citation(insurance),
                    ),
                )
            ]
        return []

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _required_docs(self, lc: LetterOfCredit) -> tuple[TradeDocType, ...]:
        raw = lc.terms.get("documents_required", "")
        if not raw:
            return _DEFAULT_REQUIRED_DOCS
        wanted: list[TradeDocType] = []
        for token in re.split(r"[;,]", raw):
            key = token.strip().lower().replace(" ", "_")
            for doc_type in TradeDocType:
                if doc_type.value == key:
                    wanted.append(doc_type)
                    break
        return tuple(dict.fromkeys(wanted)) or _DEFAULT_REQUIRED_DOCS

    @staticmethod
    def _presentation_date(extracts: list[DocumentExtract]) -> date | None:
        """Best-effort presentation date: the latest dated field across the documents."""
        dates: list[date] = []
        for extract in extracts:
            for key in ("presentation_date", "issue_date", "shipment_date", "on_board_date"):
                parsed = _parse_date(extract.fields.get(key))
                if parsed is not None:
                    dates.append(parsed)
        return max(dates) if dates else None

    @staticmethod
    def _index_rules(rules: list[Ucp600Rule]) -> dict[str, Ucp600Rule]:
        return {rule.article: rule for rule in rules}

    @staticmethod
    def _lc_citation(lc: LetterOfCredit, term: str) -> Citation:
        return Citation(
            source_id=lc.lc_number,
            source_type=CitationType.LC,
            title=f"Letter of Credit {lc.lc_number} : term '{term}'",
            snippet=str(lc.terms.get(term, "")) if term in lc.terms else "",
        )

    @staticmethod
    def _ucp_citation(article: str, rule_index: dict[str, Ucp600Rule]) -> Citation:
        rule = rule_index.get(article)
        return Citation(
            source_id=article,
            source_type=CitationType.UCP600,
            title=rule.title if rule else article,
            url=rule.url if rule else "",
            snippet=rule.requirement if rule else "",
            score=rule.score if rule else None,
        )

    @staticmethod
    def _doc_citation(extract: DocumentExtract) -> Citation:
        return Citation(
            source_id=extract.document_id or extract.doc_type.value,
            source_type=CitationType.DOCUMENT,
            title=f"Presented {extract.doc_type.value}",
            page=1 if extract.pages else None,
            snippet=extract.raw_text[:200],
        )
