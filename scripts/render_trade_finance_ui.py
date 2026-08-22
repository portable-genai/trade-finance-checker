"""Render the audit-first trade-finance UI from the demo JSON into static HTML pages.

Server-side, dependency-free rendering of the B4 ``DiscrepancyReport`` (one page per
presentation round plus an examination timeline), faithful to the console palette used by
the Next.js UI (ink / regblue, Panel, severity + citation chips). Used to produce
screenshots / slides from the synthetic demo data.

**Evidence hooks (F2).** Every result section carries a ``data-panel='<slug>'`` and every
load-bearing figure carries its own ``data-*`` attribute (``data-discrepancy-count``,
``data-material-count``, ``data-citation-count``, ``data-report-verdict``,
``data-report-review``, per-card ``data-discrepancy-kind|rule|severity|doc|citations``, and
the timeline's ``data-timeline-*`` / ``data-citation-source``). These are deliberately
styling independent: ``scripts/demo_selftest.py`` and ``tests/browser/test_served_demo_ui.py``
read the figures back out of the SERVED page through them and compare each one against what
the running app computed, so a renderer that silently stops emitting a number fails the gate
instead of shipping a stale slide. Renaming a hook is therefore a breaking change.

    PYTHONPATH=src:tests python scripts/render_trade_finance_ui.py trade_finance_demo.json out_dir/
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path

KIND_LABEL = {
    "amount_mismatch": "Amount mismatch",
    "date_expired": "Presentation after expiry",
    "late_shipment": "Late shipment",
    "description_mismatch": "Goods description mismatch",
    "missing_document": "Missing document",
    "inconsistent_data": "Inconsistent data",
    "ucp600_rule_breach": "UCP600 rule breach",
}
SEV_COLOR = {
    "low": ("#eef2f7", "#546b8b"),
    "medium": ("#fef3c7", "#92400e"),
    "high": ("#ffedd5", "#c2410c"),
    "critical": ("#fee2e2", "#b91c1c"),
}
VERDICT_COLOR = {
    "compliant": ("#ecfdf5", "#047857"),
    "discrepant": ("#fee2e2", "#b91c1c"),
}
CITE_LABEL = {"LC": "LC", "UCP600": "UCP600", "DOCUMENT": "DOC"}

CSS = """
:root{--ink-50:#f5f7fa;--ink-100:#e6ebf2;--ink-200:#cdd7e4;--ink-300:#a6b6cc;
--ink-400:#7790ae;--ink-500:#546b8b;--ink-600:#3f5470;--ink-700:#33445b;--ink-800:#1f2a3a;--ink-900:#0f1726;
--regblue-50:#eef4ff;--regblue-100:#dbe7ff;--regblue-600:#2945d6;--regblue-700:#2237ad;
--ok:#059669;--ok-bg:#ecfdf5;--warn:#d97706;--warn-bg:#fffbeb;
--shadow:0 1px 2px rgba(11,16,26,.06),0 8px 24px rgba(11,16,26,.06);}
*{box-sizing:border-box}
body{margin:0;background:var(--ink-50);color:var(--ink-800);
font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;
font-size:14px;line-height:1.5;padding:24px 18px}
.wrap{max-width:900px;margin:0 auto}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
h1{font-size:18px;margin:0 0 2px}
.sub{color:var(--ink-500);font-size:13px;margin:0 0 16px}
.sub b{color:var(--ink-800)}
.steps{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 16px}
.step{font-size:12px;padding:4px 10px;border-radius:999px;border:1px solid var(--ink-200);background:#fff;color:var(--ink-500)}
.step.done{background:var(--regblue-50);border-color:var(--regblue-100);color:var(--regblue-700)}
.step.cur{background:var(--regblue-600);border-color:var(--regblue-600);color:#fff;font-weight:600}
.panel{border:1px solid var(--ink-200);background:#fff;border-radius:10px;box-shadow:var(--shadow);margin-bottom:16px}
.panel>h2{border-bottom:1px solid var(--ink-100);padding:11px 16px;margin:0;font-size:13px;font-weight:600;color:var(--ink-800);
display:flex;justify-content:space-between;align-items:center;gap:10px}
.panel>.body{padding:16px}
.verdict{font-size:11px;font-weight:700;padding:3px 11px;border-radius:999px;text-transform:uppercase;letter-spacing:.03em}
.review{border:1px solid #fcd34d;background:var(--warn-bg);color:#92400e;border-radius:8px;padding:8px 12px;font-size:12px;font-weight:600;margin-bottom:14px}
.release{border:1px solid #a7f3d0;background:var(--ok-bg);color:#047857;border-radius:8px;padding:8px 12px;font-size:12px;font-weight:600;margin-bottom:14px}
.summary{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
.summary .f{font-size:12px;color:var(--ink-500)}
.summary .f b{display:block;color:var(--ink-800);font-size:14px;font-variant-numeric:tabular-nums}
.narr{font-size:13px;color:var(--ink-700);white-space:pre-line}
.empty{color:var(--ok);font-size:13px;background:var(--ok-bg);border:1px solid #a7f3d0;border-radius:8px;padding:10px 12px}
/* discrepancy cards */
.disc{border:1px solid var(--ink-200);border-radius:9px;background:var(--ink-50);padding:12px;margin-bottom:10px}
.disc>.dh{display:flex;align-items:center;justify-content:space-between;gap:10px}
.disc .name{font-weight:600;font-size:13px;color:var(--ink-800)}
.disc .where{font-family:ui-monospace,Menlo,monospace;font-size:11px;color:var(--ink-500);margin-left:6px;font-weight:400}
.sev{font-size:10px;font-weight:700;text-transform:uppercase;padding:2px 7px;border-radius:5px;flex:none}
.ef{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:8px}
.ef .lbl{font-size:10px;text-transform:uppercase;color:var(--ink-400)}
.ef .val{font-size:13px;color:var(--ink-800)}
.breach{margin-top:8px;font-size:12px;color:var(--ink-500)}
.breach b{color:var(--ink-700)}
.cites{margin-top:8px;display:flex;gap:5px;flex-wrap:wrap}
.chip{display:inline-flex;align-items:center;gap:4px;border:1px solid var(--ink-200);background:#fff;border-radius:6px;padding:1px 7px;font-size:11px;color:var(--ink-700)}
.chip .ty{font-family:ui-monospace,Menlo,monospace;font-weight:600;color:var(--regblue-700)}
.chip .sr{font-family:ui-monospace,Menlo,monospace}
.foot{font-size:11px;color:var(--ink-400);text-align:center;margin-top:18px}
/* timeline */
table.tl{width:100%;border-collapse:collapse;font-size:13px}
table.tl th,table.tl td{text-align:left;padding:9px 10px;border-bottom:1px solid var(--ink-100)}
table.tl th{font-size:11px;text-transform:uppercase;color:var(--ink-400);font-weight:600}
table.tl td.num{font-variant-numeric:tabular-nums}
"""


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def sev_pill(sev: str) -> str:
    bg, fg = SEV_COLOR.get(sev, SEV_COLOR["low"])
    return f'<span class="sev" style="background:{bg};color:{fg}">{esc(sev)}</span>'


def verdict_pill(verdict: str) -> str:
    bg, fg = VERDICT_COLOR.get(verdict, SEV_COLOR["low"])
    return f'<span class="verdict" style="background:{bg};color:{fg}">{esc(verdict)}</span>'


def chip(c: dict) -> str:
    ty = CITE_LABEL.get(c.get("source_type", ""), c.get("source_type", ""))
    page = f" p.{c['page']}" if c.get("page") is not None else ""
    return (
        f"<span class=\"chip\" data-citation-source='{esc(c.get('source_id'))}' "
        f"data-citation-type='{esc(c.get('source_type'))}'>"
        f'<span class="ty">{esc(ty)}</span>'
        f'<span class="sr">{esc(c.get("source_id"))}{esc(page)}</span></span>'
    )


def _material_count(report: dict) -> int:
    return sum(1 for d in report.get("discrepancies", []) if d.get("severity") != "low")


def _report_hooks(report: dict) -> str:
    """The report-level ``data-*`` evidence hooks, emitted on every result panel group.

    Kept in ONE place so the served self-test and the browser walkthrough read the same
    attribute names the renderer writes, and a figure cannot be renamed on one side only.
    """
    return (
        f"data-report-lc='{esc(report.get('lc_number'))}' "
        f"data-report-verdict='{esc(report.get('verdict'))}' "
        f"data-report-review='{str(bool(report.get('requires_human_review'))).lower()}' "
        f"data-discrepancy-count='{len(report.get('discrepancies', []))}' "
        f"data-material-count='{_material_count(report)}' "
        f"data-citation-count='{len(report.get('citations', []))}'"
    )


def steps_bar(cur: int, n_rounds: int, released: bool) -> str:
    labels = [f"Round {i}" for i in range(n_rounds)] + ["Officer review"]
    out = []
    review_idx = n_rounds
    for i, lab in enumerate(labels):
        cls = "step"
        if i == review_idx:
            if released and cur == review_idx:
                cls += " cur"
            elif released:
                cls += " done"
        elif i < cur:
            cls += " done"
        elif i == cur:
            cls += " cur"
        out.append(f'<span class="{cls}">{esc(lab)}</span>')
    return '<div class="steps">' + "".join(out) + "</div>"


def render_summary(summary: dict) -> str:
    checked = summary.get("documents_checked", [])
    docs = ", ".join(checked) or "(none)"
    return f"""
    <section class="panel" data-panel='presentation-summary'
      data-summary-lc='{esc(summary.get("lc_number"))}'
      data-summary-currency='{esc(summary.get("currency"))}'
      data-summary-document-count='{len(checked)}'><h2>Presentation summary</h2><div class="body">
      <div class="summary">
        <div class="f">LC amount<b>{esc(summary.get("amount"))} {esc(summary.get("currency"))}</b></div>
        <div class="f">Expiry<b>{esc(summary.get("expiry_date"))}</b></div>
        <div class="f">Latest shipment<b>{esc(summary.get("latest_shipment"))}</b></div>
        <div class="f">Documents checked<b>{esc(docs)}</b></div>
      </div>
      <div class="docs">{"".join(f"<span data-summary-document='{esc(d)}'></span>" for d in checked)}</div>
    </div></section>"""


def render_discrepancies(report: dict) -> str:
    discs = report.get("discrepancies", [])
    hooks = _report_hooks(report)
    if not discs:
        return (
            f"<section class=\"panel\" data-panel='discrepancies' {hooks}>"
            '<h2>Discrepancies <span class="mono">0</span></h2>'
            '<div class="body"><div class="empty">'
            "&#10003; No discrepancies detected. The presentation complies on its face with "
            "the LC terms and UCP600, subject to the officer's release decision."
            "</div></div></section>"
        )
    cards = []
    for d in discs:
        cites = "".join(chip(c) for c in d.get("citations", []))
        cards.append(
            f"""<div class="disc" data-discrepancy-kind='{esc(d["kind"])}'
              data-discrepancy-rule='{esc(d["ucp600_article"])}'
              data-discrepancy-severity='{esc(d["severity"])}'
              data-discrepancy-doc='{esc(d["doc_type"])}'
              data-discrepancy-field='{esc(d["field"])}'
              data-discrepancy-citations='{len(d.get("citations", []))}'>
              <div class="dh">
                <span class="name">{esc(KIND_LABEL.get(d["kind"], d["kind"]))}
                  <span class="where">{esc(d["doc_type"])}.{esc(d["field"])}</span></span>
                {sev_pill(d["severity"])}
              </div>
              <div class="ef">
                <div><div class="lbl">Expected</div><div class="val">{esc(d["expected"])}</div></div>
                <div><div class="lbl">Found</div><div class="val">{esc(d["found"])}</div></div>
              </div>
              <div class="breach">Breaches <b>{esc(d["ucp600_article"])}</b></div>
              <div class="cites">{cites}</div>
            </div>"""
        )
    return (
        f"<section class=\"panel\" data-panel='discrepancies' {hooks}>"
        f"<h2>Discrepancies the system found "
        f'<span class="mono">{len(discs)}</span></h2>'
        f'<div class="body">{"".join(cards)}</div></section>'
    )


def render_officer_decision(decision: dict) -> str:
    """The four-eyes (P-06) outcome banner, with its own stable evidence hooks.

    Lives here rather than in the demo server so the decision step of the presenter
    journey carries the same ``data-panel`` contract every other result section does.
    """
    verdict = decision.get("decision", "")
    released = verdict == "release"
    cls = "release" if released else "review"
    prefix = "OFFICER DECISION RECORDED" if released else "OFFICER DECISION"
    who = (
        f"(maker {esc(decision.get('maker'))}, checker {esc(decision.get('officer'))}). "
        if released
        else ""
    )
    return (
        f"<div class=\"{cls}\" data-panel='officer-decision' "
        f"data-officer-decision='{esc(verdict)}' "
        f"data-officer-maker='{esc(decision.get('maker'))}' "
        f"data-officer-checker='{esc(decision.get('officer'))}'>"
        f"{prefix} &mdash; {esc(verdict.upper())} {who}{esc(decision.get('basis'))}</div>"
    )


def page(title: str, body: str) -> str:
    return (
        f"<!doctype html><html><head><meta charset='utf-8'><title>{esc(title)}</title>"
        f"<style>{CSS}</style></head><body><div class='wrap'>{body}</div></body></html>"
    )


def render_round(data: dict, rnd: dict) -> str:
    report = rnd["report"]
    lc = data["lc"]
    n_rounds = len(data["rounds"])
    released = data.get("officer_decision", {}).get("decision") == "release"
    verdict = report["verdict"]
    n = report and len(report.get("discrepancies", []))
    header = (
        f"<h1>Documentary credit examination &mdash; {esc(lc['lc_number'])}</h1>"
        f"<p class='sub'>Beneficiary <b>{esc(lc['beneficiary'])}</b> &middot; "
        f"applicant {esc(lc['applicant'])} &middot; incoterm {esc(lc['incoterm'])} &middot; "
        f"round {esc(rnd['no'])} &mdash; <b>{esc(rnd['label'])}</b></p>"
        + steps_bar(rnd["no"], n_rounds, released)
        + (
            "<div class=\"review\" data-panel='review-gate' "
            f"data-review-required='{str(bool(report.get('requires_human_review'))).lower()}'>"
            "HUMAN REVIEW REQUIRED &mdash; maker-checker gate (P-06). "
            "A trade-finance officer must review before the bank pays, refuses, or seeks a "
            "waiver. The checker is decision support, never an approval.</div>"
        )
    )
    verdict_panel = (
        f"<section class=\"panel\" data-panel='examination-verdict' {_report_hooks(report)}>"
        f"<h2>Examination verdict {verdict_pill(verdict)}</h2>"
        f"<div class='body'><span class='mono'>{n} discrepancy(ies), "
        f"{_material_count(report)} material</span>"
        + (
            f"<p class='narr' style='margin-top:10px'>{esc(report.get('narrative'))}</p>"
            if report.get("narrative")
            else ""
        )
        + "</div></section>"
    )
    body = (
        header
        + verdict_panel
        + render_summary(report["summary"])
        + render_discrepancies(report)
        + "<p class='foot'>Audit-first trade-finance view &middot; synthetic fictional data "
        "&middot; deterministic UCP600 discrepancy detector</p>"
    )
    return page(f"LC examination round {rnd['no']}", body)


def render_timeline(data: dict) -> str:
    rows = []
    for rnd in data["rounds"]:
        report = rnd["report"]
        rows.append(
            f"<tr data-timeline-round='{esc(rnd['no'])}' "
            f"data-timeline-verdict='{esc(report['verdict'])}' "
            f"data-timeline-discrepancies='{len(report.get('discrepancies', []))}' "
            f"data-timeline-material='{_material_count(report)}'>"
            f"<td>Round {esc(rnd['no'])}</td><td>{esc(rnd['label'])}</td>"
            f"<td>{verdict_pill(report['verdict'])}</td>"
            f"<td>{esc(', '.join(rnd['presented']))}</td>"
            f"<td class='num'>{len(report.get('discrepancies', []))}</td>"
            f"<td class='num'>{_material_count(report)}</td></tr>"
        )
    decision = data.get("officer_decision", {})
    decrow = (
        f"<tr data-timeline-round='review' "
        f"data-timeline-verdict='{esc(decision.get('decision'))}'>"
        f"<td>Officer review</td><td>maker-checker (P-06)</td>"
        f"<td>{esc(decision.get('decision', '').upper())}</td>"
        f"<td>by {esc(decision.get('officer'))}</td><td class='num'>&mdash;</td>"
        f"<td class='num'>&mdash;</td></tr>"
        if decision
        else ""
    )
    body = (
        f"<h1>Examination timeline &mdash; {esc(data['lc']['lc_number'])}</h1>"
        f"<p class='sub'>How the presentation moved over rounds as the beneficiary cleared "
        f"the bank's discrepancy advice. Final officer decision: "
        f"<b>{esc(decision.get('decision', 'pending').upper())}</b>.</p>"
        "<section class=\"panel\" data-panel='rounds-timeline' "
        f"data-timeline-rounds='{len(data['rounds'])}'>"
        '<h2>Rounds</h2><div class="body">'
        "<table class='tl'><tr><th>Round</th><th>What was presented</th><th>Verdict</th>"
        "<th>Documents</th><th>Discrepancies</th><th>Material</th></tr>"
        + "".join(rows)
        + decrow
        + "</table></div></section>"
        + render_sources(data)
        + "<p class='foot'>Audit-first trade-finance view &middot; synthetic fictional data</p>"
    )
    return page("LC examination timeline", body)


def timeline_citations(data: dict) -> list[dict]:
    """Every distinct citation the examination relied on, in first-seen order.

    Deduplicated on ``(source_type, source_id)``: the same UCP600 article backs several
    findings, and the audit page lists each authority once.
    """
    seen: dict[tuple[str, str], dict] = {}
    for rnd in data.get("rounds", []):
        report = rnd["report"]
        cites = list(report.get("citations", []))
        for disc in report.get("discrepancies", []):
            cites.extend(disc.get("citations", []))
        for c in cites:
            seen.setdefault((c.get("source_type", ""), c.get("source_id", "")), c)
    return list(seen.values())


def render_sources(data: dict) -> str:
    """The sources / audit panel: the authorities behind every finding, cited once each."""
    cites = timeline_citations(data)
    rows = "".join(
        f"<tr data-citation-source='{esc(c.get('source_id'))}' "
        f"data-citation-type='{esc(c.get('source_type'))}'>"
        f"<td>{esc(CITE_LABEL.get(c.get('source_type', ''), c.get('source_type', '')))}</td>"
        f"<td>{esc(c.get('source_id'))}</td><td>{esc(c.get('title'))}</td></tr>"
        for c in cites
    )
    return (
        "<section class=\"panel\" data-panel='sources' "
        f"data-source-count='{len(cites)}'>"
        '<h2>Sources the examination cited</h2><div class="body">'
        "<table class='tl'><tr><th>Kind</th><th>Reference</th><th>Authority</th></tr>"
        f"{rows}</table></div></section>"
    )


def main(json_path: str, out_dir: str) -> None:
    data = json.loads(Path(json_path).read_text())
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    written = []
    for rnd in data["rounds"]:
        p = out / f"tf-round-{rnd['no']}.html"
        p.write_text(render_round(data, rnd))
        written.append(p)
    tl = out / "tf-timeline.html"
    tl.write_text(render_timeline(data))
    written.append(tl)
    for p in written:
        print("wrote", p)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
