"""Contract tests: the ``onprem`` and ``local`` adapters are structural parity of the ports.

For every port the catalog declares, this iterates the adapter map and, for both the
``onprem`` and ``local`` profiles, imports + constructs the bound class (which must build
cleanly with **no Google Cloud SDK** installed), then asserts:

  1. the constructed instance satisfies its runtime_checkable Protocol (isinstance), and
  2. every method/property the Protocol declares actually exists on the instance.

It additionally proves the two profiles' distinct contracts:

* ``onprem`` is the fail-fast Google Distributed Cloud migration target: every method
  raises ``NotImplementedError`` (proven on a representative port), and
* ``local`` is a WORKING offline stack: the same ports construct and answer in-process.

This is the proof of the ports-and-adapters / no-lock-in promise (P-02): the on-prem
migration target and the offline local stack implement the exact same interface as the
managed GCP stack.
"""

from __future__ import annotations

from typing import Protocol, get_type_hints

import pytest

from trade_finance_checker import config, ports
from trade_finance_checker.config import LocalSettings, Settings, instantiate

CONFIG_PATH = "config/settings.yaml"

# Every port name in settings.adapters mapped to its Protocol.
PORT_PROTOCOLS: dict[str, type] = {
    "extraction": ports.DocumentExtractionPort,
    "rules": ports.RulesRetrievalPort,
    "llm": ports.LLMPort,
    "guardrail": ports.GuardrailPort,
    "redaction": ports.PIIRedactionPort,
    "agent_runtime": ports.AgentRuntimePort,
    "session": ports.SessionPort,
    "memory": ports.MemoryPort,
    "audit": ports.AuditSinkPort,
    "tracer": ports.ObservabilityTracerPort,
    "evaluation": ports.EvaluationGatePort,
    "registry": ports.AgentRegistryPort,
    "tool_catalog": ports.ToolCatalogPort,
    "identity": ports.IdentityPort,
    "acl": ports.AclPort,
    "review_router": ports.ReviewRouterPort,
}

# Profiles whose adapters must construct + satisfy the Protocols with no GCP SDK.
# ``live`` is SDK-free too: a local model server over httpx; an unbound live port
# would silently fall back to a managed GCP adapter.
SDK_FREE_PROFILES = ("onprem", "local", "live")


def _settings(profile: str) -> Settings:
    base = Settings.load(CONFIG_PATH)
    # Point the local stores at in-memory SQLite so the contract test stays ephemeral.
    return Settings(
        project_id=base.project_id,
        region=base.region,
        profile=profile,
        kms_key=base.kms_key,
        models=base.models,
        document_ai=base.document_ai,
        rules_kb=base.rules_kb,
        model_armor=base.model_armor,
        dlp=base.dlp,
        logging=base.logging,
        agent_engine=base.agent_engine,
        check=base.check,
        local=LocalSettings(rules_db_path=":memory:", audit_path=":memory:"),
        adapters=base.adapters,
    )


def _protocol_members(protocol: type) -> set[str]:
    """The attribute names a Protocol declares (methods + properties), no dunders."""
    members = set(getattr(protocol, "__protocol_attrs__", set()))
    if not members:
        # Fallback for older typing internals: union of annotations + callables.
        members |= set(get_type_hints(protocol).keys())
        for name in dir(protocol):
            if name.startswith("_"):
                continue
            members.add(name)
    return {m for m in members if not m.startswith("_")}


def test_port_protocols_matches_settings_adapters():
    """The hand-maintained PORT_PROTOCOLS map must EQUAL the ports bound in settings.

    This is the drift guard, and it fails LOUDLY on either direction of drift:

    * forward drift - a port bound in ``config/settings.yaml`` under ``adapters:`` but
      absent from ``PORT_PROTOCOLS`` gets ZERO parity / constructor / onprem-binding
      enforcement (the parametrized suites iterate ``PORT_PROTOCOLS``, so an unmapped
      port is silently untested with a green CI);
    * reverse drift - a port in ``PORT_PROTOCOLS`` with no ``adapters:`` binding would
      never be reachable through the container.

    A subset check (``set(PORT_PROTOCOLS) <= set(settings.adapters)``) catches only the
    second; set-equality here catches both, so a fork that adds a port Protocol and binds
    it in settings but forgets the ``PORT_PROTOCOLS`` entry (or vice versa) fails CI.
    """
    settings = Settings.load(CONFIG_PATH)
    bound = set(settings.adapters)
    declared = set(PORT_PROTOCOLS)
    missing_from_map = bound - declared
    missing_from_settings = declared - bound
    assert not missing_from_map, (
        f"ports bound in settings.adapters but absent from PORT_PROTOCOLS "
        f"(so untested): {sorted(missing_from_map)}. Add them to the parity map."
    )
    assert not missing_from_settings, (
        f"ports in PORT_PROTOCOLS with no settings.adapters binding: "
        f"{sorted(missing_from_settings)}."
    )


def test_every_port_has_an_explicit_binding_for_every_profile():
    settings = Settings.load(CONFIG_PATH)
    for port_name in PORT_PROTOCOLS:
        binding = settings.adapters.get(port_name, {})
        missing = set(config.RUNTIME_PROFILES) - set(binding)
        assert not missing, f"port '{port_name}' has no explicit bindings for {sorted(missing)}"


