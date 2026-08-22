"""Document AI extraction adapter (DocumentExtractionPort).

Primary production extraction backend for B4: **Document AI** on the Gemini Enterprise
Agent Platform. This adapter calls a Document AI processor through a **regional** endpoint
pinned to ``asia-southeast1`` (Singapore) so that parsing of the Letter of Credit and the
presented trade documents stays in-country for Transaction Banking data residency.

Each processed document is mapped to a domain :class:`DocumentExtract`: the processor's
extracted entities become the structured ``fields`` map the deterministic detector reasons
over (amount, currency, shipment_date, goods_description, ...), and the document text is
kept (short) for traceability.

All Google Cloud SDK imports are lazy (inside ``__init__`` / methods) so the on-prem / test
profile imports this module without ``google-cloud-documentai`` installed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...config import Settings
from ...domain.models import DocumentExtract, PresentedDocument, TradeDocType

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from google.cloud import documentai_v1

# Map Document AI entity type names to the structured field keys the detector expects.
_ENTITY_ALIASES: dict[str, str] = {
    "total_amount": "amount",
    "invoice_amount": "amount",
    "net_amount": "amount",
    "currency_code": "currency",
    "ship_date": "shipment_date",
    "shipped_on_board_date": "on_board_date",
    "description": "goods_description",
    "goods": "goods_description",
    "insured_value": "insured_amount",
}


class DocumentAiExtractionAdapter:
    """Parse the LC and presented documents via a Document AI processor."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        cfg = settings.document_ai
        self._location = cfg.location
        self._processor_id = cfg.processor_id
        self._processor_version = cfg.processor_version
        # Regional endpoint : the global endpoint gives no residency guarantee.
        self._endpoint = f"{self._location}-documentai.googleapis.com"
        self._client: Any | None = None

    # ------------------------------------------------------------------ #
    # Lazy client construction
    # ------------------------------------------------------------------ #
    def _get_client(self) -> documentai_v1.DocumentProcessorServiceClient:
        if self._client is None:
            from google.api_core.client_options import ClientOptions
            from google.cloud import documentai_v1

            self._client = documentai_v1.DocumentProcessorServiceClient(
                client_options=ClientOptions(api_endpoint=self._endpoint),
            )
        return self._client

    def _processor_name(self) -> str:
        base = (
            f"projects/{self._settings.project_id}"
            f"/locations/{self._location}"
            f"/processors/{self._processor_id}"
        )
        if self._processor_version:
            return f"{base}/processorVersions/{self._processor_version}"
        return base

    # ------------------------------------------------------------------ #
    # DocumentExtractionPort
    # ------------------------------------------------------------------ #
    def extract(self, document: PresentedDocument) -> DocumentExtract:
        """Return the structured extract for an already-fielded presented document.

        When a presented document already carries structured ``fields`` (e.g. supplied by
        an upstream channel) the adapter trusts them; otherwise it would re-parse the raw
        bytes via :meth:`extract_raw`. Document AI is not invoked for pre-fielded inputs.
        """
        return DocumentExtract(
            doc_type=document.doc_type,
            fields=dict(document.fields),
            pages=document.pages,
            document_id=document.document_id,
            raw_text="",
        )

    def extract_raw(self, content: bytes, doc_type: TradeDocType) -> DocumentExtract:
        """Parse raw document bytes (e.g. an uploaded PDF) via Document AI."""
        from google.cloud import documentai_v1

        client = self._get_client()
        raw_document = documentai_v1.RawDocument(content=content, mime_type="application/pdf")
        request = documentai_v1.ProcessRequest(
            name=self._processor_name(),
            raw_document=raw_document,
        )
        result = client.process_document(request=request)
        doc = result.document
        fields = self._entities_to_fields(doc)
        return DocumentExtract(
            doc_type=doc_type,
            fields=fields,
            pages=len(getattr(doc, "pages", []) or []) or 1,
            document_id="",
            raw_text=(getattr(doc, "text", "") or "")[:500],
        )

    # ------------------------------------------------------------------ #
    # Entity mapping
    # ------------------------------------------------------------------ #
    @staticmethod
    def _entities_to_fields(doc: Any) -> dict[str, str]:
        fields: dict[str, str] = {}
        for entity in getattr(doc, "entities", []) or []:
            etype = (getattr(entity, "type_", "") or "").strip().lower()
            value = (getattr(entity, "mention_text", "") or "").strip()
            if not etype or not value:
                continue
            key = _ENTITY_ALIASES.get(etype, etype)
            # Keep the first occurrence of each field; later duplicates are ignored.
            fields.setdefault(key, value)
        return fields
