#!/usr/bin/env python3
"""Execute this repository's bounded portability contract without cloud credentials.

This is intentionally a proof driver, not another copy of the port map. The contract tests
own the repository-specific port-to-Protocol mapping and offline/exit calls; this program
runs those tests, verifies that the deterministic domain does not import a cloud SDK, proves
the audit trail survives leaving this codebase, and states the claims a laptop cannot
establish.

Exit is the load-bearing word in "portability", and until now this proof only covered the
CODE half of it: the ports bind offline, the domain imports no cloud SDK. The DATA half went
unexamined, even though the audit trail is the artefact a departing client actually has to
carry out. So the trail is now exported, reloaded into a foreign store, and its chain
re-verified here, with a truncated export required to be REFUSED rather than restored.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from hex_service_kit.audit import EXPORT_FORMAT, AuditChainError, HashChainedAuditLog

from trade_finance_checker.domain.models import AuditEvent, Decision

ROOT = Path(__file__).resolve().parents[1]
PYTEST_PYTHON = (
    ROOT / ".venv" / "bin" / "python"
    if (ROOT / ".venv" / "bin" / "python").is_file()
    else Path(sys.executable)
)


def _domain_files() -> list[Path]:
    return sorted((ROOT / "src").glob("*/domain/**/*.py"))


def _assert_cloud_free_domain() -> int:
    checked = 0
    forbidden: list[str] = []
    for path in _domain_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        checked += 1
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                if name.split(".", 1)[0] in {"google", "vertexai"}:
                    forbidden.append(f"{path.relative_to(ROOT)}:{node.lineno} imports {name}")
    if forbidden:
        raise AssertionError("cloud SDK crossed the domain boundary:\n" + "\n".join(forbidden))
    return checked


def _audit_event(action: str) -> AuditEvent:
    """One already-redacted record of the shape this repository actually writes."""
    return AuditEvent(
        action=action,
        actor="portability-proof (FICTIONAL)",
        decision=Decision.ALLOWED,
        redacted_prompt="[REDACTED] presentation against LC terms",
        redacted_response="[REDACTED] discrepancy summary",
    )


def _assert_the_trail_leaves_this_codebase_intact() -> int:
    """The trail exports to an open format, carries its anchor, and refuses a truncated copy.

    The export leads with the anchor header and then carries one line per record, so the file
    is one line LONGER than the record count ``export_jsonl`` returns. Header and record are
    told apart by KEY, not by position: a header carries ``anchor`` and no ``event``. Asserting
    position alone would keep passing if the header ever stopped being a header, and asserting
    ``len(lines) == written`` was the pre-anchor arithmetic that silently counted the header as
    a record.

    Why the anchor has to travel, and why the last case here is the point of the whole check:
    a shortened export is internally PERFECT. Every remaining link verifies, so the chain
    ALONE cannot see a dropped tail; the head it should have ended on stayed behind with the
    source store. The header is what the recipient checks the last record against, so dropping
    the newest record now has to be REFUSED rather than restored as a shorter, self-consistent
    history that reports itself intact.

    The truncated file is rebuilt from the RAW text lines. Re-encoding the parsed JSON would
    not be the bytes the hashes were taken over, so the import would fail for the wrong
    reason and the check would pass without ever exercising the anchor.
    """
    with tempfile.TemporaryDirectory(prefix="portability-") as work:
        source = HashChainedAuditLog(str(Path(work) / "audit.sqlite3"))
        for action in ("check", "extract", "detect"):
            source.record(_audit_event(action))

        export = Path(work) / "audit.jsonl"
        written = source.export_jsonl(export)
        raw = export.read_text(encoding="utf-8").splitlines()
        lines = [json.loads(line) for line in raw]
        header, records = lines[0], lines[1:]
        if len(lines) != written + 1 or "anchor" not in header or "event" in header:
            raise AssertionError(
                f"the export does not lead with one anchor header per record set: "
                f"{len(lines)} lines for {written} records"
            )
        if header.get("format") != EXPORT_FORMAT:
            raise AssertionError(
                f"the export header names {header.get('format')!r}, not the documented "
                f"format {EXPORT_FORMAT!r}"
            )
        if any("entry_hash" not in record or "anchor" in record for record in records):
            raise AssertionError("the export is not self-describing JSON Lines")
        head = {"seq": records[-1]["seq"], "entry_hash": records[-1]["entry_hash"]}
        if header["anchor"] != head:
            raise AssertionError("the anchor header does not commit to the head it ships with")

        foreign = HashChainedAuditLog(":memory:")
        reloaded = foreign.import_jsonl(export)
        if reloaded != written or not foreign.verify_chain().ok:
            raise AssertionError("the trail did not reload into a foreign store with its chain")

        truncated = Path(work) / "truncated.jsonl"
        truncated.write_text("\n".join(raw[:-1]) + "\n", encoding="utf-8")
        try:
            HashChainedAuditLog(":memory:").import_jsonl(truncated)
        except AuditChainError:
            pass
        else:
            raise AssertionError("a truncated export was restored as though it were whole")
    return written


def main() -> int:
    parity = ROOT / "tests" / "contract" / "test_port_parity.py"
    if not parity.is_file():
        raise AssertionError("tests/contract/test_port_parity.py is required")

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    result = subprocess.run(
        [
            str(PYTEST_PYTHON),
            "-m",
            "pytest",
            "-m",
            "not integration",
            "--disable-warnings",
            "-q",
        ],
        cwd=ROOT,
        env=env,
        check=False,
    )
    if result.returncode:
        print("FAIL offline and port contract suite", file=sys.stderr)
        return result.returncode
    print("PASS offline product: the repository's non-integration suite completed")
    print("PASS port matrix: every declared SDK-free adapter conforms and exit adapters refuse")

    checked = _assert_cloud_free_domain()
    print(f"PASS portable core: {checked} domain modules import no Google Cloud SDK")
    print("PASS managed boundary: adapter selection is configuration, not domain code")

    exported = _assert_the_trail_leaves_this_codebase_intact()
    print(
        f"PASS record leaves intact: {exported} records exported as anchored JSONL, reloaded "
        "into a foreign store with the chain verified, truncated export refused"
    )
    print(
        "LIMITS not proved here: live GCP calls, hosted identity, managed durability, "
        "CMEK/VPC-SC/Org Policy enforcement, performance parity, or a completed on-premises "
        "adapter. Those require deployment evidence; this proof makes no such claim."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
