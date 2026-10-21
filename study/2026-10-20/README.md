# Does Routeval help an agent do the work?

Sessions ran October 20, 2026; chair scoring and publication preparation completed
October 21. Routeval 0.1.1, synthetic data, no provider calls.

## Result

All **22 submitted candidate judgments** matched the expected outcomes frozen
before dispatch. Both ordinary Python and Python with Routeval completed both
tasks correctly. One session per condition cannot establish a general advantage.

| Session | Task | Available approach | Correct judgments | Main runtime lines | Audit/setup/report lines | Measured elapsed seconds |
|---|---|---|---|---:|---:|---:|
| A | Integrate an existing app | Python standard library | 4/4 | 301 | 108 | 268.4 |
| B | Integrate an existing app | Python + Routeval | 4/4 | 295 | 109 | 235.0 |
| C | Evaluate saved runs | Python standard library | 7/7 | 429 | 129 | 398.7 |
| D | Evaluate saved runs | Python + Routeval | 7/7 | 350 | 206 | 289.0 |

Physical lines include blanks and comments. Main runtime includes the evaluator
and batch/command capture; the other column contains saved tests, discovery and
report generation. Preserved revision copies and interactive snippets are
excluded. These implementations cover different defensive checks. Neither line
counts nor elapsed wall-clock times establish productivity: inference/tool
latency, scheduling and implementation choices were uncontrolled. Prepared
environment installation was excluded. All sessions met the ten-minute budget.

## What Routeval supplied

For integration, public Harness/Decision/scorer exports supplied attempted-case
recording, scoring, aggregates, route-role metrics, schema-1 evidence and baseline
gates. The caller still mapped nested billing, preserved original charge ledgers
and enforced absolute owner limits. Main runtime size was similar in this pair.

For saved-run evaluation, the native compare CLI supplied schema, compatibility
and watched-baseline evidence. The caller still implemented critical-cohort,
full callable-latency and per-ID target protection checks. It also reconstructed
aggregates and comparison deltas to produce structured evidence because the
public interface returned a process result and terminal report. No terminal
tables were scraped and no private runtime modules were imported.

The standard-library participants built their own metric/comparison/evidence
logic. That worked on the supplied tasks. Maintaining those checks is a
plausible package benefit, which this small experiment does not quantify.

## Actual subsequent reuse

After originals were frozen and scored, all four participants received new saved
inputs and access to the same prepared Routeval environment. Each had five
minutes and could choose any permitted approach. All **six follow-up judgments**
were correct; report these separately from the initial 22.

| Session | Observed choice | Follow-up judgments | What changed |
|---|---|---|---|
| A | Reused standard-library evaluator | 2/2 | Existing evaluator copied unchanged |
| B | Reused Routeval integration | 2/2 | New policy data, existing mapping and gates |
| C | Reused standard-library consumer | 1/1 | Corrected per-route p95 handling for missing latency |
| D | Reused Routeval comparison plus caller rules | 1/1 | Missing callable latency remained unknown; native exit 3 |

Both initially assigned package users reused it. Neither control inspected or
tried it after it became available. Existing working code and the same owner
contract strongly influenced these choices. This demonstrates continued use
within a controlled exercise; it does not establish outside adoption or that
agents prefer Routeval. Feedback JSON contains opinions separately from these
observed choices.

## Next product hypotheses

1. **Structured comparison results:** a public API or JSON CLI result containing
   validation diagnostics and watched-metric decisions could reduce duplicate
   saved-run inspection code. Test against a new stdlib control before claiming
   an improvement.
2. **Billing examples:** demonstrate known partial charges, unknown whole totals,
   zero-price review roles and billed failures in a runnable app adapter. Clarify
   Harness.run's returned artifact and invalid-comparison behavior.
3. **Visible owner rules:** keep critical cohorts, latency, trusted targets and
   absolute limits explicit. A native baseline pass does not establish owner
   acceptance. A reusable skill remains a later experiment.

These are proposals arising from observed work and participant feedback, not
features shipped in Routeval 0.1.1.

## Method and evidence

The first input commit is
`3dcc6c23b26cb42665b4809bc555818c6788d39f`. There were 21 protected initial
files; their hashes matched before scoring. Thirteen data/code fixtures were
preflighted, and expected judgments were withheld. Golden targets and original
charge records stayed unchanged. The follow-up's seven fixed files also matched.

All four final receipts passed shape, hash and link checks: **986 check evidence
links** resolved. Focused chair code review examined preservation, denominators,
measurement precedence and required owner checks. Link resolution alone does not
prove a check's semantic correctness or authenticate the underlying measurements.
All four portable replays reproduced the 22 recommendations and valid receipts.

In-session corrections are retained locally: C improved validation/evidence paths
and D corrected shared-null reporting and recorded-decimal comparisons. Their
candidate recommendations were unchanged in the saved earlier revisions. The
chair's receipt checker initially rejected task-relative input links permitted by
the contract; it was corrected without editing D's submission. See
chair-corrections.json and revision-audit.json.

Published here: frozen protocol, initial scores, expected outcomes, input hashes,
receipt audit, focused code-review findings, original feedback, follow-up scores
and redacted choice records. `frozen-inputs.json` describes the initial commit;
the README and other documentation later changed for publication. The data/code
hashes in `fixture-hashes.json` still apply. Full local original bundles, command
logs, revision snapshots and digest indexes remain in the chair archive.
Unmodified runtime files and their digests are published under solutions/;
tools/run_reference.py adds portable reproduction plumbing after the experiment.
Choice records replace local workspace/environment prefixes with placeholders.

## Limits

Four fresh AI contexts used inherited settings; exact served model IDs were not
disclosed. These are not four different models, independent customers or an
estimate of real-world reliability. Shared-workspace restrictions were enforced
by instructions and hashes, not OS-level isolation. There was no author coaching
after assignment, and no external-user trial. All prices, records and latencies
were synthetic. No real billing, production latency, deployment safety, willingness
to pay or market demand was established. The current environment used Python
3.14.6; a supported-version matrix was not run.

Now that inputs and answers are public, these are learning fixtures. A new
controlled study needs fresh held-out tasks and expected outcomes.
