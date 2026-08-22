"""RulesRetrievalPort : retrieve the governed UCP600 rule set (R3, via A2).

The UCP600 article set is not vendored into this repo; it is retrieved at runtime
from the central **A2 Enterprise Knowledge Base** (File Search over UCP600 articles)
via its ``POST /v1/search`` contract. The platform adapter is a thin HTTP client to
A2; the on-prem placeholder satisfies the same Protocol. Keeping the rule set in the
governed KB (rather than hard-coded) is the R3 dependency rule in action.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import Ucp600Rule


@runtime_checkable
class RulesRetrievalPort(Protocol):
    def retrieve_rules(self, query: str, top_k: int = 8) -> list[Ucp600Rule]:
        """Return the UCP600 articles most relevant to ``query`` (ranked)."""
        ...
