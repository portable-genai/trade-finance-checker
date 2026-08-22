"""Local document-extraction adapter (DocumentExtractionPort) : Document AI stand-in.

The ``local`` profile's stand-in for **Document AI**: SDK-free, deterministic parsing.
For an already-fielded :class:`PresentedDocument` (the common case in B4, where an
upstream channel supplies the structured fields) the adapter trusts and projects those
fields, exactly like the managed and fake adapters. For raw bytes it parses plain text
(and per-page PDF text when ``pypdf`` is importable) and lifts a few obvious trade fields
out of the text with simple regexes, so an uploaded document still yields a structured
extract offline. There is no Google emulator for Document AI, so this path is
unconditional and imports no google-cloud package.
"""

from __future__ import annotations

import re

from ...config import Settings
from ...domain.models import DocumentExtract, PresentedDocument, TradeDocType

# Light field lifters for the raw-bytes path: amount, currency, dates. Best-effort only;
# the structured-fields path is authoritative when an upstream channel supplies fields.
_AMOUNT_RE = re.compile(r"(?:amount|total)\D{0,8}([0-9][0-9,]*\.?[0-9]{0,2})", re.I)
_CURRENCY_RE = re.compile(r"\b(USD|EUR|SGD|GBP|JPY|HKD|AUD|CNY)\b")
_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_DESC_RE = re.compile(r"(?:goods|description)\s*[:\-]\s*(.+)", re.I)


class LocalDocumentExtractionAdapter:
    """Parse the LC and presented documents into structured fields, no SDK required."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def extract(self, document: PresentedDocument) -> DocumentExtract:
        """Return the structured extract for an already-fielded presented document.

        When a presented document already carries structured ``fields`` the adapter trusts
        them (no re-parse), mirroring the managed adapter's behaviour for pre-fielded inputs.
        """
        return DocumentExtract(
            doc_type=document.doc_type,
            fields=dict(document.fields),
            pages=document.pages,
            document_id=document.document_id,
            raw_text="",
        )

    def extract_raw(self, content: bytes, doc_type: TradeDocType) -> DocumentExtract:
        """Parse raw document bytes (plain text, or per-page PDF text via pypdf)."""
        text = self._to_text(content)
        fields = self._lift_fields(text)
        return DocumentExtract(
            doc_type=doc_type,
            fields=fields,
            pages=self._page_count(content),
            document_id="",
            raw_text=text[:500],
        )

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _to_text(self, content: bytes) -> str:
        if self._looks_like_pdf(content):
            pages = self._extract_pdf_pages(content)
            if pages:
                return "\n\n".join(pages)
        if isinstance(content, bytes):
            return content.decode("utf-8", errors="replace")
        return str(content)

    @staticmethod
    def _looks_like_pdf(content: bytes) -> bool:
        return isinstance(content, bytes) and content[:5] == b"%PDF-"

    def _page_count(self, content: bytes) -> int:
        if self._looks_like_pdf(content):
            pages = self._extract_pdf_pages(content)
            if pages:
                return len(pages)
        return 1

    @staticmethod
    def _extract_pdf_pages(content: bytes) -> list[str]:
        """Extract per-page text via pypdf when available; empty list if it is not."""
        try:
            import io

            from pypdf import PdfReader  # type: ignore[import-not-found]
        except Exception:  # noqa: BLE001 - pypdf is optional; fall back to text decode
            return []
        try:
            reader = PdfReader(io.BytesIO(content))
            return [(page.extract_text() or "") for page in reader.pages]
        except Exception:  # noqa: BLE001 - a malformed PDF falls back to text decode
            return []

    @staticmethod
    def _lift_fields(text: str) -> dict[str, str]:
        fields: dict[str, str] = {}
        amount = _AMOUNT_RE.search(text)
        if amount:
            fields["amount"] = amount.group(1).replace(",", "")
        currency = _CURRENCY_RE.search(text)
        if currency:
            fields["currency"] = currency.group(1)
        date = _DATE_RE.search(text)
        if date:
            fields["issue_date"] = date.group(1)
        desc = _DESC_RE.search(text)
        if desc:
            fields["goods_description"] = desc.group(1).strip()[:200]
        return fields
