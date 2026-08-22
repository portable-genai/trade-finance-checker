"""Runnable demo of the B4 trade-finance discrepancy check (synthetic, fictional data).

Drives a single documentary-credit presentation through three rounds as the beneficiary
corrects discrepancies against the bank's examination advice:

    Round 0  first presentation        -> DISCREPANT, several discrepancies, advice issued
    Round 1  corrected invoice + B/L    -> DISCREPANT, fewer discrepancies remain
    Round 2  amended set + insurance    -> COMPLIANT, ready for officer release decision
    Review   trade-finance officer      -> maker-checker (P-06) release recorded

Run it::

    PYTHONPATH=src:tests python scripts/trade_finance_demo.py [out.json]

It prints a per-round summary and writes the full report JSON (one entry per round) for
the static renderer / live server to display. No cloud, no LLM, no API key: the detector
is deterministic and the narrator is the offline default adapter.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from trade_finance_checker.api.deps import build_trade_check_service
from trade_finance_checker.config import Settings, build_container
from trade_finance_checker.domain.identity import Principal
from trade_finance_checker.domain.models import (
    LetterOfCredit,
    PresentedDocument,
    TradeDocType,
)
from trade_finance_checker.domain.serialization import to_jsonable

ACTOR = "rm.tan@bank.test"
OFFICER = "tf.officer.lim@bank.test"

# The verified principal the demo runs as: an entitled demo-bank relationship manager. The
# domain service enforces object-level authorization, so callers pass a full Principal (the
# audit actor is derived from its subject); the demo LC is demo-bank owned.
PRINCIPAL = Principal(
    subject=ACTOR,
    principals=("group:trade-analyst", "group:trade-finance"),
    tenant="demo-bank",
    source="demo",
)

# The documentary credit under which every round is presented. Fictional parties.
LC = LetterOfCredit(
    lc_number="LC-DEMO-2026-0917",
    amount=120000.00,
    currency="USD",
    expiry_date="2026-06-30",
    latest_shipment="2026-05-31",
    incoterm="CIF",  # CIF => the beneficiary must present an insurance document
    beneficiary="Fictional Exporters Pte Ltd",  # PII : redacted at the boundary (P-04)
    applicant="Imaginary Importers Co",  # PII : redacted at the boundary (P-04)
    terms={
        "goods_description": "1000 cartons of organic arabica coffee beans grade A",
        "documents_required": "invoice, bill_of_lading, insurance",
    },
)

# Each round: (label, what the beneficiary presented this round). Rounds are weeks apart
# as the beneficiary responds to the bank's discrepancy advice.
ROUNDS: list[tuple[str, list[PresentedDocument]]] = [
    (
        "First presentation",
        [
            PresentedDocument(
                doc_type=TradeDocType.INVOICE,
                fields={
                    "amount": "138500.00",  # exceeds LC 120000 -> AMOUNT_MISMATCH
                    "currency": "EUR",  # != USD -> INCONSISTENT_DATA
                    "goods_description": "assorted dried agricultural produce",  # mismatch
                    "issue_date": "2026-05-18",
                },
                pages=1,
                document_id="inv-r0",
            ),
            PresentedDocument(
                doc_type=TradeDocType.BILL_OF_LADING,
                fields={
                    "shipment_date": "2026-06-08",  # after latest_shipment -> LATE_SHIPMENT
                    "goods_description": "assorted dried agricultural produce",
                },
                pages=2,
                document_id="bl-r0",
            ),
            # No insurance document though incoterm is CIF -> MISSING_DOCUMENT.
        ],
    ),
    (
        "Corrected invoice and transport",
        [
            PresentedDocument(
                doc_type=TradeDocType.INVOICE,
                fields={
                    "amount": "118400.00",  # now within the LC amount
                    "currency": "USD",  # currency now matches
                    "goods_description": "1000 cartons organic arabica coffee beans grade A",
                    "issue_date": "2026-05-22",
                },
                pages=1,
                document_id="inv-r1",
            ),
            PresentedDocument(
                doc_type=TradeDocType.BILL_OF_LADING,
                fields={
                    "shipment_date": "2026-05-26",  # now on or before latest_shipment
                    "goods_description": "1000 cartons organic arabica coffee beans grade A",
                },
                pages=2,
                document_id="bl-r1",
            ),
            # Insurance still not presented -> MISSING_DOCUMENT remains for CIF.
        ],
    ),
    (
        "Amended set with insurance",
        [
            PresentedDocument(
                doc_type=TradeDocType.INVOICE,
                fields={
                    "amount": "118400.00",
                    "currency": "USD",
                    "goods_description": "1000 cartons organic arabica coffee beans grade A",
                    "issue_date": "2026-05-22",
                },
                pages=1,
                document_id="inv-r2",
            ),
            PresentedDocument(
                doc_type=TradeDocType.BILL_OF_LADING,
                fields={
                    "shipment_date": "2026-05-26",
                    "goods_description": "1000 cartons organic arabica coffee beans grade A",
                },
                pages=2,
                document_id="bl-r2",
            ),
            PresentedDocument(
                doc_type=TradeDocType.INSURANCE,
                fields={
                    # >= 110% of the LC value (132000) per UCP600 Art. 28(f).
                    "insured_amount": "132500.00",
                    "currency": "USD",
                    "goods_description": "1000 cartons organic arabica coffee beans grade A",
                },
                pages=1,
                document_id="ins-r2",
            ),
        ],
    ),
]


def _build_service():
    os.environ.setdefault("TRADE_FINANCE_PROFILE", "local")
    container = build_container(Settings.load())
    return build_trade_check_service(container), container.settings.profile


def main(out_path: str) -> None:
    service, profile = _build_service()
    payload: dict = {
        "lc": to_jsonable(LC),
        "profile": profile,
        "actor": ACTOR,
        "officer": OFFICER,
        "rounds": [],
    }

    print(f"Examining presentation under {LC.lc_number} for {LC.beneficiary} (profile={profile})\n")
    for no, (label, documents) in enumerate(ROUNDS):
        report = service.check(LC, documents, principal=PRINCIPAL)
        verdict = report.verdict.value
        print(f"-- Round {no}  ({label})  verdict={verdict.upper()}")
        print(f"   presented: {', '.join(d.doc_type.value for d in documents)}")
        print(f"   discrepancies: {report.discrepancy_count} ({report.material_count} material)")
        for d in report.discrepancies:
            print(f"     - [{d.kind.value}] ({d.severity.value}) {d.doc_type.value}.{d.field}")
        print()
        payload["rounds"].append(
            {
                "no": no,
                "label": label,
                "presented": [d.doc_type.value for d in documents],
                "report": to_jsonable(report),
            }
        )

    # Round 2 is clean: a trade-finance officer takes the maker-checker release decision.
    final = payload["rounds"][-1]["report"]
    released = final["verdict"] == "compliant"
    payload["officer_decision"] = {
        "officer": OFFICER,
        "maker": ACTOR,
        "decision": "release" if released else "refuse",
        "basis": (
            "Compliant on its face after re-presentation; complying presentation honoured "
            "under the credit."
            if released
            else "Discrepancies outstanding; refusal / waiver-request per UCP600 Art. 16."
        ),
    }
    print(
        f"Officer {OFFICER} (four-eyes; maker was {ACTOR}) "
        f"recorded decision: {payload['officer_decision']['decision'].upper()}."
    )

    parent = Path(out_path).parent
    if parent and not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    print(f"\nWrote report JSON -> {out_path}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "trade_finance_demo.json")
