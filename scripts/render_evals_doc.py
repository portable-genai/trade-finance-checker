#!/usr/bin/env python3
"""Regenerate the derived half of ``docs/evals.md`` from the rubrics, golden sets and floors.

A page that lists metrics and thresholds by hand goes stale the first time a bar moves, and
nothing notices. This repository had exactly that: the bars lived in a Python dict AND in the
rubric files, and the two could disagree without anything failing. The dict is gone; this
makes the prose derived too.

    make evals-doc          # rewrite the generated sections
    make evals-doc-check    # non-zero when the page and the artifacts disagree (runs in check)

Only the sections named in :data:`BLOCKS` are generated. Everything else on the page is
hand-written prose addressed to a reviewer, and this script does not touch it: the point is a
document a person wrote, whose FACTS cannot drift from the artifacts they describe.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml
from agent_eval_kit import load_jsonl, load_rubrics, render_main, required_positives
from agent_eval_kit.rubrics import Rubric

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "eval"))
sys.path.insert(0, str(_REPO_ROOT / "src"))

DOC = _REPO_ROOT / "docs" / "evals.md"
RUBRICS = _REPO_ROOT / "eval" / "rubrics"
GOLDEN = _REPO_ROOT / "eval" / "datasets" / "golden_presentations.jsonl"

#: The headings this script owns. Each runs from its heading to the next `\n## `.
BLOCKS = (
    "## What is measured, and against what bar",
    "## What is exercised",
)


def _denominator_kind(rubric: Rubric) -> str:
    """What a rubric says its bar is measured over. Read, never guessed from the number.

    0.99 is both the bar a leak metric carries (one leak anywhere fails it) and a perfectly
    ordinary rate. Guessing from the number would print "needs 100 cases" beside a metric a
    corpus of one already gates correctly, which is a confident wrong answer.
    """
    document = yaml.safe_load(Path(rubric.source).read_text(encoding="utf-8")) or {}
    declared = document.get("denominator") or {}
    node = declared.get(rubric.metric, declared) if isinstance(declared, dict) else {}
    if not isinstance(node, dict):
        node = {}
    return str(node.get("kind", "rate"))


def _metrics_block() -> list[str]:
    rubrics = load_rubrics(RUBRICS)
    cases = load_jsonl(GOLDEN)
    lines = [
        BLOCKS[0],
        "",
        "Every bar below lives in `eval/rubrics/*.yaml` next to the argument for it, and the",
        "runner reads it from there. There is no dict of thresholds in the runner any more: a",
        "metric scored with no reviewed bar fails the build, and so does a bar that names no",
        "metric, which is the direction that rots quietly because it rots toward looking well",
        "governed.",
        "",
        "The third column is the denominator rule, and it applies only where a score is a",
        "FRACTION over scored positives: such a threshold `t` tolerates a single miss only over",
        "at least `1/(1-t)` of them. `all or nothing` marks a bar that already asks for no",
        "headroom, so a bigger corpus would not change what it means. Each rubric declares which",
        "it is rather than the rule being guessed from the number.",
        "",
        "| Metric | Bar | Denominator | What it measures |",
        "|---|---|---|---|",
    ]
    for rubric in rubrics:
        if _denominator_kind(rubric) == "all-or-nothing":
            needs = "all or nothing"
        else:
            needs = f"a rate; needs {required_positives(rubric.threshold)} positives"
        lines.append(
            f"| `{rubric.metric}` | {rubric.threshold:g} | {needs} | {rubric.description} |"
        )
    lines += ["", f"Scored over {len(cases)} golden presentations.", ""]
    return lines


def _exercised_block() -> list[str]:
    cases = load_jsonl(GOLDEN)
    kinds = sum(len(row["expected_discrepancy_kinds"]) for row in cases)
    multi = sum(1 for row in cases if len(row["expected_discrepancy_kinds"]) > 1)
    clean = sum(1 for row in cases if not row["expected_discrepancy_kinds"])
    distinct = len({kind for row in cases for kind in row["expected_discrepancy_kinds"]})
    planted = sum(1 for row in cases if row.get("pii_in_inputs"))
    return [
        BLOCKS[1],
        "",
        f"- **{len(cases)} golden presentations** in",
        f"  `eval/datasets/golden_presentations.jsonl`, carrying **{kinds} expected discrepancies**",
        f"  across **{distinct} distinct UCP600 kinds**. That count is what `discrepancy_recall`",
        "  is measured over, not the case count.",
        f"- **{multi} of them carry more than one discrepancy at once.** A detector that stops at",
        "  the first finding scores full marks on a one-per-case corpus and fails here.",
        f"- **{clean} clean presentations**, which is what a false positive can fire on. The",
        "  runner refuses a corpus with almost nothing clean, because precision over a corpus of",
        "  discrepant files cannot catch a detector that cries wolf.",
        f"- **{planted} presentations plant a raw identifier**, so the leak metric has a target it",
        "  could miss.",
        "",
    ]


def render() -> str:
    """The page, with the generated blocks replaced and the hand-written prose untouched."""
    text = DOC.read_text(encoding="utf-8")
    missing = [heading for heading in BLOCKS if heading not in text]
    if missing:
        raise SystemExit(
            f"{DOC}: missing generated section(s) {missing}. This script replaces named "
            "headings; it does not invent them, because a page it could create from nothing "
            "would silently replace one a person wrote."
        )
    generated = {
        BLOCKS[0]: _metrics_block(),
        BLOCKS[1]: _exercised_block(),
    }
    out: list[str] = []
    skipping = False
    for line in text.splitlines():
        if line in generated:
            out.extend(generated[line])
            skipping = True
            continue
        if skipping:
            if line.startswith("## "):
                skipping = False
            else:
                continue
        out.append(line)
    return "\n".join(out).rstrip("\n") + "\n"


if __name__ == "__main__":
    raise SystemExit(
        render_main(
            output=DOC,
            render=render,
            description="Regenerate docs/evals.md from the rubrics, golden sets and floors.",
            argv=sys.argv[1:],
        )
    )
