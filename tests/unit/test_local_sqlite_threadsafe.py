"""Concurrency regression tests for the local SQLite adapters.

The API serves sync ``def`` endpoints from Starlette's threadpool while the container is a
process-wide singleton (``api.deps.get_container`` is ``@lru_cache``), so a single adapter
instance, holding one ``sqlite3`` connection, is exercised from several worker threads at
once. Without ``check_same_thread=False`` plus a lock serialising every access, SQLite
raises "SQLite objects created in a thread can only be used in that same thread" and the
WORM audit write (or a rules query) fails under concurrent ``serve``.

These tests drive each adapter's writes and reads from a ``ThreadPoolExecutor`` and assert
no exception is raised and the final row count is correct. They FAIL before the
``check_same_thread=False`` + lock fix and PASS after it.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from trade_finance_checker.adapters.local.audit import LocalAppendOnlyAuditAdapter
from trade_finance_checker.adapters.local.rules import LocalFtsRulesAdapter
from trade_finance_checker.config import LocalSettings, Settings
from trade_finance_checker.domain.models import AuditEvent, Decision, Ucp600Rule

# A file-backed temp DB is used (not ``:memory:``): an in-memory connection is private to
# its connection object, so a shared file path exercises the real cross-thread access that
# the FastAPI threadpool triggers in production.
_THREADS = 8
_PER_THREAD = 25


def _settings(tmp_path) -> Settings:
    return Settings(
        profile="local",
        local=LocalSettings(
            rules_db_path=str(tmp_path / "rules.db"),
            audit_path=str(tmp_path / "audit.db"),
        ),
    )


def test_audit_adapter_is_thread_safe(tmp_path) -> None:
    """Concurrent record() + read_all() on one audit adapter: no error, exact row count."""
    adapter = LocalAppendOnlyAuditAdapter(_settings(tmp_path))

    def worker(i: int) -> int:
        event = AuditEvent(
            action="check",
            actor=f"svc-{i}",
            decision=Decision.ALLOWED,
            redacted_prompt="p",
            redacted_response="r",
        )
        for _ in range(_PER_THREAD):
            adapter.record(event)
            adapter.read_all()  # interleave reads with writes across threads
        return _PER_THREAD

    with ThreadPoolExecutor(max_workers=_THREADS) as pool:
        written = sum(pool.map(worker, range(_THREADS)))

    assert written == _THREADS * _PER_THREAD
    assert len(adapter.read_all()) == _THREADS * _PER_THREAD


def test_rules_adapter_is_thread_safe(tmp_path) -> None:
    """Concurrent add() + retrieve_rules() on one rules adapter: no error, exact row count."""
    adapter = LocalFtsRulesAdapter(_settings(tmp_path))
    adapter.seed(())  # start from an empty, deterministic index

    def worker(i: int) -> int:
        for j in range(_PER_THREAD):
            adapter.add(
                [
                    Ucp600Rule(
                        article=f"UCP600 Art. {i}-{j}",
                        title=f"rule {i}-{j}",
                        requirement="documents must comply on their face",
                        url="https://example.test/ucp600",
                        score=0.5,
                    )
                ]
            )
            adapter.retrieve_rules("documents comply")  # interleave reads with writes
        return _PER_THREAD

    with ThreadPoolExecutor(max_workers=_THREADS) as pool:
        added = sum(pool.map(worker, range(_THREADS)))

    assert added == _THREADS * _PER_THREAD
    # Every inserted article is distinct, so the unbounded scan returns them all.
    assert len(adapter.retrieve_rules("documents comply", top_k=10_000)) == _THREADS * _PER_THREAD
