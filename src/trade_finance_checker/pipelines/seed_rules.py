"""Seed helper for the governed UCP600 rule set in the A2 Enterprise Knowledge Base.

B4 retrieves the UCP600 articles at runtime from A2 (R3) rather than vendoring them. This
module reads the article registry (``sources/registry.yaml``) and produces the list of
article references the A2 collection should contain, so an operator can verify the governed
KB is aligned with the deterministic detector's article tags.

It performs no ingestion itself (ingestion is an A2 concern); it is a small, dependency-light
helper used by the runbook and the corpus-refresh workflow to list the expected articles.
Pure standard library plus PyYAML.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_REGISTRY = Path(__file__).resolve().parent / "sources" / "registry.yaml"


def load_registry(path: str | Path | None = None) -> dict[str, Any]:
    """Load the UCP600 article registry as a plain dict."""
    p = Path(path or _REGISTRY)
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def expected_articles(path: str | Path | None = None) -> list[str]:
    """Return the article references the A2 ``ucp600-rules`` collection should contain."""
    registry = load_registry(path)
    return [
        str(a.get("article", "")).strip() for a in registry.get("articles", []) if a.get("article")
    ]


def main() -> int:  # pragma: no cover - operator convenience entry point
    articles = expected_articles()
    print(f"A2 collection: {load_registry().get('collection', 'ucp600-rules')}")
    print(f"Expected UCP600 articles ({len(articles)}):")
    for article in articles:
        print(f"  - {article}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
