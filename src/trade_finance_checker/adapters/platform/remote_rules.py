"""Remote-platform rules adapter : thin HTTP client to the A2 Enterprise KB.

The UCP600 rule set is governed in the central **A2 Enterprise Knowledge Base** rather
than vendored into this repo (R3). This adapter implements :class:`RulesRetrievalPort` by
POSTing to A2's ``POST /v1/search`` endpoint (File Search over the UCP600 articles) and
mapping each returned passage into a domain :class:`Ucp600Rule`.

The adapter follows the B4 construction convention ``__init__(self, settings)`` and reads
its base URL from ``HRZ_KB_URL`` (localhost default), so nothing GCP-specific is required
to construct or exercise it. The ``acl_principals`` and collection come from settings so
retrieval respects the KB's access controls.
"""

from __future__ import annotations

import httpx

from ...config import Settings
from ...domain.errors import TradeFinanceError
from ...domain.models import Ucp600Rule
from ...envread import setting_or_default
from . import _s2s

_DEFAULT_URL = "http://localhost:8082"
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class RemoteRulesError(TradeFinanceError):
    """Raised when the remote A2 knowledge-base returns a non-2xx response."""


class RemoteRulesAdapter:
    """HTTP client for the A2 ``enterprise-knowledge-base`` search endpoint."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._kb = settings.rules_kb
        self._base_url = _s2s.validate_base_url(
            setting_or_default("HRZ_KB_URL", _DEFAULT_URL), service="rules knowledge base"
        )

    def retrieve_rules(self, query: str, top_k: int = 8) -> list[Ucp600Rule]:
        """Retrieve the most relevant UCP600 articles via A2 File Search."""
        payload = {
            "query": query,
            "top_k": top_k or self._kb.top_k,
            "acl_principals": list(self._kb.acl_principals),
            "filters": {"collection": self._kb.collection},
        }
        url = f"{self._base_url}/v1/search"
        try:
            response = httpx.post(url, json=payload, timeout=_TIMEOUT, headers=_s2s.headers())
        except httpx.HTTPError as exc:  # network / connection / timeout
            raise RemoteRulesError(f"A2 knowledge-base request to {url} failed: {exc}") from exc
        if response.status_code // 100 != 2:
            raise RemoteRulesError(
                f"A2 knowledge-base {url} returned {response.status_code}: {response.text[:500]}"
            )
        return self._parse_rules(response.json())

    @staticmethod
    def _parse_rules(body: dict) -> list[Ucp600Rule]:
        rules: list[Ucp600Rule] = []
        for passage in body.get("passages") or ():
            citation = passage.get("citation") or {}
            article = str(citation.get("article") or citation.get("source_id") or "").strip()
            if not article:
                continue
            rules.append(
                Ucp600Rule(
                    article=article,
                    title=str(citation.get("title") or article),
                    requirement=str(passage.get("text") or ""),
                    url=str(citation.get("url") or ""),
                    score=float(passage.get("score") or 0.0),
                )
            )
        return rules
