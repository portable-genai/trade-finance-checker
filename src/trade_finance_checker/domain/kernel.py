"""Vertical-neutral evidence, model-boundary, safety, and audit contracts.

This module is the **kernel**: the part of the domain a fork inherits unchanged when it
retargets this repo at a different document vertical. It OWNS the types below rather than
re-exporting them, and it imports **nothing from this package** : only the standard library
and the shared commons (``hex_service_kit``, ``agent_eval_kit``). That one-way arrow is the
whole point of the split, and it is proved by execution in
``tests/unit/test_kernel_boundary.py``, which imports this module in a fresh interpreter and
asserts ``trade_finance_checker.domain.models`` never enters ``sys.modules``.

The trade-finance artifacts (the Letter of Credit, the presented documents, the UCP600 rule,
the discrepancy and its report) are the replaceable vertical layer and stay in
:mod:`trade_finance_checker.domain.models`. ``models`` imports this module and re-exports
every name here, so existing import sites keep working unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

# The shared value types are IMPORTED, never redeclared. Sixteen repositories had each grown
# their own copy of these, and by the time anybody compared them they had drifted. Re-exporting
# retires the whole drift class: there is one definition, and `is`-identity assertions in
# tests/contract/test_port_parity.py prove the domain hands out that one rather than a
# look-alike (isinstance against a runtime_checkable Protocol cannot tell the difference).
#
# `agent_eval_kit.report` is imported by SUBMODULE rather than the package root deliberately:
# this module promises to be stdlib-only, and the package root pulls httpx in via gate_client.
from agent_eval_kit.report import EvalMetricResult as EvalMetricResult
from agent_eval_kit.report import EvalReport as EvalReport
from hex_service_kit import StrEnum as StrEnum
from hex_service_kit.observability import TokenUsage as TokenUsage


def utcnow() -> datetime:
    """Timezone-aware UTC now : the single clock the domain uses."""
    return datetime.now(UTC)


# --------------------------------------------------------------------------- #
# Citation / provenance
# --------------------------------------------------------------------------- #
class CitationType(StrEnum):
    """What a citation points at: the governing instrument, a rule, or a source document.

    The member names are this vertical's vocabulary (an LC, a UCP600 article, a presented
    document); the SHAPE : an enumerated provenance kind carried on every claim : is the
    neutral part a fork keeps while renaming the members.
    """

    LC = "LC"
    UCP600 = "UCP600"
    DOCUMENT = "DOCUMENT"


@dataclass(frozen=True, slots=True)
class Citation:
    """Examiner-grade provenance attached to every consequential finding.

    A finding must point to the exact authority behind it : the governing term, the rule
    article, or the source document and page so a human can verify it (P-07).
    """

    source_id: str  # lc_number, UCP600 article ref, or document id
    source_type: CitationType
    title: str
    url: str = ""
    page: int | None = None
    snippet: str = ""
    score: float | None = None


# Retrieval has no vertical-neutral value type in this repo: the only retrieved artifact is
# the UCP600 article (``Ucp600Rule``), which is trade-finance vocabulary and therefore stays
# in ``models`` with the rest of the vertical. The neutral half of grounding that a fork DOES
# inherit is ``Citation`` above : the provenance every retrieved claim must carry.


# --------------------------------------------------------------------------- #
# Generation (LLM envelope)
# --------------------------------------------------------------------------- #
class ThinkingLevel(StrEnum):
    MINIMAL = "minimal"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class LlmMessage:
    role: str  # "user" | "model" | "system"
    content: str


@dataclass(frozen=True, slots=True)
class LlmRequest:
    messages: tuple[LlmMessage, ...]
    system_instruction: str | None = None
    model: str | None = None  # None => adapter default from config
    thinking: ThinkingLevel = ThinkingLevel.MEDIUM
    temperature: float = 0.2
    max_output_tokens: int = 4096
    response_schema: dict | None = None  # JSON schema for structured output


# ``TokenUsage`` is NOT declared HERE. Three ``int`` fields defaulting to zero, redeclared
# byte-identically in every sibling repository, is a shared value type that is not shared and a
# drift class waiting to happen. It comes from :mod:`hex_service_kit.observability`, imported at
# the top of this module, so there is exactly one definition to change and
# ``tests/contract/test_port_parity.py`` asserts object IDENTITY rather than structural
# look-alikeness.


@dataclass(frozen=True, slots=True)
class LlmResponse:
    text: str
    usage: TokenUsage = field(default_factory=TokenUsage)
    model: str = ""
    raw: dict | None = None


# --------------------------------------------------------------------------- #
# Safety (guardrail + PII redaction) : A1 Guardrail Gateway concerns
# --------------------------------------------------------------------------- #
class GuardrailCategory(StrEnum):
    PROMPT_INJECTION = "prompt_injection"
    JAILBREAK = "jailbreak"
    SENSITIVE_DATA = "sensitive_data"
    MALICIOUS_URL = "malicious_url"
    HATE = "hate"
    HARASSMENT = "harassment"
    SEXUAL = "sexual"
    DANGEROUS = "dangerous"
    OTHER = "other"


class Direction(StrEnum):
    INPUT = "input"
    OUTPUT = "output"


@dataclass(frozen=True, slots=True)
class GuardrailFinding:
    category: GuardrailCategory
    confidence: str  # e.g. "low" | "medium" | "high"
    detail: str = ""


@dataclass(frozen=True, slots=True)
class GuardrailVerdict:
    allowed: bool
    direction: Direction
    findings: tuple[GuardrailFinding, ...] = ()
    # Text after any inline sanitisation the guardrail applied (may equal input).
    sanitized_text: str | None = None
    reason: str = ""


@dataclass(frozen=True, slots=True)
class RedactionFinding:
    info_type: str  # e.g. "PERSON_NAME", "SG_NRIC_FIN", "BANK_ACCOUNT_NUMBER"
    count: int = 1


@dataclass(frozen=True, slots=True)
class RedactionResult:
    text: str  # de-identified text safe to send to the model / audit log
    findings: tuple[RedactionFinding, ...] = ()

    @property
    def redacted(self) -> bool:
        return bool(self.findings)


# --------------------------------------------------------------------------- #
# Runtime, session & memory
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Session:
    id: str
    user_id: str
    case_id: str | None = None
    created_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True, slots=True)
class MemoryItem:
    id: str
    content: str
    scope: str = "user"  # "user" | "case" | "global"
    created_at: datetime = field(default_factory=utcnow)


# --------------------------------------------------------------------------- #
# Audit & observability : A5 Observability, Audit & FinOps concerns
# --------------------------------------------------------------------------- #
class Decision(StrEnum):
    ALLOWED = "allowed"
    BLOCKED = "blocked"
    ESCALATED = "escalated"  # routed to a human (maker-checker)


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """An immutable, WORM-stored record of one check / extract interaction.

    Prompt and response are stored **already redacted** (P-04): party PII is removed at the
    boundary before it is ever written to the audit sink or a span.
    """

    action: str  # "check" | "extract" | "detect"
    actor: str  # authenticated user / service identity
    decision: Decision
    redacted_prompt: str
    redacted_response: str
    citations: tuple[Citation, ...] = ()
    resource: str = "trade-finance-checker"
    trace_id: str | None = None
    timestamp: datetime = field(default_factory=utcnow)
    metadata: dict[str, str] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Evaluation gate : A4 AI Quality & Model-Risk concerns
# --------------------------------------------------------------------------- #
# ``EvalMetricResult`` and ``EvalReport`` are likewise not declared in the domain: they are
# imported at the top of this module from :mod:`agent_eval_kit.report`.
#
# Taking them from the commons does NOT relax the fail-closed rule on ``EvalReport.passed``: the
# commons property is the same expression, ``n_examples > 0 and bool(results) and all(...)``,
# for the same reason. ``all(())`` is vacuously True, so a report that scored nothing reports
# PASSED and ``eval/run_eval.py`` exits 0 on this property, which is a promotion certified by
# the absence of evidence. Re-exporting a type whose guard is WEAKER than that rule would
# silently remove it, so the commons type is checked field by field and rule by rule, and
# ``tests/unit/test_eval_report_gate.py`` executes every branch of it.
#
# The commons type additionally carries the durable identifiers a score needs to be evidence
# (``run_id``, ``dataset_version``, ``dataset_digest``, ``evaluator``, ``schema_version``,
# ``trace_id``, ``correlation_id``, ``artifact_refs``, ``attested``), all defaulted, so a
# constructor in this repo need not name any of them.


# --------------------------------------------------------------------------- #
# Governance : A3 Agent Registry & Governance concerns (A2A AgentCard)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class AgentSkill:
    id: str
    name: str
    description: str


@dataclass(frozen=True, slots=True)
class AgentCard:
    """Minimal A2A-style agent card published at /.well-known/agent-card.json."""

    name: str
    description: str
    url: str
    version: str
    skills: tuple[AgentSkill, ...] = ()
    provider: str = "trade-finance-checker"


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """A governed, least-privilege tool exposed to the agent (typically via MCP)."""

    name: str
    description: str
    input_schema: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Shared severity scale
# --------------------------------------------------------------------------- #
class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


__all__ = [
    "AgentCard",
    "AgentSkill",
    "AuditEvent",
    "Citation",
    "CitationType",
    "Decision",
    "Direction",
    "EvalMetricResult",
    "EvalReport",
    "GuardrailCategory",
    "GuardrailFinding",
    "GuardrailVerdict",
    "LlmMessage",
    "LlmRequest",
    "LlmResponse",
    "MemoryItem",
    "RedactionFinding",
    "RedactionResult",
    "Session",
    "Severity",
    "StrEnum",
    "ThinkingLevel",
    "TokenUsage",
    "ToolSpec",
    "utcnow",
]
