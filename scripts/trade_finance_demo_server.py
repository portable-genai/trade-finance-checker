"""Live, click-through demo server for the B4 trade-finance check flow (stdlib only).

Holds a real :class:`TradeCheckService` on the ``local`` profile and runs the *actual*
discrepancy check one round per click as the beneficiary corrects the presentation:
first presentation -> corrected invoice + B/L -> amended set with insurance -> officer
release decision (maker-checker, P-06). Each step renders the audit-first report UI.
No Google Cloud, no API key, no extra dependencies.

    PYTHONPATH=src:tests python scripts/trade_finance_demo_server.py [--port 8095]

Then open http://localhost:8095 and click "Next" to advance the real check, "Restart" to
reset; or drive it with ``scripts/trade_finance_demo_playwright.py`` for a guided,
presenter-controlled walkthrough. The demo port (8095) is deliberately distinct from the
API port (8094, ``make run-api``) so both can run side by side.
"""

from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import render_trade_finance_ui as r  # sibling: reuse the exact audit-first rendering
import trade_finance_demo as demo  # sibling: reuse the synthetic LC scenario

# Scripted demo steps. Each "Next" performs the action described by ``next``.
STEPS = [
    {
        "key": "round0",
        "label": "First presentation examined",
        "next": "Beneficiary corrects invoice and transport, re-presents (Round 1)",
    },
    {
        "key": "round1",
        "label": "Round 1 examined — fewer discrepancies",
        "next": "Beneficiary adds the insurance document, re-presents (Round 2)",
    },
    {
        "key": "round2",
        "label": "Round 2 examined — compliant on its face",
        "next": "Trade-finance officer records the release decision (four-eyes)",
    },
    {"key": "decision", "label": "Officer release decision recorded", "next": None},
]

_CONTROL_CSS = """
.democtl{position:sticky;top:0;z-index:10;display:flex;align-items:center;gap:12px;
  margin:-24px -18px 16px;padding:12px 18px;background:#0b101a;color:#fff}
.democtl .lbl{font-size:13px}.democtl .lbl b{color:#90b2ff}
.democtl .spacer{flex:1}
.democtl form{margin:0}
.democtl button{font:inherit;font-size:13px;font-weight:600;border:0;border-radius:7px;
  padding:7px 14px;cursor:pointer}
.democtl .next{background:#3a60f0;color:#fff}.democtl .next:disabled{opacity:.4;cursor:default}
.democtl .restart{background:transparent;color:#a6b6cc;border:1px solid #33445b}
.democtl .pct{font-variant-numeric:tabular-nums;color:#cdd7e4;font-size:12px}
"""


