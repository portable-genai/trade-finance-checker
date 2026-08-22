"""FastAPI dependency wiring for the B4 Trade-Finance Document Checker.

This module builds a single, process-wide :class:`~trade_finance_checker.config.Container`
(the ports-and-adapters registry) and assembles the orchestration service from the
Container's port instances. The Container is created lazily on first access so importing
this module : and therefore the FastAPI app : never touches Google Cloud: a unit test or
the on-prem profile can import the API with no GCP SDK installed.

Each ``get_*`` factory is a FastAPI ``Depends`` provider. The service takes *explicit port
instances* in its constructor (SPEC §5), so the wiring here is the single place that knows
which ports the service needs.
"""

from __future__ import annotations

from functools import lru_cache

from ..config import Container, Settings, build_container
from ..domain.detector import DiscrepancyDetector
from ..domain.services import TradeCheckService


@lru_cache(maxsize=1)
def get_container() -> Container:
    """Return the process-wide Container, building it on first use.

    Cached for the lifetime of the process so every request shares one set of adapter
    instances. ``Settings.load()`` reads ``config/settings.yaml`` with ``${ENV_VAR}``
    interpolation and selects the active profile.
    """
    return build_container(Settings.load())


def get_settings() -> Settings:
    """Convenience accessor for the active settings (region, profile, tolerances...)."""
    return get_container().settings


# --------------------------------------------------------------------------- #
# Service factories : assemble the service from the Container's ports.
# Constructor argument order mirrors SPEC §5 exactly.
# --------------------------------------------------------------------------- #
def get_trade_check_service() -> TradeCheckService:
    """TradeCheckService(extraction, rules, llm, guardrail, redaction, tracer, audit, acl)."""
    return build_trade_check_service(get_container())


def build_trade_check_service(container: Container) -> TradeCheckService:
    """Assemble a :class:`TradeCheckService` from an explicit Container.

    The ``get_*`` factory above uses the cached, process-wide Container (right for the
    long-lived FastAPI app). The CLI and the ADK tools instead build their own Container
    per invocation : honouring ``TRADE_FINANCE_PROFILE`` at call time : so they call this
    ``build_*`` variant with an explicit Container.
    """
    return TradeCheckService(
        extraction=container.extraction,
        rules=container.rules,
        llm=container.llm,
        guardrail=container.guardrail,
        redaction=container.redaction,
        tracer=container.tracer,
        audit=container.audit,
        acl=container.acl,
        review_router=container.review_router,
        detector=DiscrepancyDetector(
            amount_tolerance_pct=container.settings.check.amount_tolerance_pct,
            description_min_overlap=container.settings.check.description_min_overlap,
        ),
    )


def create_app():  # -> fastapi.FastAPI
    """App factory used by ``uvicorn ... --factory`` so each worker imports cleanly."""
    from .app import app

    return app
