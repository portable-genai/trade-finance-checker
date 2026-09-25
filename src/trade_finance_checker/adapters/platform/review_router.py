"""Platform ReviewRouterPort: submit the routed report review to human-review-console via
``review-kit``.

Builds the review from the escalated discrepancy report and submits it to the
human-review-console service intake (``POST /v1/service/reviews``). The human-review-console
base URL comes from the environment (``HUMAN_REVIEW_URL``). It is bound under the ``gcp`` and
``platform`` profiles because it makes a real network call to a sibling service.

**Two bearers, chosen by one variable.** A deployed human-review-console is an embedded app
behind the portal's IAP edge, so under ``gcp`` ``HUMAN_REVIEW_URL`` is the edge path
``https://<edge-host>/apps/human-review-console/api`` and the edge accepts one bearer: a
Google-signed ID token minted for the deployment's IAP OAuth client id, named by
``HUMAN_REVIEW_IAP_AUDIENCE``. When that variable is set, the router hands ``review-kit`` a
bearer provider that mints such a token with this service's own workload identity, once per
submission, so an expiring token is never reused. When it is unset, the router keeps the static
S2S path: the bearer comes from this repo's shared env-var names (``S2S_TOKEN`` /
``S2S_SIGNING_KEY``, the same pair the other platform delegates use). Boot refuses ``gcp`` with
routing on and no audience (see ``config._refuse_unreachable_console``), so the static path is
what ``platform`` and a directly reached console use.

The minting import is lazy, so this module still imports with no Google SDK installed.
"""

from __future__ import annotations

from collections.abc import Callable

from review_kit import ReviewClient
from review_kit.client import Transport

from ...config import Settings, review_iap_audience
from ...domain.models import DiscrepancyReport
from ...envread import required_setting
from .._review_payload import report_to_review
from ._s2s import SIGNING_KEY_ENV, TOKEN_ENV

_URL_ENV = "HUMAN_REVIEW_URL"

#: Mints a Google-signed ID token for an audience. Injectable so tests never reach a metadata
#: server; the default uses this service's own workload identity.
Minter = Callable[[str], str]


def fetch_id_token(audience: str) -> str:  # pragma: no cover - needs a workload identity
    """Mint a Google-signed ID token for ``audience`` with this process's own identity."""
    from google.auth.transport.requests import Request
    from google.oauth2.id_token import fetch_id_token as _fetch

    token: str = _fetch(Request(), audience)
    return token


class PlatformReviewRouter:
    """Submit escalated discrepancy reports to human-review-console (rule R8), reusing the shared
    client.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        mint: Minter | None = None,
        transport: Transport | None = None,
    ) -> None:
        self._settings = settings
        # Read at construction, which the container does at boot beside the boot check, so an
        # emptied or backend-path audience is a named refusal, not a failed hand-off per report.
        self._audience = review_iap_audience()
        self._mint = mint or fetch_id_token
        self._transport = transport

    def _client(self) -> ReviewClient:
        base_url = required_setting(_URL_ENV)
        audience = self._audience
        if audience is None:
            return ReviewClient(
                base_url,
                token_env=TOKEN_ENV,
                signing_key_env=SIGNING_KEY_ENV,
                transport=self._transport,
            )
        mint = self._mint
        return ReviewClient(
            base_url,
            token_env=TOKEN_ENV,
            signing_key_env=SIGNING_KEY_ENV,
            transport=self._transport,
            bearer_provider=lambda: mint(audience),
        )

    def route(self, report: DiscrepancyReport, *, maker: str, tenant: str = "") -> None:
        self._client().submit(
            report_to_review(report, maker=maker, tenant=tenant), actor="doc4-trade-finance-checker"
        )
