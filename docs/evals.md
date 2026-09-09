# How the trade finance checker is evaluated

Read this page if you decide what this service is allowed to call compliant. The metrics, the
bars and the corpus below are generated from the artifacts that actually gate the build, so they
cannot drift from what runs: `make evals-doc-check` fails the build when this page and those
artifacts disagree.

## How to run it

```sh
make eval              # offline, no credentials
make evals-doc-check   # this page is still true
```

`make check` runs both on every change.

## The corpus grew, and the reason is arithmetic

It carried eight expected discrepancies across fourteen presentations: one per kind, no case with
two at once, and no boundary anywhere. Two things follow, and neither is visible in a green
result.

**The recall bar was a 1.0 wearing a 0.90 label.** A 0.90 threshold tolerates one miss only over
ten scored positives; over eight, missing one scores 0.875 and fails. A reviewer reading 0.90
believed in headroom that was never there.

**One discrepancy per case is not what a presentation looks like.** A detector that stops at the
first finding scores full marks on that corpus. Nothing measured whether it finds the second
problem once it has found the first.

Three shapes were added, each of which the old corpus could not express:

- **Simultaneous discrepancies**: cases carrying two, three and four at once.
- **The Article 14 near-miss**, on both sides of the configured description-overlap floor:
  wording that differs and means the same thing must be ACCEPTED, wording that differs enough must
  be refused. A corpus of obvious mismatches pins neither side of that line.
- **The amount and latest-shipment boundaries** at the configured policy: exactly at the credit
  and one cent over, on the last shipment day and one day after. A boundary nobody tested is a
  boundary that moves in a refactor.

## What is measured, and against what bar

Every bar below lives in `eval/rubrics/*.yaml` next to the argument for it, and the
runner reads it from there. There is no dict of thresholds in the runner any more: a
metric scored with no reviewed bar fails the build, and so does a bar that names no
metric, which is the direction that rots quietly because it rots toward looking well
governed.

The third column is the denominator rule, and it applies only where a score is a
FRACTION over scored positives: such a threshold `t` tolerates a single miss only over
at least `1/(1-t)` of them. `all or nothing` marks a bar that already asks for no
headroom, so a bigger corpus would not change what it means. Each rubric declares which
it is rather than the rule being guessed from the number.

| Metric | Bar | Denominator | What it measures |
|---|---|---|---|
| `citation_accuracy` | 0.9 | a rate; needs 10 positives | Fraction of detected discrepancies that carry both a UCP600 article reference and at least one citation (LC term / UCP600 article / document). Every discrepancy must be traceable to the rule it breaches (P-07); an uncited finding is not actionable by an examiner. |
| `discrepancy_precision` | 0.9 | a rate; needs 10 positives | Fraction of detected discrepancies that are genuine (present in the ground truth). On a clean presentation any detected discrepancy is a false positive; false discrepancies waste officer time and erode trust, so precision is gated equally hard. |
| `discrepancy_recall` | 0.9 | a rate; needs 10 positives | Fraction of the planted discrepancies (per the golden ground truth) that the deterministic detector actually finds, averaged over the golden presentations. A trade-finance checker that misses real discrepancies is worse than useless, so the bar is high. |
| `pii_safety` | 0.99 | a rate; needs 100 positives | Fraction of checks in which no raw trade-party PII token (NRIC, email, account number) leaks into the drafted narrative or any audited record. PII is redacted at the boundary before any model call, span, or audit write (P-04 / R1), so a leak is a hard failure: the bar is 0.99. |

Scored over 27 golden presentations.

## What is exercised

- **27 golden presentations** in
  `eval/datasets/golden_presentations.jsonl`, carrying **27 expected discrepancies**
  across **7 distinct UCP600 kinds**. That count is what `discrepancy_recall`
  is measured over, not the case count.
- **6 of them carry more than one discrepancy at once.** A detector that stops at
  the first finding scores full marks on a one-per-case corpus and fails here.
- **9 clean presentations**, which is what a false positive can fire on. The
  runner refuses a corpus with almost nothing clean, because precision over a corpus of
  discrepant files cannot catch a detector that cries wolf.
- **4 presentations plant a raw identifier**, so the leak metric has a target it
  could miss.

## How a metric is prevented from being decoration

1. **The bars are read from the rubrics, in both directions.** There is no `THRESHOLDS` dict any
   more. What was here before was both a dict and a loader that overlaid two rubric files on top
   of it, silently falling back to the dict when PyYAML was missing.
2. **The denominator rule is asserted against what actually divides each rate.** Recall over the
   expected discrepancy KINDS, precision over the kinds the detector CLAIMED. Neither is the case
   count.
3. **The corpus must contain clean presentations.** Precision is scored on whether the detector
   stays silent on a file with nothing wrong with it, and a corpus of discrepant files cannot
   catch one that cries wolf. The runner refuses a corpus with almost nothing clean.

## What is NOT measured here

- **A real model's words.** Detection is deterministic here; the narrative that explains a
  discrepancy is not scored.
- **Production traffic.** Everything here is a golden set. Nothing samples live requests.
