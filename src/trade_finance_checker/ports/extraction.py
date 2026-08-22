"""DocumentExtractionPort : structured parse of the LC and presented documents.

Primary GCP adapter: **Document AI** on the Gemini Enterprise Agent Platform, pinned
to a single in-country region. The adapter parses a Letter of Credit and each
presented trade document (invoice, bill of lading, insurance, packing list,
certificate of origin, draft) into a structured :class:`DocumentExtract`. On-prem
migration swaps this for a placeholder adapter with no change to callers.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import DocumentExtract, PresentedDocument, TradeDocType


@runtime_checkable
class DocumentExtractionPort(Protocol):
    def extract(self, document: PresentedDocument) -> DocumentExtract:
        """Parse one presented document into a structured :class:`DocumentExtract`."""
        ...

    def extract_raw(self, content: bytes, doc_type: TradeDocType) -> DocumentExtract:
        """Parse raw document bytes (e.g. an uploaded PDF) into a structured extract."""
        ...
