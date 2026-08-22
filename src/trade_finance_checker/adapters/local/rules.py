"""Local rules-retrieval adapter (RulesRetrievalPort) : SQLite FTS5 over UCP600 articles.

The ``local`` profile's stand-in for the **A2 Enterprise Knowledge Base** File Search
over the governed UCP600 rule set: a ``sqlite3`` database with an **FTS5** virtual table
over the article requirements, queried with BM25 (``ORDER BY rank``). It is SDK-free,
deterministic and **seedable**, so the same code grounds the offline CLI run and the unit
tests. Under ``local`` this platform client uses an in-process FTS5 index rather than HTTP
to the A2 sibling service (a laptop runs one app, not the whole platform).

The adapter returns the same :class:`Ucp600Rule` objects with article references and
governed titles/urls as the remote adapter, preserving interface parity. It self-seeds
from the built-in synthetic rule set on first use so an out-of-the-box local run grounds
citations without any ingestion step; callers may also ``seed(rules)`` a set of their own.

Default DB path is under a per-package local dir (``~/.trade_finance_checker/rules.db``);
tests pass ``:memory:`` for an ephemeral, deterministic index.
"""

from __future__ import annotations

import re
import sqlite3
import threading
from pathlib import Path

from ...config import Settings
from ...domain.models import Ucp600Rule
from ._seed import SEED_RULES

# Default on-disk location for the local index (overridable via settings.local.rules_db_path).
_DEFAULT_DB_DIR = Path.home() / ".trade_finance_checker"
_DEFAULT_DB_PATH = _DEFAULT_DB_DIR / "rules.db"

# FTS5 query syntax is strict; keep only word characters so a free-text query never trips
# an "fts5: syntax error" (e.g. on punctuation), and OR the terms for recall.
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


class LocalFtsRulesAdapter:
    """Retrieve governed UCP600 articles from a local SQLite FTS5 index (BM25 ranked)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        db_path = getattr(getattr(settings, "local", None), "rules_db_path", "") or str(
            _DEFAULT_DB_PATH
        )
        self._db_path = db_path
        # check_same_thread=False + a lock keeps the store usable from the FastAPI thread
        # pool (sync endpoints run on Starlette's threadpool while the container is a
        # process-wide singleton), with the lock serialising every access (single-writer).
        self._lock = threading.Lock()
        self._conn = self._connect(db_path)
        self._init_schema()
        # Self-seed the built-in rule set so an out-of-the-box local run is grounded.
        # Re-seed too when the store holds a RETIRED rule set: the index lives on disk
        # and outlives the code, so an upgrade that changes the shipped rules (the
        # citation URLs moved from a fictional host to the official ICC publication
        # page) would otherwise keep citing the old ones forever.
        if self._is_empty() or self._holds_retired_rules():
            self.seed(SEED_RULES)

    def _holds_retired_rules(self) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT count(*) AS n FROM rules WHERE url LIKE ?", ("https://example.test/%",)
            ).fetchone()
        return int(row["n"]) > 0

    # ------------------------------------------------------------------ #
    # Connection / schema
    # ------------------------------------------------------------------ #
    @staticmethod
    def _connect(db_path: str) -> sqlite3.Connection:
        if db_path not in (":memory:", "") and not db_path.startswith("file:"):
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        # One FTS5 table holds the searchable requirement text; the article metadata rides
        # alongside as UNINDEXED columns so a single query returns everything needed to cite.
        with self._lock:
            self._conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS rules USING fts5(
                    requirement,
                    title,
                    article UNINDEXED,
                    url UNINDEXED,
                    score UNINDEXED
                )
                """
            )
            self._conn.commit()

    def _is_empty(self) -> bool:
        with self._lock:
            row = self._conn.execute("SELECT count(*) AS n FROM rules").fetchone()
        return int(row["n"]) == 0

    # ------------------------------------------------------------------ #
    # Seeding
    # ------------------------------------------------------------------ #
    def seed(self, rules: tuple[Ucp600Rule, ...] | list[Ucp600Rule]) -> int:
        """Replace the index contents with ``rules`` (deterministic test/CLI seed)."""
        with self._lock:
            self._conn.execute("DELETE FROM rules")
        return self._insert(list(rules))

    def add(self, rules: list[Ucp600Rule]) -> int:
        """Append ``rules`` to the index without clearing existing rows."""
        return self._insert(rules)

    def _insert(self, rules: list[Ucp600Rule]) -> int:
        rows = [(r.requirement, r.title, r.article, r.url, f"{r.score:.6f}") for r in rules]
        with self._lock:
            self._conn.executemany(
                "INSERT INTO rules (requirement, title, article, url, score) "
                "VALUES (?, ?, ?, ?, ?)",
                rows,
            )
            self._conn.commit()
        return len(rows)

    # ------------------------------------------------------------------ #
    # RulesRetrievalPort
    # ------------------------------------------------------------------ #
    def retrieve_rules(self, query: str, top_k: int = 8) -> list[Ucp600Rule]:
        """Return the UCP600 articles most relevant to ``query`` (BM25 ranked)."""
        match = self._build_match(query)
        with self._lock:
            if not match:
                # No usable query terms: fall back to a score-ordered scan so the pipeline
                # still gets the governed set rather than an FTS5 syntax error.
                cursor = self._conn.execute(
                    "SELECT * FROM rules ORDER BY score DESC LIMIT ?", (max(top_k, 1),)
                )
            else:
                cursor = self._conn.execute(
                    "SELECT * FROM rules WHERE rules MATCH ? ORDER BY rank LIMIT ?",
                    (match, max(top_k, 1)),
                )
            rows = cursor.fetchall()
        return [self._row_to_rule(row) for row in rows]

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _build_match(text: str) -> str:
        """Build a safe FTS5 MATCH expression: OR of the alphanumeric query tokens."""
        tokens = _TOKEN_RE.findall(text or "")
        if not tokens:
            return ""
        # Quote each token so reserved words (AND/OR/NOT/NEAR) are treated as literals.
        return " OR ".join(f'"{t}"' for t in tokens)

    @staticmethod
    def _row_to_rule(row: sqlite3.Row) -> Ucp600Rule:
        try:
            score = float(row["score"])
        except (TypeError, ValueError):
            score = 0.0
        return Ucp600Rule(
            article=row["article"],
            title=row["title"],
            requirement=row["requirement"],
            url=row["url"] or "",
            score=score,
        )