class DemoSession:
    """Drives the real trade-finance check forward one scripted round at a time."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.service, self.profile = demo._build_service()
        self.idx = 0
        self.data: dict = {
            "lc": demo.to_jsonable(demo.LC),
            "profile": self.profile,
            "actor": demo.ACTOR,
            "officer": demo.OFFICER,
            "rounds": [],
            "officer_decision": {},
        }
        # Run round 0 immediately so the first page already shows a real examination.
        self._run_round(0)

    @property
    def at_end(self) -> bool:
        return self.idx >= len(STEPS) - 1

    def _run_round(self, no: int) -> None:
        label, documents = demo.ROUNDS[no]
        report = self.service.check(demo.LC, documents, principal=demo.PRINCIPAL)
        self.data["rounds"].append(
            {
                "no": no,
                "label": label,
                "presented": [d.doc_type.value for d in documents],
                "report": demo.to_jsonable(report),
            }
        )

    def advance(self) -> None:
        if self.at_end:
            return
        self.idx += 1
        key = STEPS[self.idx]["key"]
        if key.startswith("round"):
            self._run_round(int(key[-1]))
        elif key == "decision":
            final = self.data["rounds"][-1]["report"]
            released = final["verdict"] == "compliant"
            self.data["officer_decision"] = {
                "officer": demo.OFFICER,
                "maker": demo.ACTOR,
                "decision": "release" if released else "refuse",
                "basis": (
                    "Compliant on its face after re-presentation; complying presentation "
                    "honoured under the credit."
                    if released
                    else "Discrepancies outstanding; refusal / waiver-request per UCP600 Art. 16."
                ),
            }

    # -- rendering --------------------------------------------------------- #
    def render(self) -> str:
        if STEPS[self.idx]["key"] == "decision":
            html = self._decision_page()
        else:
            rnd = self.data["rounds"][-1]
            html = r.render_round(self.data, rnd)
        return self._inject_controls(html)

    def _decision_page(self) -> str:
        rnd = self.data["rounds"][-1]
        report = rnd["report"]
        decision = self.data["officer_decision"]
        lc = self.data["lc"]
        released = decision.get("decision") == "release"
        # The banner (and its data-panel / data-officer-* evidence hooks) is rendered by the
        # shared renderer, so the decision step carries the same hook contract as every other
        # result section and scripts/demo_selftest.py can read it out of the served bytes.
        banner = r.render_officer_decision(decision)
        body = (
            f"<h1>Documentary credit examination &mdash; {r.esc(lc['lc_number'])}</h1>"
            f"<p class='sub'>Beneficiary <b>{r.esc(lc['beneficiary'])}</b> &middot; "
            f"four-eyes maker-checker (P-06) complete.</p>"
            + r.steps_bar(len(self.data["rounds"]), len(self.data["rounds"]), released)
            + banner
            + r.render_summary(report["summary"])
            + r.render_discrepancies(report)
            + "<p class='foot'>Audit-first trade-finance view &middot; synthetic fictional data "
            "&middot; deterministic UCP600 discrepancy detector</p>"
        )
        return r.page("LC examination — officer decision", body)

    def _inject_controls(self, html: str) -> str:
        step = STEPS[self.idx]
        nxt = step["next"]
        n = ""
        if self.data["rounds"]:
            ndisc = len(self.data["rounds"][-1]["report"].get("discrepancies", []))
            n = f"<span class='pct'>{ndisc} discrepancy(ies)</span>"
        next_btn = (
            f"<form method='post' action='/advance'><button class='next' type='submit'>"
            f"Next &nbsp;&middot;&nbsp; {r.esc(nxt)}</button></form>"
            if nxt
            else "<button class='next' disabled>Demo complete &#10003;</button>"
        )
        bar = (
            f"<div class='democtl' data-demo='presenter-step' data-step='{self.idx}'>"
            f"<span class='lbl'>Step {self.idx + 1}/{len(STEPS)} &mdash; "
            f"<b>{r.esc(step['label'])}</b></span>"
            f"{n}<span class='spacer'></span>{next_btn}"
            "<form method='post' action='/restart'>"
            "<button class='restart' type='submit'>Restart</button></form>"
            "</div>"
        )
        html = html.replace("</style>", _CONTROL_CSS + "</style>", 1)
        return html.replace("<div class='wrap'>", "<div class='wrap'>" + bar, 1)


class Handler(BaseHTTPRequestHandler):
    session: DemoSession  # set on the server instance below

    def _send(self, body: str, status: int = 200) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _redirect(self, to: str = "/") -> None:
        self.send_response(303)
        self.send_header("Location", to)
        self.end_headers()

    @property
    def _sess(self) -> DemoSession:
        return self.server.session  # type: ignore[attr-defined]

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        with self.server.lock:  # type: ignore[attr-defined]
            if path == "/":
                self._send(self._sess.render())
            elif path == "/timeline":
                self._send(r.render_timeline(self._sess.data))
            elif path == "/state":
                self._send(json.dumps({"step": self._sess.idx}), 200)
            elif path == "/restart":
                # Allowed over GET so the walkthrough can reset with a plain navigation.
                self._sess.reset()
                self._redirect("/")
            else:
                self._send("<h1>404</h1>", 404)

    def do_POST(self) -> None:  # noqa: N802 (http.server API)
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        with self.server.lock:  # type: ignore[attr-defined]
            if path == "/advance":
                self._sess.advance()
            elif path == "/restart":
                self._sess.reset()
        self._redirect("/")

    def log_message(self, *args: object) -> None:  # quiet console
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Live trade-finance demo server")
    parser.add_argument("--port", type=int, default=8095)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.session = DemoSession()  # type: ignore[attr-defined]
    server.lock = threading.Lock()  # type: ignore[attr-defined]
    print(f"Trade-finance demo server on http://{args.host}:{args.port}  (Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()
