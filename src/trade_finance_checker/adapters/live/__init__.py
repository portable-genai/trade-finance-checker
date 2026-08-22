"""``live`` profile adapters: a local model server narrating deterministic checks.

Under live, the presentation data is whatever the audience submits, every
discrepancy verdict comes from the deterministic detector, and only the report
prose is generated, on a local OpenAI-compatible model server. Everything else
reuses the SDK-free local adapters.
"""
