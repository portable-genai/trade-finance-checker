"""On-prem placeholder for ``DocumentExtractionPort`` : the Google Distributed Cloud target.

One of the reversibility (P-02, P-12) migration placeholders: in the managed profile this
port binds to the Document AI adapter; switching ``profile`` to ``onprem`` rebinds it here.
The adapter constructs cleanly with **no external dependencies** and structurally satisfies
the same Protocol as the managed adapter, so the contract tests prove interface parity.
Porting B4 on-premise is *only* a matter of filling these bodies in : the domain check
pipeline and the service callers do not change.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import DocumentExtract, PresentedDocument, TradeDocType

_MESSAGE = (
    "On-prem DocumentExtractionPort adapter is a migration placeholder; implement against "
    "your on-premise platform. Core domain logic is unchanged."
)


class OnPremExtractionAdapter:
    """Placeholder extraction adapter for the on-prem (Google Distributed Cloud) profile."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def extract(self, document: PresentedDocument) -> DocumentExtract:
        raise NotImplementedError(_MESSAGE)

    def extract_raw(self, content: bytes, doc_type: TradeDocType) -> DocumentExtract:
        raise NotImplementedError(_MESSAGE)
