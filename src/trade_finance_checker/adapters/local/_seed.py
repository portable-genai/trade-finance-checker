"""Built-in UCP600 rule set for the ``local`` and ``live`` profiles.

Real article numbers and titles, paraphrased requirement summaries. The full text of
UCP 600 is an ICC-copyrighted publication, so it is deliberately NOT vendored or
fetched: each rule paraphrases the article's requirement in this project's own words
and cites the article number with the official ICC publication page as the reference
URL, so a reviewer can verify against the licensed text. The article references mirror
the article tags the deterministic :class:`DiscrepancyDetector` uses, so the rule set
stays aligned with the detector.

This mirrors ``tests/fixtures/sample_trade.SAMPLE_RULES`` so the local adapters and the
unit-test fixtures share one deterministic rule set, but it lives under ``src`` (not
``tests``) so the shipped package can seed itself without importing the test tree.
"""

from __future__ import annotations

from ...domain.models import Ucp600Rule

#: The official ICC publication page for UCP 600 (the licensed full text). Every rule
#: cites it as the verification reference; the requirement strings below are this
#: project's own paraphrases, not the ICC text.
ICC_UCP600_URL = (
    "https://2go.iccwbo.org/ucp-600-uniform-rules-for-documentary-credits"
    "-config-1+book_version-Book/"
)

# A small, deterministic governed rule set. Articles match the detector's article tags.
SEED_RULES: tuple[Ucp600Rule, ...] = (
    Ucp600Rule(
        article="UCP600 Art. 6",
        title="Availability, expiry date and place for presentation",
        requirement="A presentation must be made on or before the expiry date of the credit.",
        url=ICC_UCP600_URL,
        score=0.90,
    ),
    Ucp600Rule(
        article="UCP600 Art. 14",
        title="Standard for examination of documents",
        requirement="Data in a document must not conflict with the credit or other documents.",
        url=ICC_UCP600_URL,
        score=0.95,
    ),
    Ucp600Rule(
        article="UCP600 Art. 18",
        title="Commercial invoice",
        requirement="The invoice amount must not exceed the credit amount and currency must match.",
        url=ICC_UCP600_URL,
        score=0.92,
    ),
    Ucp600Rule(
        article="UCP600 Art. 19",
        title="Transport document covering at least two modes of transport",
        requirement="The shipment date must be on or before the latest shipment date stated.",
        url=ICC_UCP600_URL,
        score=0.87,
    ),
    Ucp600Rule(
        article="UCP600 Art. 28",
        title="Insurance document and coverage",
        requirement="Insurance must cover at least 110% of the CIF or CIP value of the goods.",
        url=ICC_UCP600_URL,
        score=0.88,
    ),
)
