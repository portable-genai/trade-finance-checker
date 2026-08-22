"""On-prem placeholder for ``RulesRetrievalPort`` : the Google Distributed Cloud target.

One of the reversibility (P-02, P-12) migration placeholders: in the managed/platform
profile this port binds to the A2 Enterprise KB remote client; switching ``profile`` to
``onprem`` rebinds it here. The adapter constructs cleanly with **no external
dependencies** and structurally satisfies the same Protocol as the managed adapter, so the
contract tests prove interface parity. Porting the governed UCP600 rule set to an
on-premise knowledge base is *only* a matter of filling this body in : the domain is
unchanged.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import Ucp600Rule

_MESSAGE = (
    "On-prem RulesRetrievalPort adapter is a migration placeholder; implement against your "
    "on-premise platform. Core domain logic is unchanged."
)


class OnPremRulesAdapter:
    """Placeholder UCP600 rules adapter for the on-prem (Google Distributed Cloud) profile."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def retrieve_rules(self, query: str, top_k: int = 8) -> list[Ucp600Rule]:
        raise NotImplementedError(_MESSAGE)
