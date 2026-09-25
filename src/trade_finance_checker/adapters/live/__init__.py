"""``live`` profile adapters: the shared local model narrating deterministic checks.

Under live, the presentation data is whatever the audience submits, every discrepancy
verdict comes from the deterministic detector, and only the report prose is generated, by
the fleet's local open-weight model through :mod:`hex_service_kit.localmodel`. Everything
else reuses the SDK-free local adapters.
"""