@pytest.mark.parametrize("profile", SDK_FREE_PROFILES)
@pytest.mark.parametrize("port_name", sorted(PORT_PROTOCOLS))
def test_adapter_satisfies_protocol(profile: str, port_name: str):
    settings = _settings(profile)
    protocol = PORT_PROTOCOLS[port_name]
    dotted = settings.adapters[port_name][profile]

    # Import + construct with only Settings (the adapter convention), no GCP SDK.
    adapter = instantiate(dotted, settings)

    # 1. Structural conformance via runtime_checkable Protocol.
    assert isinstance(adapter, protocol), (
        f"{dotted} does not structurally satisfy {protocol.__name__}"
    )

    # 2. Every declared Protocol member exists. Check on the *class* (via the MRO), not the
    #    instance: a placeholder property getter may raise, so ``hasattr`` would wrongly
    #    report it missing. Looking the name up on the type tests for declaration without
    #    invoking the getter.
    members = _protocol_members(protocol)
    declared = set().union(*(vars(klass) for klass in type(adapter).__mro__))
    for member in members:
        assert member in declared, (
            f"{dotted} is missing port method/attr '{member}' of {protocol.__name__}"
        )


@pytest.mark.parametrize("profile", SDK_FREE_PROFILES)
@pytest.mark.parametrize("port_name", sorted(PORT_PROTOCOLS))
def test_adapter_constructs_with_single_settings_arg(profile: str, port_name: str):
    """The build contract: every adapter is ``Adapter(settings: Settings)``."""
    settings = _settings(profile)
    dotted = settings.adapters[port_name][profile]
    module_path, _, class_name = dotted.partition(":")
    import importlib

    cls = getattr(importlib.import_module(module_path), class_name)
    instance = cls(settings)
    assert instance is not None


def test_onprem_rules_fails_fast():
    """The on-prem stubs are fail-fast: a representative port raises NotImplementedError."""
    settings = _settings("onprem")
    adapter = instantiate(settings.adapters["rules"]["onprem"], settings)

    with pytest.raises(NotImplementedError):
        adapter.retrieve_rules("anything")


def test_local_rules_returns_real_articles():
    """The local stack is WORKING: rules retrieval returns real, cited UCP600 articles."""
    settings = _settings("local")
    adapter = instantiate(settings.adapters["rules"]["local"], settings)

    rules = adapter.retrieve_rules("commercial invoice amount currency examination", top_k=8)
    assert rules, "local FTS5 rules retrieval returned nothing for the seeded rule set"
    assert all(r.article for r in rules), "every governed rule must carry an article reference"


def test_all_protocols_are_runtime_checkable():
    for protocol in PORT_PROTOCOLS.values():
        assert issubclass(protocol, Protocol)  # type: ignore[arg-type]
        assert getattr(protocol, "_is_runtime_protocol", False), (
            f"{protocol.__name__} must be @runtime_checkable"
        )


def test_the_shared_types_are_the_commons_objects_not_look_alikes():
    """The drift guard that no structural test can provide.

    Every check above this one passes just as happily against a hand-copied Protocol as
    against the shared one: ``isinstance`` on a ``runtime_checkable`` Protocol asks only
    whether the methods exist, and ``issubclass`` asks only that it is a Protocol. That is
    exactly how sixteen copies of these types drifted apart while every repo's contract suite
    stayed green. ``is`` cannot be fooled that way, so it is what is asserted here: if anyone
    redeclares one of these locally, this test fails on the next run instead of years later
    when two repos disagree about what a token count or a promotion record means.
    """
    import agent_eval_kit
    import hex_service_kit.identity
    import hex_service_kit.observability
    from agent_eval_kit import report as eval_report

    from trade_finance_checker.domain import models

    assert ports.ObservabilityTracerPort is hex_service_kit.observability.ObservabilityTracerPort
    assert ports.TokenUsage is hex_service_kit.observability.TokenUsage
    assert ports.EvaluationGatePort is agent_eval_kit.EvaluationGatePort
    assert ports.IdentityPort is hex_service_kit.identity.IdentityPort

    assert models.TokenUsage is hex_service_kit.observability.TokenUsage
    assert models.EvalReport is eval_report.EvalReport
    assert models.EvalMetricResult is eval_report.EvalMetricResult

    from trade_finance_checker.domain import identity

    assert identity.Principal is hex_service_kit.identity.Principal
    assert identity.RequestContext is hex_service_kit.identity.RequestContext
    assert identity.IdentityError is hex_service_kit.identity.IdentityError
    assert identity.ANONYMOUS is hex_service_kit.identity.ANONYMOUS


def test_the_eval_report_gate_still_fails_closed_after_the_move():
    """Re-exporting a type whose guard is WEAKER than the local one silently removes it.

    This repo's ``EvalReport.passed`` refused a report with no examples and a report with no
    metric rows, because ``all(())`` is vacuously True and ``eval/run_eval.py`` exits 0 on
    this property. The commons property carries the identical rule; this asserts that rather
    than trusting the read of it.
    """
    from trade_finance_checker.domain.models import EvalMetricResult, EvalReport

    row = EvalMetricResult(metric="discrepancy_recall", score=1.0, threshold=0.9, passed=True)
    assert EvalReport(dataset="d", results=(), n_examples=0).passed is False
    assert EvalReport(dataset="d", results=(), n_examples=12).passed is False
    assert EvalReport(dataset="d", results=(row,), n_examples=0).passed is False
    assert EvalReport(dataset="d", results=(row,), n_examples=12).passed is True


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
