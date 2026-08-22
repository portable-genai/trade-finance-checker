"""Domain models for the Trade-Finance Document Checker (system B4).

This module is the heart of the hexagon. It has **no dependency on Google Cloud,
ADK, FastAPI, or any framework** : only the Python standard library. Every adapter
(GCP, remote-platform, or on-prem placeholder) speaks in terms of these types, which
is what lets the managed-service stack be swapped for an on-premise one without
touching domain logic (General Principle P-02, "no vendor lock-in / ports & adapters").

The domain models a single **presentation** under a documentary credit: a
:class:`LetterOfCredit` plus the set of :class:`PresentedDocument` objects (invoice,
bill of lading, insurance, packing list, certificate of origin, draft). The checker
runs deterministic checks against the LC terms and the **UCP600** rules and returns a
:class:`DiscrepancyReport` (verdict + the discrepancies found, each cited).

This module is the **vertical** half of the domain: the letter-of-credit artifacts a fork
rewrites when it retargets the repo. The vertical-neutral machinery it builds on (citations,
the LLM envelope, guardrail and redaction verdicts, the audit event, agent cards, the shared
severity scale, the clock, and the commons re-exports) is defined in
:mod:`trade_finance_checker.domain.kernel` and imported below, never redeclared here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# A7: the vertical-neutral machinery lives in ``kernel`` and is IMPORTED here, never
# redeclared. The arrow points one way : ``models`` (this vertical) depends on ``kernel``,
# and ``kernel`` imports nothing from this package, so a fork can take the kernel without
# dragging in the letter-of-credit artifacts it is about to rewrite. Every kernel name is
# re-exported below with ``as`` so that existing ``from ...domain.models import X`` sites
# keep working unchanged; ``tests/unit/test_kernel_boundary.py`` proves both halves
# (the direction, by importing the kernel in a fresh interpreter, and the re-export, by
# asserting object identity between the two modules).
from .kernel import AgentCard as AgentCard
from .kernel import AgentSkill as AgentSkill
from .kernel import AuditEvent as AuditEvent
from .kernel import Citation as Citation
from .kernel import CitationType as CitationType
from .kernel import Decision as Decision
from .kernel import Direction as Direction
from .kernel import EvalMetricResult as EvalMetricResult
from .kernel import EvalReport as EvalReport
from .kernel import GuardrailCategory as GuardrailCategory
from .kernel import GuardrailFinding as GuardrailFinding
from .kernel import GuardrailVerdict as GuardrailVerdict
from .kernel import LlmMessage as LlmMessage
from .kernel import LlmRequest as LlmRequest
from .kernel import LlmResponse as LlmResponse
from .kernel import MemoryItem as MemoryItem
from .kernel import RedactionFinding as RedactionFinding
from .kernel import RedactionResult as RedactionResult
from .kernel import Session as Session
from .kernel import Severity as Severity
from .kernel import StrEnum as StrEnum
from .kernel import ThinkingLevel as ThinkingLevel
from .kernel import TokenUsage as TokenUsage
from .kernel import ToolSpec as ToolSpec
from .kernel import utcnow as utcnow


# --------------------------------------------------------------------------- #
# Trade-finance taxonomy
# --------------------------------------------------------------------------- #
class LcTermKind(StrEnum):
    """The kind of an individual term parsed out of a Letter of Credit.

    The LC carries a free-form ``terms`` map; this enum names the terms the
    deterministic detector reasons about explicitly so a key typo fails fast.
    """

    AMOUNT = "amount"
    CURRENCY = "currency"
    EXPIRY_DATE = "expiry_date"
    LATEST_SHIPMENT = "latest_shipment"
    INCOTERM = "incoterm"
    GOODS_DESCRIPTION = "goods_description"
    PARTIAL_SHIPMENT = "partial_shipment"
    TRANSHIPMENT = "transhipment"
    PORT_OF_LOADING = "port_of_loading"
    PORT_OF_DISCHARGE = "port_of_discharge"
    DOCUMENTS_REQUIRED = "documents_required"
    OTHER = "other"


class TradeDocType(StrEnum):
    """The kinds of document presented under a documentary credit."""

    INVOICE = "invoice"
    BILL_OF_LADING = "bill_of_lading"
    INSURANCE = "insurance"
    PACKING_LIST = "packing_list"
    CERT_ORIGIN = "cert_origin"
    DRAFT = "draft"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class LetterOfCredit:
    """The documentary credit a presentation is checked against.

    Parties (``beneficiary`` / ``applicant``) are trade-party PII and are redacted at
    the boundary (P-04) before any model call, trace span, or audit write. ``terms``
    is a free-form map of additional LC conditions keyed by an ``LcTermKind`` value.
    """

    lc_number: str
    amount: float
    currency: str
    expiry_date: str  # ISO date the credit expires (presentation deadline)
    latest_shipment: str  # ISO date : goods must ship on or before this date
    incoterm: str = ""  # e.g. "CIF", "FOB"
    beneficiary: str = ""  # the seller / exporter (PII)
    applicant: str = ""  # the buyer / importer (PII)
    terms: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PresentedDocument:
    """One document presented for examination under the credit.

    ``fields`` is the structured key/value extraction (e.g. ``{"amount": "98000.00",
    "currency": "USD", "shipment_date": "2026-05-10"}``) produced by the extraction
    port; ``pages`` is the page count for traceability.
    """

    doc_type: TradeDocType
    fields: dict[str, str] = field(default_factory=dict)
    pages: int = 1
    document_id: str = ""  # opaque id for the source artifact


@dataclass(frozen=True, slots=True)
class DocumentExtract:
    """The structured result of parsing one presented document (or the LC).

    Returned by :class:`DocumentExtractionPort`. ``raw_text`` is kept short and is
    already redacted; the structured ``fields`` are what the detector reasons over.
    """

    doc_type: TradeDocType
    fields: dict[str, str] = field(default_factory=dict)
    pages: int = 1
    document_id: str = ""
    raw_text: str = ""


@dataclass(frozen=True, slots=True)
class Ucp600Rule:
    """A UCP600 article retrieved from the governed rule set (via A2).

    The rule text is illustrative; the article reference is what every detected
    discrepancy is cited to (P-07). Retrieved through :class:`RulesRetrievalPort`.
    """

    article: str  # e.g. "UCP600 Art. 14", "UCP600 Art. 18"
    title: str
    requirement: str
    url: str = ""
    score: float = 0.0


# --------------------------------------------------------------------------- #
# Top-level artifacts (the three artifacts B4 produces)
# --------------------------------------------------------------------------- #
class DiscrepancyKind(StrEnum):
    """The category of a detected discrepancy against the LC / UCP600."""

    AMOUNT_MISMATCH = "amount_mismatch"
    DATE_EXPIRED = "date_expired"
    LATE_SHIPMENT = "late_shipment"
    DESCRIPTION_MISMATCH = "description_mismatch"
    MISSING_DOCUMENT = "missing_document"
    INCONSISTENT_DATA = "inconsistent_data"
    UCP600_RULE_BREACH = "ucp600_rule_breach"


class ComplianceVerdict(StrEnum):
    """The overall verdict for one presentation."""

    COMPLIANT = "compliant"
    DISCREPANT = "discrepant"


@dataclass(frozen=True, slots=True)
class Discrepancy:
    """One detected discrepancy between the presentation and the LC / UCP600.

    Each discrepancy names the UCP600 article it breaches, the document type and
    field at fault, what was expected (per the LC or UCP600) versus what was found,
    a severity, and the citations that back it (P-07).
    """

    kind: DiscrepancyKind
    ucp600_article: str
    doc_type: TradeDocType
    field: str
    expected: str
    found: str
    severity: Severity = Severity.MEDIUM
    citations: tuple[Citation, ...] = ()

    @property
    def is_material(self) -> bool:
        """A material discrepancy is anything at MEDIUM severity or above.

        Material discrepancies drive the DISCREPANT verdict; trivial LOW findings
        (informational only) do not by themselves make a presentation discrepant.
        """
        return self.severity is not Severity.LOW


@dataclass(frozen=True, slots=True)
class PresentationSummary:
    """The parsed LC terms + the documents checked, for traceability."""

    lc_number: str
    currency: str
    amount: float
    expiry_date: str
    latest_shipment: str
    documents_checked: tuple[TradeDocType, ...] = ()
    terms: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DiscrepancyReport:
    """The full check result for one presentation (the primary B4 artifact).

    ``requires_human_review`` is always ``True``: a discrepancy report is decision
    support for a trade-finance officer, never an approval (P-06). The ``verdict`` is
    DISCREPANT iff one or more material discrepancies were found.
    """

    lc_number: str
    documents_checked: tuple[TradeDocType, ...]
    discrepancies: tuple[Discrepancy, ...]
    verdict: ComplianceVerdict
    summary: PresentationSummary
    requires_human_review: bool = True
    narrative: str = ""  # LLM-drafted prose; never overrides the deterministic verdict
    citations: tuple[Citation, ...] = ()
    generated_at: datetime = field(default_factory=utcnow)

    @property
    def discrepancy_count(self) -> int:
        return len(self.discrepancies)

    @property
    def material_count(self) -> int:
        return sum(1 for d in self.discrepancies if d.is_material)
