"""``trade-finance-checker`` : the Typer CLI for the B4 Trade-Finance Document Checker.

This is a thin presentation layer over the domain service. It owns no business logic:
every command builds the wiring from
:func:`trade_finance_checker.config.build_container` and the factory functions in
:mod:`trade_finance_checker.api.deps`, invokes the service, and pretty-prints the cited
result.

Design constraints honoured here:

* **Import-safe.** Importing this module (e.g. ``trade_finance_checker.cli.main:app`` as
  the ``[project.scripts]`` entry point, or ``--help``) must never pull in FastAPI,
  uvicorn, or the Google Cloud SDKs. All of those are imported *lazily inside command
  bodies*, so the on-prem/test profile : which installs no Google Cloud SDK : can still
  load the CLI and run ``--help``.
* **Profile-aware.** ``TRADE_FINANCE_PROFILE`` selects the adapter stack. The ``onprem``
  profile binds placeholder adapters that raise ``NotImplementedError`` from every method;
  when a command trips one of those, the CLI fails clearly (exit code 2) with a message
  that names the migration target rather than dumping a traceback.
* **Citations are first-class.** A discrepancy report is printed with the UCP600 article /
  LC term provenance behind each finding, because a discrepancy a trade officer cannot
  trace to a rule is worthless.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import typer

from ..domain.identity import Principal

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime top level
    from ..config import Container
    from ..domain.models import Citation, DiscrepancyReport, DocumentExtract

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        "B4 Trade-Finance Document Checker : detect discrepancies in a documentary-credit "
        "presentation against the LC terms and UCP600, on the Gemini Enterprise Agent "
        "Platform (region asia-southeast1)."
    ),
)

# Exit codes: 2 == the active profile cannot satisfy this command (e.g. on-prem stub);
# 1 == an unexpected adapter/runtime failure. 0 == success.
_PROFILE_EXIT = 2
_RUNTIME_EXIT = 1

# Identity the CLI operates under. The local CLI has no IdP, so it runs as a seeded
# demo-bank operator: a verified :class:`Principal` (never a client-asserted string) that
# is the audit actor AND carries the entitlement principals the object-authz gate checks.
# It is entitled to the demo-bank-owned sample LCs; an LC owned by another tenant (or with
# no registered owner) is denied server-side, exactly as it would be for the API.
_CLI_PRINCIPAL = Principal(
    subject="cli:operator",
    principals=("group:trade-analyst", "group:trade-finance"),
    tenant="demo-bank",
    assurance="local-cli",
    source="cli",
)


# --------------------------------------------------------------------------- #
# Wiring helpers (all imports lazy, so this module stays import-safe)
# --------------------------------------------------------------------------- #
def _container() -> Container:
    """Build the adapter container for the active ``TRADE_FINANCE_PROFILE``."""
    from ..config import build_container

    return build_container()


def _deps() -> Any:
    """Import the ``api.deps`` factory module lazily."""
    try:
        from ..api import deps  # type: ignore[attr-defined]
    except ImportError as exc:  # pragma: no cover - defensive wiring guard
        _fail(
            f"Service factories (trade_finance_checker.api.deps) are unavailable: {exc}",
            code=_RUNTIME_EXIT,
        )
    return deps


def _fail(message: str, *, code: int = _RUNTIME_EXIT) -> Any:
    """Print a clean error to stderr and abort with ``code`` (no traceback)."""
    typer.secho(f"error: {message}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code)


def _run(action: str, fn: Any) -> Any:
    """Execute ``fn`` and translate adapter failures into clean CLI errors.

    ``NotImplementedError`` (raised by every on-prem placeholder adapter) maps to a profile
    error that names the migration target; anything else surfaces as a runtime error. This
    is the single place the CLI turns exceptions into exit codes.
    """
    from ..config import Settings

    profile = Settings.load().profile
    try:
        return fn()
    except NotImplementedError as exc:
        detail = str(exc) or "method not implemented"
        _fail(
            f"'{action}' is not available under profile '{profile}'. "
            f"This profile uses placeholder adapters (on-prem migration target): {detail}",
            code=_PROFILE_EXIT,
        )
    except KeyError as exc:
        _fail(
            f"'{action}' has no adapter wired for profile '{profile}': {exc}",
            code=_PROFILE_EXIT,
        )
    except typer.Exit:
        raise
    except Exception as exc:  # noqa: BLE001 - CLI boundary: no tracebacks to operators
        _fail(f"'{action}' failed: {type(exc).__name__}: {exc}", code=_RUNTIME_EXIT)


# --------------------------------------------------------------------------- #
# Pretty-printing
# --------------------------------------------------------------------------- #
def _fmt_citation(c: Citation) -> str:
    """Render one citation as ``[source_type source_id p.N] : url``."""
    page = f" p.{c.page}" if c.page is not None else ""
    stype = c.source_type.value if hasattr(c.source_type, "value") else str(c.source_type)
    tail = f" : {c.url}" if c.url else ""
    return f"[{stype} {c.source_id}{page}]{tail}"


def _echo_citations(citations: tuple[Citation, ...], indent: str = "    ") -> None:
    if not citations:
        return
    for c in citations:
        typer.echo(f"{indent}- {_fmt_citation(c)}")


def _print_report(report: DiscrepancyReport) -> None:
    color = typer.colors.GREEN if report.verdict.value == "compliant" else typer.colors.RED
    typer.secho(
        f"Presentation {report.lc_number} : {report.verdict.value.upper()}",
        bold=True,
        fg=color,
    )
    typer.echo(
        f"  documents checked: {', '.join(d.value for d in report.documents_checked) or '(none)'}"
    )
    typer.echo(f"  discrepancies: {report.discrepancy_count} ({report.material_count} material)")
    typer.secho(
        "  [HUMAN REVIEW REQUIRED] maker-checker gate (P-06) : a trade-finance officer "
        "must review before the bank acts (pay, refuse, or seek a waiver).",
        fg=typer.colors.YELLOW,
        bold=True,
    )
    if report.narrative:
        typer.echo("")
        typer.echo(f"  {report.narrative}")
    typer.echo("")
    for disc in report.discrepancies:
        sev = disc.severity.value if hasattr(disc.severity, "value") else str(disc.severity)
        typer.secho(
            f"  [{disc.kind.value}] ({sev}) {disc.doc_type.value}.{disc.field}",
            bold=True,
        )
        typer.echo(f"    expected: {disc.expected}")
        typer.echo(f"    found:    {disc.found}")
        typer.echo(f"    breach:   {disc.ucp600_article}")
        _echo_citations(disc.citations)


def _print_extract(extract: DocumentExtract) -> None:
    typer.secho(f"Extract : {extract.doc_type.value}", bold=True, fg=typer.colors.GREEN)
    typer.echo(f"  pages: {extract.pages}")
    for key, value in extract.fields.items():
        typer.echo(f"  {key}: {value}")


def _load_json(path: str) -> Any:
    from pathlib import Path

    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _fail(f"could not read JSON from {path}: {exc}", code=_RUNTIME_EXIT)


def _to_lc(data: dict[str, Any]) -> Any:
    from ..domain.models import LetterOfCredit

    return LetterOfCredit(
        lc_number=str(data.get("lc_number", "")),
        amount=float(data.get("amount", 0.0) or 0.0),
        currency=str(data.get("currency", "")),
        expiry_date=str(data.get("expiry_date", "")),
        latest_shipment=str(data.get("latest_shipment", "")),
        incoterm=str(data.get("incoterm", "")),
        beneficiary=str(data.get("beneficiary", "")),
        applicant=str(data.get("applicant", "")),
        terms={str(k): str(v) for k, v in (data.get("terms") or {}).items()},
    )


def _to_documents(items: list[dict[str, Any]]) -> list[Any]:
    from ..domain.models import PresentedDocument, TradeDocType

    return [
        PresentedDocument(
            doc_type=TradeDocType(str(item.get("doc_type", "other"))),
            fields={str(k): str(v) for k, v in (item.get("fields") or {}).items()},
            pages=int(item.get("pages", 1) or 1),
            document_id=str(item.get("document_id", "")),
        )
        for item in items
    ]


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
@app.command()
def check(
    presentation: str = typer.Argument(
        ...,
        help="Path to a JSON file with {lc: {...}, documents: [{...}]}.",
    ),
) -> None:
    """Examine a presentation against its LC and UCP600; print the discrepancy report."""
    data = _load_json(presentation)
    lc = _to_lc(data.get("lc", {}))
    documents = _to_documents(data.get("documents", []) or [])

    def _do() -> DiscrepancyReport:
        svc = _deps().build_trade_check_service(_container())
        return svc.check(lc, documents, principal=_CLI_PRINCIPAL)

    report = _run("check", _do)
    _print_report(report)


@app.command()
def extract(
    document: str = typer.Argument(
        ..., help="Path to a JSON file with a single {doc_type, fields, pages} document."
    ),
) -> None:
    """Parse a single trade document into structured fields."""
    data = _load_json(document)
    doc = _to_documents([data])[0]

    def _do() -> DocumentExtract:
        svc = _deps().build_trade_check_service(_container())
        return svc.extract(doc, principal=_CLI_PRINCIPAL)

    result = _run("extract", _do)
    _print_extract(result)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind address for the API server."),
    port: int = typer.Option(8094, help="TCP port for the API server."),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload on code change (dev only)."),
) -> None:
    """Run the FastAPI app (A2A card, MCP, and REST endpoints) under uvicorn."""

    def _do() -> None:
        import uvicorn

        deps = _deps()
        if not hasattr(deps, "create_app"):
            _fail(
                "trade_finance_checker.api.deps does not expose create_app(); "
                "cannot start the server.",
                code=_RUNTIME_EXIT,
            )
        typer.secho(
            f"serving trade-finance-checker on http://{host}:{port} (profile={_profile_label()})",
            fg=typer.colors.GREEN,
        )
        uvicorn.run(
            "trade_finance_checker.api.deps:create_app",
            factory=True,
            host=host,
            port=port,
            reload=reload,
        )

    _run("serve", _do)


@app.command()
def eval(  # noqa: A001 - "eval" is the documented command name in SPEC §
    dataset: str | None = typer.Option(
        None,
        "--dataset",
        "-d",
        help="Path to the golden eval dataset (defaults to the gate's bundled set).",
    ),
) -> None:
    """Run the A4 promotion eval gate (recall / precision / citation accuracy / PII safety).

    Delegates to the ``eval/run_eval.py`` gate script (SPEC §3, A4) in a subprocess so the
    heavy Gen AI evaluation dependencies stay out of the CLI's import graph. The
    subprocess's exit code is the gate verdict and becomes this command's exit code.
    """

    def _do() -> int:
        import subprocess
        import sys
        from pathlib import Path

        # eval/ is a repo-root directory (not a package), so locate the script relative to
        # the source tree: main.py -> cli -> trade_finance_checker -> src -> <repo>.
        repo_root = Path(__file__).resolve().parents[3]
        script = repo_root / "eval" / "run_eval.py"
        if not script.exists():
            _fail(f"eval gate script not found at {script}", code=_RUNTIME_EXIT)
        cmd = [sys.executable, str(script)]
        if dataset:
            cmd += ["--dataset", dataset]
        typer.secho(f"running eval gate: {script}", fg=typer.colors.CYAN)
        completed = subprocess.run(cmd, check=False)  # noqa: S603 - trusted local script
        return completed.returncode

    code = _run("eval", _do)
    if code == 0:
        typer.secho("eval gate: PASS", fg=typer.colors.GREEN, bold=True)
    else:
        typer.secho("eval gate: FAIL", fg=typer.colors.RED, bold=True)
    raise typer.Exit(int(code))


def _profile_label() -> str:
    from ..config import Settings

    return Settings.load().profile


if __name__ == "__main__":  # pragma: no cover
    app()
