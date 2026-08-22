"""Pydantic v2 request/response models for the B4 Trade-Finance Checker API.

These schemas mirror the frozen domain dataclasses in
:mod:`trade_finance_checker.domain.models` one-for-one, so the HTTP boundary is a thin,
typed projection of the domain : the React/Next.js UI and the CLI consume exactly these
shapes. Each response model exposes a ``from_domain`` classmethod that builds itself from
the corresponding domain object, using :func:`domain.serialization.to_jsonable` where a
nested structure is easiest to project verbatim (enums become their ``.value`` strings).

Nothing here imports Google Cloud, ADK, or any adapter: the API layer depends only on the
domain models, the ports, and the orchestration service : never on a concrete adapter.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..domain import models as m
from ..domain.serialization import to_jsonable

# --------------------------------------------------------------------------- #
# Shared projections
# --------------------------------------------------------------------------- #


class CitationModel(BaseModel):
    """Examiner-grade provenance attached to a discrepancy (mirror of Citation)."""

    source_id: str
    source_type: str
    title: str
    url: str = ""
    page: int | None = None
    snippet: str = ""
    score: float | None = None

    @classmethod
    def from_domain(cls, citation: m.Citation) -> CitationModel:
        return cls(**to_jsonable(citation))


# --------------------------------------------------------------------------- #
# Requests
# --------------------------------------------------------------------------- #


class LetterOfCreditModel(BaseModel):
    """Inbound Letter of Credit (mirror of LetterOfCredit)."""

    lc_number: str = Field(..., min_length=1)
    amount: float
    currency: str
    expiry_date: str
    latest_shipment: str
    incoterm: str = ""
    beneficiary: str = ""
    applicant: str = ""
    terms: dict[str, str] = Field(default_factory=dict)

    def to_domain(self) -> m.LetterOfCredit:
        return m.LetterOfCredit(
            lc_number=self.lc_number,
            amount=self.amount,
            currency=self.currency,
            expiry_date=self.expiry_date,
            latest_shipment=self.latest_shipment,
            incoterm=self.incoterm,
            beneficiary=self.beneficiary,
            applicant=self.applicant,
            terms=dict(self.terms),
        )


class PresentedDocumentModel(BaseModel):
    """Inbound presented document (mirror of PresentedDocument)."""

    doc_type: str
    fields: dict[str, str] = Field(default_factory=dict)
    pages: int = 1
    document_id: str = ""

    def to_domain(self) -> m.PresentedDocument:
        return m.PresentedDocument(
            doc_type=m.TradeDocType(self.doc_type),
            fields=dict(self.fields),
            pages=self.pages,
            document_id=self.document_id,
        )


class CheckRequest(BaseModel):
    """Inbound presentation-check request.

    There is no ``actor`` field: the audit actor is the server-verified :class:`Principal`
    resolved by the IdentityPort (``api/security.py``), never a client-supplied identity.
    """

    lc: LetterOfCreditModel
    documents: list[PresentedDocumentModel] = Field(default_factory=list)


class ExtractRequest(BaseModel):
    """Inbound single-document extraction request (no client-supplied actor: see above)."""

    document: PresentedDocumentModel


class LcRegistrationRequest(BaseModel):
    """Claim a Letter of Credit for the caller's verified tenant (audience data)."""

    lc_number: str = Field(..., min_length=3, max_length=60)


class LcRegistrationResponse(BaseModel):
    """Outcome of an LC ownership registration."""

    lc_number: str
    tenant: str
    already_registered: bool = False


# --------------------------------------------------------------------------- #
# Artifact responses
# --------------------------------------------------------------------------- #


class DiscrepancyModel(BaseModel):
    """One detected discrepancy (mirror of Discrepancy)."""

    kind: str
    ucp600_article: str
    doc_type: str
    field: str
    expected: str
    found: str
    severity: str = "medium"
    citations: list[CitationModel] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, disc: m.Discrepancy) -> DiscrepancyModel:
        return cls(
            kind=disc.kind.value,
            ucp600_article=disc.ucp600_article,
            doc_type=disc.doc_type.value,
            field=disc.field,
            expected=disc.expected,
            found=disc.found,
            severity=disc.severity.value,
            citations=[CitationModel.from_domain(c) for c in disc.citations],
        )


class PresentationSummaryModel(BaseModel):
    """Parsed LC terms + documents checked (mirror of PresentationSummary)."""

    lc_number: str
    currency: str
    amount: float
    expiry_date: str
    latest_shipment: str
    documents_checked: list[str] = Field(default_factory=list)
    terms: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def from_domain(cls, summary: m.PresentationSummary) -> PresentationSummaryModel:
        return cls(
            lc_number=summary.lc_number,
            currency=summary.currency,
            amount=summary.amount,
            expiry_date=summary.expiry_date,
            latest_shipment=summary.latest_shipment,
            documents_checked=[d.value for d in summary.documents_checked],
            terms=dict(summary.terms),
        )


class DiscrepancyReportResponse(BaseModel):
    """The full check result for one presentation (mirror of DiscrepancyReport)."""

    lc_number: str
    documents_checked: list[str] = Field(default_factory=list)
    discrepancies: list[DiscrepancyModel] = Field(default_factory=list)
    verdict: str
    summary: PresentationSummaryModel
    requires_human_review: bool = True
    narrative: str = ""
    citations: list[CitationModel] = Field(default_factory=list)
    discrepancy_count: int = 0
    material_count: int = 0
    generated_at: str = ""

    @classmethod
    def from_domain(cls, report: m.DiscrepancyReport) -> DiscrepancyReportResponse:
        return cls(
            lc_number=report.lc_number,
            documents_checked=[d.value for d in report.documents_checked],
            discrepancies=[DiscrepancyModel.from_domain(d) for d in report.discrepancies],
            verdict=report.verdict.value,
            summary=PresentationSummaryModel.from_domain(report.summary),
            requires_human_review=report.requires_human_review,
            narrative=report.narrative,
            citations=[CitationModel.from_domain(c) for c in report.citations],
            discrepancy_count=report.discrepancy_count,
            material_count=report.material_count,
            generated_at=report.generated_at.isoformat(),
        )


class DocumentExtractResponse(BaseModel):
    """The structured result of parsing one document (mirror of DocumentExtract)."""

    doc_type: str
    fields: dict[str, str] = Field(default_factory=dict)
    pages: int = 1
    document_id: str = ""
    raw_text: str = ""

    @classmethod
    def from_domain(cls, extract: m.DocumentExtract) -> DocumentExtractResponse:
        return cls(
            doc_type=extract.doc_type.value,
            fields=dict(extract.fields),
            pages=extract.pages,
            document_id=extract.document_id,
            raw_text=extract.raw_text,
        )


# --------------------------------------------------------------------------- #
# Health & governance
# --------------------------------------------------------------------------- #


class HealthResponse(BaseModel):
    """Liveness/readiness of the checker and its active profile."""

    status: str = "ok"
    profile: str = "local"
    region: str = "asia-southeast1"


class AgentSkillModel(BaseModel):
    id: str
    name: str
    description: str


class AgentCardModel(BaseModel):
    """A2A AgentCard served at /.well-known/agent-card.json (mirror of AgentCard)."""

    name: str
    description: str
    url: str
    version: str
    provider: str = "trade-finance-checker"
    skills: list[AgentSkillModel] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, card: m.AgentCard) -> AgentCardModel:
        return cls(**to_jsonable(card))
