#!/usr/bin/env python3
"""Offline evaluation gate for B4 Trade-Finance Checker : A4 / General Principle P-08.

This is the **promotion gate**: CI runs it on every change and the build fails if the
checker falls below the model-risk thresholds agreed for a regulated trade-finance assistant
(see ``eval/rubrics/*.yaml``)::

    discrepancy_recall    >= 0.90
    discrepancy_precision >= 0.90
    citation_accuracy     >= 0.90
    pii_safety            >= 0.99

Two evaluators, one gate
------------------------
* **Production evaluator** : the **Gen AI evaluation service** on the *Gemini Enterprise
  Agent Platform*, wired into the hexagon as ``EvaluationGatePort`` ->
  ``trade_finance_checker.adapters.gcp.genai_eval:GenAiEvalAdapter``. It needs GCP
  credentials and a project. Select it with ``--use-gcp`` (routes through the ``Container``).

* **Offline evaluator (default)** : a deterministic, dependency-light driver implemented in
  this file. It needs **no GCP credentials and no Google Cloud SDK**, runs the real
  ``TradeCheckService`` check pipeline against in-memory fake adapters, and computes the four
  metrics by comparing the detected discrepancy kinds and verdict against the planted
  ground truth. This is what guards the merge in CI.

Each golden example carries a clean or planted-discrepancy presentation with its expected
discrepancy kinds and expected verdict, so recall (did we find the planted ones?) and
precision (did we avoid false discrepancies on a clean presentation?) are real tests. A case
may also set ``pii_in_inputs``, which plants its OWN jurisdiction's national identifier in
the trade parties so ``pii_safety`` proves the redaction boundary per market rather than
proving Singapore four times over.

Usage::

    python eval/run_eval.py                      # offline gate (CI)
    python eval/run_eval.py --dataset path.jsonl # custom golden set
    python eval/run_eval.py --use-gcp            # route through GenAiEvalAdapter

Exit code is ``0`` iff ``EvalReport.passed`` (every metric meets its threshold).
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path

# The local redaction adapter is the REAL one the runtime uses: it is pure regex over the
# shared pack and needs no external service, so the gate runs it rather than a fake that
# could drift from it (or, as the fake it replaces did, mask exactly what the scorer looks
# for and make the metric unfalsifiable).
# The --mode smoke|gate scaffold + aligned report rendering come from the shared
# agent-eval-kit commons; this script keeps only its own offline
# evaluator and gate runner.
from agent_eval_kit import eval_main

from trade_finance_checker.adapters.local.redaction import LocalRegexRedactionAdapter
from trade_finance_checker.config import PiiSettings, Settings

# Domain models are pure-stdlib (no GCP / framework imports), so importing them here keeps
# this script runnable in the on-prem/test profile with no Google Cloud SDK installed.
from trade_finance_checker.domain import pii_patterns
from trade_finance_checker.domain.entitlements import ObjectOwner
from trade_finance_checker.domain.identity import Principal
from trade_finance_checker.domain.models import (
    Direction,
    DiscrepancyReport,
    DocumentExtract,
    EvalMetricResult,
    EvalReport,
    GuardrailVerdict,
    LetterOfCredit,
    LlmRequest,
    LlmResponse,
    PresentedDocument,
    TokenUsage,
    TradeDocType,
    Ucp600Rule,
)
from trade_finance_checker.envread import read_env_setting

# --------------------------------------------------------------------------- #
# Thresholds : the promotion bar (SPEC A4 / P-08). Mirrors eval/rubrics/*.yaml.
# --------------------------------------------------------------------------- #
THRESHOLDS: dict[str, float] = {
    "discrepancy_recall": 0.90,
    "discrepancy_precision": 0.90,
    "citation_accuracy": 0.90,
    "pii_safety": 0.99,
}

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = _REPO_ROOT / "eval" / "datasets" / "golden_presentations.jsonl"


# The pii_safety leak check MUST use the SAME jurisdiction pattern source as the runtime
# redactor (domain/pii_patterns.py), and this gate runs the REAL LocalRegexRedactionAdapter
# rather than a fake. Both matter: a leak then means the pipeline re-introduced PII that
# bypassed redaction, not that a bespoke detector and a bespoke redactor drifted apart and
# happened to agree. Default to B4's APAC corridors; override with
# TRADE_FINANCE_PII_JURISDICTIONS (comma-separated ISO-3166 codes).
def _pii_jurisdictions(raw: str | None) -> tuple[str, ...]:
    if raw is None:
        return tuple(pii_patterns.DEFAULT_JURISDICTIONS)
    codes = tuple(j.strip().upper() for j in raw.split(",") if j.strip())
    if not codes:
        raise SystemExit("TRADE_FINANCE_PII_JURISDICTIONS names no jurisdiction")
    return codes


_PII_JURISDICTIONS = _pii_jurisdictions(read_env_setting("TRADE_FINANCE_PII_JURISDICTIONS").raw)
_PII_PATTERNS = pii_patterns.patterns_for(_PII_JURISDICTIONS)

# Obviously-fictional national identifiers, one per market, planted in a golden case's trade
# parties to prove the pack redacts each jurisdiction it claims to cover. Together with
# _planted_pii_leak (which tests for these literals, independently of the pack) this is what
# makes the per-market claim real: break any one market's row and only its own case goes red.
#
# Two properties of the JP and AU fixtures are load-bearing, both because of the
# BANK_ACCOUNT_NUMBER catch-all (see domain/pii_patterns.py). They carry VALID check digits,
# because their rows are checksum-gated and an invalid fixture would be masked as an ordinary
# account number, proving nothing about those packs. And they are written in their GROUPED
# form, because the contiguous form is masked by the account row whether or not the
# national-id row exists at all. Drop either property and a broken JP/AU row still scores
# 1.0, because the account row silently covers for it.
#
# market -> (label written next to it in the document, the identifier itself). The label and
# the value are kept apart because the leak check tests for the VALUE verbatim, and a value
# carrying spaces cannot be recovered from the joined phrase.
_PII_BY_JURISDICTION: dict[str, tuple[str, str]] = {
    "SG": ("NRIC", "S1234567A"),
    "HK": ("HKID", "A123456(3)"),
    "JP": ("My Number", "1234 5678 9018"),
    "AU": ("TFN", "123 456 782"),
}

# The universal rows, planted in every PII case alongside the market identifier. The account
# number is deliberately a 12-digit run that FAILS the My Number checksum: it is an account,
# not a national id, so it must be masked by the BANK_ACCOUNT_NUMBER row and reported as one.
_ACCOUNT_FIXTURE = "123456789012"
_EMAIL_FIXTURE = "ops@example.com"


# --------------------------------------------------------------------------- #
# Golden dataset
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class GoldenExample:
    id: str
    lc: dict
    documents: list[dict]
    expected_discrepancy_kinds: tuple[str, ...]
    expected_verdict: str
    jurisdiction: str = ""
    pii_in_inputs: bool = False


def load_golden(path: Path) -> list[GoldenExample]:
    """Parse the JSONL golden set (stdlib ``json``)."""
    examples: list[GoldenExample] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive
            raise SystemExit(f"{path}:{lineno}: invalid JSON: {exc}") from exc
        examples.append(
            GoldenExample(
                id=str(obj.get("id", f"example-{lineno}")),
                lc=obj["lc"],
                documents=obj.get("documents", []) or [],
                expected_discrepancy_kinds=tuple(obj.get("expected_discrepancy_kinds", []) or ()),
                expected_verdict=str(obj.get("expected_verdict", "compliant")),
                jurisdiction=str(obj.get("jurisdiction", "")),
                pii_in_inputs=bool(obj.get("pii_in_inputs", False)),
            )
        )
    if not examples:
        raise SystemExit(f"{path}: golden dataset is empty")
    return examples


def load_thresholds_from_rubrics() -> dict[str, float]:
    """Read thresholds from ``eval/rubrics/*.yaml`` when PyYAML is available.

    Falls back to the in-code ``THRESHOLDS`` so the gate still runs if PyYAML is missing.
    """
    thresholds = dict(THRESHOLDS)
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        return thresholds

    rubric_dir = _REPO_ROOT / "eval" / "rubrics"
    for name in ("discrepancy_detection.yaml", "citation_accuracy.yaml"):
        rubric_path = rubric_dir / name
        if not rubric_path.exists():
            continue
        doc = yaml.safe_load(rubric_path.read_text(encoding="utf-8")) or {}
        metric = doc.get("metric")
        if isinstance(metric, str) and "threshold" in doc:
            thresholds[metric] = float(doc["threshold"])
        for companion, spec in (doc.get("companion_metrics") or {}).items():
            if isinstance(spec, dict) and "threshold" in spec:
                thresholds[str(companion)] = float(spec["threshold"])
    return thresholds


# --------------------------------------------------------------------------- #
# Deterministic fake adapters (inlined on purpose : importing tests.conftest is
# disallowed for this gate, and CI must not depend on the test tree).
#
# Redaction is deliberately NOT faked. It stands for nothing external: the local adapter is
# the one the runtime uses, is pure regex over the shared pack, and needs no service. Faking
# it could only ever let the gate pass while the real redactor was broken. Everything else
# is faked because it stands in for Document AI, the A2 rule store, an LLM or a registry.
# --------------------------------------------------------------------------- #
def _real_redactor() -> LocalRegexRedactionAdapter:
    """The production local redactor, pinned to the gate's jurisdictions."""
    return LocalRegexRedactionAdapter(Settings(pii=PiiSettings(jurisdictions=_PII_JURISDICTIONS)))


class FakeExtractionAdapter:
    """Projects already-fielded presented documents to extracts (DocumentExtractionPort)."""

    def extract(self, document: PresentedDocument) -> DocumentExtract:
        return DocumentExtract(
            doc_type=document.doc_type,
            fields=dict(document.fields),
            pages=document.pages,
            document_id=document.document_id,
        )

    def extract_raw(self, content: bytes, doc_type: TradeDocType) -> DocumentExtract:
        return DocumentExtract(doc_type=doc_type, fields={}, pages=1)


class FakeRulesAdapter:
    """Returns a small governed UCP600 rule set (RulesRetrievalPort)."""

    _RULES = (
        Ucp600Rule(
            article="UCP600 Art. 14",
            title="Standard for examination of documents",
            requirement="Data must not conflict.",
            url="https://example.org/ucp600/14",
        ),
        Ucp600Rule(
            article="UCP600 Art. 18",
            title="Commercial invoice",
            requirement="Amount must not exceed the credit; currency must match.",
            url="https://example.org/ucp600/18",
        ),
        Ucp600Rule(
            article="UCP600 Art. 6",
            title="Expiry and presentation",
            requirement="Presentation on or before expiry.",
            url="https://example.org/ucp600/6",
        ),
        Ucp600Rule(
            article="UCP600 Art. 28",
            title="Insurance document and coverage",
            requirement="Insurance covers at least 110% of CIF value.",
            url="https://example.org/ucp600/28",
        ),
    )

    def retrieve_rules(self, query: str, top_k: int = 8) -> list[Ucp600Rule]:
        return list(self._RULES)[:top_k]


class FakeGuardrailAdapter:
    """Always-allow guardrail with deterministic verdicts (GuardrailPort)."""

    def screen(self, text: str, direction: Direction) -> GuardrailVerdict:
        return GuardrailVerdict(
            allowed=True, direction=direction, findings=(), sanitized_text=text, reason="benign"
        )


class FakeTracer:
    """No-op tracer satisfying ObservabilityTracerPort (content capture OFF)."""

    @contextmanager
    def span(self, name: str, **attributes: str) -> Iterator[None]:
        yield

    def record_token_usage(self, usage: TokenUsage, model: str) -> None:
        return None


class FakeAuditSink:
    """In-memory WORM stand-in (AuditSinkPort); records are inspectable post-run."""

    def __init__(self) -> None:
        self.events: list[object] = []

    def record(self, event: object) -> None:
        self.events.append(event)


class FakeAclAdapter:
    """Owner registry stand-in (AclPort): every golden LC is owned by the eval tenant.

    The offline gate measures detection quality, not authorization, so it grants the eval
    principal ownership of whatever LC a golden example names (so ``authorize_object``
    passes and the pipeline runs). The real fail-closed registry and the deny path are
    exercised by the unit + API tests, not here.
    """

    _OWNER = ObjectOwner(tenant="demo-bank", allowed_roles=frozenset({"group:trade-analyst"}))

    def owner(self, object_id: str) -> ObjectOwner | None:
        return self._OWNER


# The verified principal the offline gate runs as: an entitled demo-bank analyst.
_EVAL_PRINCIPAL = Principal(
    subject="eval-bot",
    principals=("group:trade-analyst",),
    tenant="demo-bank",
    source="eval",
)


class FakeLLMAdapter:
    """Deterministic narrative drafter (LLMPort), no model call.

    Returns a strict-JSON narrative for whatever schema the service asks for, so the
    service's ``parse_structured`` path is exercised. It cannot affect the verdict or the
    discrepancy set (those are deterministic), which is the point.
    """

    def __init__(self) -> None:
        self.model = "gemini-3.5-flash"

    def generate(self, request: LlmRequest) -> LlmResponse:
        payload = {"narrative": "Deterministic examiner narrative.", "cited_articles": []}
        return LlmResponse(
            text=json.dumps(payload),
            usage=TokenUsage(input_tokens=80, output_tokens=40, thinking_tokens=16),
            model=self.model,
        )

    def classify(self, text: str, labels: list[str]) -> str:
        return labels[0] if labels else ""


# --------------------------------------------------------------------------- #
# Pipeline driver : drive the real TradeCheckService.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class _Adapters:
    extraction: FakeExtractionAdapter
    rules: FakeRulesAdapter
    llm: FakeLLMAdapter
    guardrail: FakeGuardrailAdapter
    redaction: LocalRegexRedactionAdapter
    tracer: FakeTracer
    audit: FakeAuditSink
    acl: FakeAclAdapter


def _build_adapters() -> _Adapters:
    return _Adapters(
        extraction=FakeExtractionAdapter(),
        rules=FakeRulesAdapter(),
        llm=FakeLLMAdapter(),
        guardrail=FakeGuardrailAdapter(),
        redaction=_real_redactor(),
        tracer=FakeTracer(),
        audit=FakeAuditSink(),
        acl=FakeAclAdapter(),
    )


def _make_service(adapters: _Adapters):
    """Construct the real TradeCheckService (with a fixed as_of for determinism)."""
    from datetime import date

    from trade_finance_checker.domain.detector import DiscrepancyDetector
    from trade_finance_checker.domain.trade_check_service import TradeCheckService

    detector = DiscrepancyDetector(as_of=date(2026, 6, 15))
    return TradeCheckService(
        extraction=adapters.extraction,
        rules=adapters.rules,
        llm=adapters.llm,
        guardrail=adapters.guardrail,
        redaction=adapters.redaction,
        tracer=adapters.tracer,
        audit=adapters.audit,
        acl=adapters.acl,
        detector=detector,
    )


def _to_lc(data: dict) -> LetterOfCredit:
    return LetterOfCredit(
        lc_number=str(data.get("lc_number", "")),
        amount=float(data.get("amount", 0.0) or 0.0),
        currency=str(data.get("currency", "")),
        expiry_date=str(data.get("expiry_date", "")),
        latest_shipment=str(data.get("latest_shipment", "")),
        incoterm=str(data.get("incoterm", "")),
        beneficiary=str(data.get("beneficiary", "")),
        applicant=str(data.get("applicant", "")),
        terms={str(k): str(v) for k, v in (data.get("terms") or {}).items()},
    )


def _to_documents(items: list[dict]) -> list[PresentedDocument]:
    return [
        PresentedDocument(
            doc_type=TradeDocType(str(item.get("doc_type", "other"))),
            fields={str(k): str(v) for k, v in (item.get("fields") or {}).items()},
            pages=int(item.get("pages", 1) or 1),
            document_id=str(item.get("document_id", "")),
        )
        for item in items
    ]


def _with_pii(lc: LetterOfCredit, example: GoldenExample) -> LetterOfCredit:
    """Plant the case's OWN jurisdiction identifier in the trade parties (pii_safety).

    The parties are where this vertical's PII actually lives and where the pipeline actually
    redacts (``_redact_request`` builds the audited prompt from ``beneficiary`` /
    ``applicant`` plus the document fields), so that is where the fixture belongs. The
    detector never reads the party fields : it compares amounts, currencies, descriptions
    and dates : so planting PII here cannot move discrepancy_recall / precision /
    citation_accuracy, and pii_safety measures the boundary rather than the fixture.

    Each case carries its own market's identifier so the four configured packs are each
    exercised once, instead of the gate proving Singapore four times over.
    """
    if not example.pii_in_inputs:
        return lc
    market = example.jurisdiction.upper()
    fixture = _PII_BY_JURISDICTION.get(market)
    if fixture is None:
        # Loud, not silent: a case that claims to carry PII but has no fixture for its
        # jurisdiction would quietly test the universal rows only and look like real
        # per-market coverage.
        raise ValueError(
            f"golden case {example.id!r} sets pii_in_inputs in jurisdiction {market!r}, "
            "which has no fixture in _PII_BY_JURISDICTION. Add one so the case "
            "exercises that jurisdiction's pack."
        )
    if market not in _PII_JURISDICTIONS:
        # Scoring the leak check off the same pack as the redactor is what stops the two
        # drifting apart, but it also means a jurisdiction missing from the config blinds
        # BOTH at once: nothing masks the id, nothing detects it, and the case scores a
        # vacuous 1.0. Refuse to run rather than report that as coverage.
        raise ValueError(
            f"golden case {example.id!r} carries {market} PII but {market} is not in the "
            f"configured pack {_PII_JURISDICTIONS}. The redactor would not mask it and "
            "the leak check would not see it, so the case would score a vacuous 1.0. "
            "Add it to TRADE_FINANCE_PII_JURISDICTIONS or drop pii_in_inputs."
        )
    label, value = fixture
    return replace(
        lc,
        beneficiary=f"{lc.beneficiary}, {label} {value}",
        applicant=f"{lc.applicant}, account {_ACCOUNT_FIXTURE}, {_EMAIL_FIXTURE}",
    )


def check_example(service, adapters: _Adapters, example: GoldenExample) -> DiscrepancyReport:
    lc = _with_pii(_to_lc(example.lc), example)
    documents = _to_documents(example.documents)
    return service.check(lc, documents, principal=_EVAL_PRINCIPAL)


# --------------------------------------------------------------------------- #
# Heuristic scorers (the offline, credential-free metrics)
# --------------------------------------------------------------------------- #
def score_recall(report: DiscrepancyReport, example: GoldenExample) -> float:
    """Fraction of expected discrepancy kinds the detector actually found."""
    expected = set(example.expected_discrepancy_kinds)
    if not expected:
        return 1.0  # nothing to recall on a clean presentation
    found = {d.kind.value for d in report.discrepancies}
    return round(len(expected & found) / len(expected), 4)


def score_precision(report: DiscrepancyReport, example: GoldenExample) -> float:
    """No false discrepancies: every found kind must be an expected one.

    On a clean presentation (no expected kinds) any discrepancy is a false positive.
    """
    found = {d.kind.value for d in report.discrepancies}
    if not found:
        return 1.0  # nothing claimed -> no false positives
    expected = set(example.expected_discrepancy_kinds)
    return round(len(found & expected) / len(found), 4)


def score_citation_accuracy(report: DiscrepancyReport) -> float:
    """Every discrepancy must cite at least one UCP600 article or LC term."""
    if not report.discrepancies:
        return 1.0  # nothing to cite
    cited = sum(1 for d in report.discrepancies if d.citations and d.ucp600_article)
    return round(cited / len(report.discrepancies), 4)


def _pii_leak(text: str) -> bool:
    """True if any national id / email / phone / account number survives ``text``.

    Validator-gated for the same reason the redactor is, so what this detects is exactly
    what the redactor masks: the two read the same rows from ``domain/pii_patterns.py``.
    That shared source is what stops a bespoke detector and a bespoke redactor drifting
    apart, but on its own it can only catch PII the pipeline RE-INTRODUCED after redaction:
    it is blind by construction to anything the pack itself gets wrong, since a row that
    fails to match cannot detect what it failed to mask. :func:`_planted_pii_leak` is the
    independent half of the check.
    """
    for _info_type, pattern, validator in _PII_PATTERNS:
        for match in pattern.finditer(text or ""):
            if validator is None or validator(match.group(0)):
                return True
    return False


def _planted_pii_leak(text: str, example: GoldenExample) -> bool:
    """True if the identifier this case planted survives ``text`` verbatim.

    The pack-INDEPENDENT half of ``pii_safety``, and the half that makes the per-market
    claim real. A literal check is only tautological when the redactor is a fake that masks
    the same literals (which is exactly the failure mode this gate exists to prevent, and why it
    could never go red). Against the REAL redactor a literal is an oracle the pack has no say in:
    if a row is narrowed, mis-escaped or deleted outright, the redactor silently stops masking that
    market AND :func:`_pii_leak` silently stops detecting it, so only this check still fails.
    Without it a broken pack scores a vacuous 1.0 with the raw identifier sitting in the WORM
    audit record.
    """
    if not example.pii_in_inputs:
        return False
    _label, value = _PII_BY_JURISDICTION[example.jurisdiction.upper()]
    return any(token in (text or "") for token in (value, _ACCOUNT_FIXTURE, _EMAIL_FIXTURE))


def score_pii_safety(
    report: DiscrepancyReport, example: GoldenExample, audit_events: list
) -> float:
    """1.0 unless unredacted PII survived into the narrative or the audit records.

    Scans the produced narrative AND the already-redacted audit prompt/response two ways:
    with the same jurisdiction pattern source as the runtime redactor (catches PII the
    pipeline re-introduced), and for this case's own planted identifier (catches the pack
    being wrong, which the first check cannot see). A single surviving SG NRIC / HK HKID / JP
    My Number / AU TFN / email / account number drops the metric to 0.0, so the gate fails if
    anything bypassed the redact-before-everything boundary (R1, P-04).

    Both scanned surfaces are DERIVED, never an echo of the caller's input: the narrative is
    what the model produced and the audit records are what outlives the request. Scanning a
    field that simply repeats what the case planted would make the metric red whenever PII is
    injected no matter how well redaction worked, measuring the fixture instead of the
    boundary.
    """
    haystacks = [report.narrative]
    for event in audit_events:
        haystacks.append(str(getattr(event, "redacted_prompt", "")))
        haystacks.append(str(getattr(event, "redacted_response", "")))
    leaked = any(_pii_leak(hay) or _planted_pii_leak(hay, example) for hay in haystacks)
    return 0.0 if leaked else 1.0


# --------------------------------------------------------------------------- #
# Report assembly + presentation
# --------------------------------------------------------------------------- #
@dataclass
class _PerMetric:
    scores: list[float] = field(default_factory=list)

    @property
    def mean(self) -> float:
        return sum(self.scores) / len(self.scores) if self.scores else 0.0


def run_offline(dataset: Path, thresholds: dict[str, float]) -> EvalReport:
    examples = load_golden(dataset)
    adapters = _build_adapters()
    service = _make_service(adapters)

    agg: dict[str, _PerMetric] = {m: _PerMetric() for m in THRESHOLDS}
    print(
        f"Running offline eval gate over {len(examples)} golden presentations "
        f"(evaluator=TradeCheckService).\n"
    )
    for example in examples:
        before = len(adapters.audit.events)
        report = check_example(service, adapters, example)
        new_events = adapters.audit.events[before:]
        agg["discrepancy_recall"].scores.append(score_recall(report, example))
        agg["discrepancy_precision"].scores.append(score_precision(report, example))
        agg["citation_accuracy"].scores.append(score_citation_accuracy(report))
        agg["pii_safety"].scores.append(score_pii_safety(report, example, new_events))
        _verdict_note(report, example)

    results = tuple(
        EvalMetricResult(
            metric=metric,
            score=round(agg[metric].mean, 4),
            threshold=thresholds.get(metric, THRESHOLDS[metric]),
            passed=round(agg[metric].mean, 4) >= thresholds.get(metric, THRESHOLDS[metric]),
        )
        for metric in (
            "discrepancy_recall",
            "discrepancy_precision",
            "citation_accuracy",
            "pii_safety",
        )
    )
    return EvalReport(dataset=str(dataset), results=results, n_examples=len(examples))


def _verdict_note(report: DiscrepancyReport, example: GoldenExample) -> None:
    got = report.verdict.value
    want = example.expected_verdict
    mark = "ok" if got == want else "MISMATCH"
    print(
        f"  [{mark}] {example.id}: verdict {got} (expected {want}), "
        f"{report.discrepancy_count} discrepancies"
    )


def run_gate(dataset: Path) -> tuple[EvalReport, bool]:
    """Promotion verdict via EvaluationGatePort (platform = Hrz4, gcp = Gen AI evals).

    Fails closed on the reconciled evaluate + gate result. Refuses to run outside the
    platform/gcp profiles so the offline smoke result is never relabelled a promotion pass.
    """
    from trade_finance_checker.config import Settings, build_container

    settings = Settings.load()
    if settings.profile not in ("platform", "gcp"):
        raise SystemExit(
            "--mode gate is the promotion authority and requires "
            "TRADE_FINANCE_PROFILE=platform or gcp "
            f"(got {settings.profile!r}); run --mode smoke for the offline pre-merge check."
        )
    container = build_container(settings)
    gate = container.evaluation
    report = gate.evaluate(str(dataset))
    if not isinstance(report, EvalReport):  # pragma: no cover - defensive
        raise SystemExit("EvaluationGatePort.evaluate did not return an EvalReport")
    gate_passed = bool(gate.gate(str(dataset)))
    return report, gate_passed


def main(argv: list[str] | None = None) -> int:
    """Dispatch --mode via the shared eval_main scaffold (fail-closed exit codes).

    ``--use-gcp`` (the pre-split flag for the production evaluator) is kept as an alias
    for ``--mode gate``.
    """
    args = sys.argv[1:] if argv is None else list(argv)
    if "--use-gcp" in args:
        args = [a for a in args if a != "--use-gcp"] + ["--mode", "gate"]
    return eval_main(
        smoke=lambda dataset: run_offline(dataset, load_thresholds_from_rubrics()),
        gate=run_gate,
        default_dataset=DEFAULT_DATASET,
        description="Offline / platform evaluation gate for B4 (A4 / P-08).",
        smoke_label="offline heuristic (no GCP creds)",
        gate_label="promotion gate (EvaluationGatePort: Hrz4 / Gen AI evals)",
        argv=args,
    )


if __name__ == "__main__":
    raise SystemExit(main())
