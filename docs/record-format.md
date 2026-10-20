# Run artifact contract — schema 1

Packages 0.1.x write `schema_version: "1"`. This is a breaking change from the
unreleased source harness's schema 0. Regenerate schema-0 runs with the same
examples and an explicitly declared route policy; they cannot gate a comparison.
The PyPI 0.0.1 placeholder has no harness.

## Top level and persistence

A full artifact contains `schema_version`, `manifest`, `items`, `aggregates`,
and optionally `baseline`. All values are strict JSON: no NaN, infinity, or
repeated object keys. SHA-256 digests are full 64-character hex strings.

`manifest` fields:

| Field | Contract |
|---|---|
| run_id | UUID4 hex; also part of the filename |
| harness_version | Installed package version |
| started_at / finished_at | UTC ISO 8601 timestamps |
| status | `complete` or `measurement_failed` (scorer/validation error) |
| git_sha | Current directory's commit, or null outside Git |
| config_hash | Digest of scorer, roles, pricing digest, cost basis, echo flag, schema |
| golden_set | `{path, sha256, n}`; file digest covers exact bytes; in-memory digest covers canonical JSON |
| pricing_file | `{source: "user" or "bundled", sha256}`; digest covers loaded pricing contents |
| scorer | `{id, version}`; custom version may be null for exploratory runs, but cannot compare |
| route_policy | `{auto_routes: [str], escalation_routes: [str]}`; sorted, unique, disjoint |
| cost_basis | Nonempty description such as `api-only`, `deployment`, or `api-and-human` |
| note | User's free-form note |
| artifact_path | Present when written to disk; omitted with `runs_dir=None` |

Runs write `run-<UTC time>-<UUID>.json`. Serialization finishes before disk
writes; a temporary file on the same volume is replaced atomically. The saved
artifact includes its path and the completed baseline block and equals the
returned Python value. Same-second runs have different filenames.

## Golden set and item records

JSONL rows require `input` and `expected` (any JSON values). Optional nonempty
string `id` defaults to the row index; IDs must be unique. Optional nonempty
string `expected_route` and `tier` are labels. Empty sets, duplicate IDs,
malformed JSON, nonfinite values, and invalid labels are rejected before calls.

Each attempted item records:

- `id`, `input_hash`, `expected`, `expected_route` or null, `tier` or null;
- `answer`, `correct` (strict bool), `route` (nonempty string or null on failure);
- `cost_usd` (finite nonnegative USD or null), `cost_source`
  (`reported`, `estimated`, or `unknown`), `model` or null;
- `tokens`: `{in: int, out: int}` for a validated decision, otherwise null;
- `latency_ms`: finite nonnegative pipeline execution time, excluding scoring;
- `stages`: optional user-supplied JSON object, otherwise null;
- `error`: string or null; `error_stage`: `pipeline`, `validation`, `scorer`, or null;
- `input_echo` only when explicitly enabled.

`Decision.error` retains known route, answer, and cost on execution failure.
A thrown exception has unknown cost and route. Independently valid explicit
cost survives a malformed decision. Scorer failures retain all valid pipeline
fields. Errors set correctness false, and every row is attempted exactly once.
Scorers must return bool; threshold numerical judge scores in your wrapper.

## Aggregate definitions

Definitions live in `metrics.py`; renderers use these recorded values.

| Field | Denominator or meaning |
|---|---|
| attempted | All attempted items |
| succeeded | Items without an execution or measurement error; may have wrong answers |
| errors | All non-null item errors |
| measurement_errors | Scorer or decision validation errors |
| accuracy_attempted | Correct / attempted, including errors |
| per_route.<route>.n / share | Actual route count / attempted; unknown route gets `[unknown route]` |
| per_route.<route>.accuracy | Correct / all items on that actual route |
| per_route.<route>.errors | Errored items on that route |
| per_route cost fields | Known subtotal, complete total or null, complete mean or null, unknown count |
| per_route.<route>.p95_latency_ms | Nearest-rank p95 of pipeline execution time |
| economics.known_cost_usd | Sum of known costs, **not** an estimate of total spend |
| economics.total_cost_usd | Sum only if every item has known cost; otherwise null |
| economics.cost_per_correct_usd | Complete total / correct count; null if cost incomplete or zero correct |
| economics.cost_complete / unknown_cost_n | Whether every cost is known / missing-cost count |
| economics.deflection_rate | Successful automatic completions / attempted; null if auto roles undeclared |
| economics.auto_routes | Explicit automatic role declarations |

Explicit cost wins over token pricing. Tokens price one model invocation;
users must report whole-decision totals for cascades or multiple calls.
Zero means no spend under the declared cost basis; missing means unknown.
Bundled rates describe toy models and local zero API spend, not current paid
provider prices. No currency conversion or inference of human/compute cost. Cost covers the
pipeline; scorer/judge charges are not added automatically.

### Routing (present only with at least one expected_route label)

Every routing denominator uses **labelled attempted items**; never silently
extrapolate to unlabelled items. `n_labelled` and `label_coverage = labelled /
attempted` expose that scope. Label agreement is not counterfactual optimality.

- `routing_accuracy`: actual route equals expected route / labelled items.
- `grid`: counts `route_right_verdict_right`, `route_right_verdict_wrong`,
  `route_wrong_verdict_right`, `route_wrong_verdict_wrong`.
- `correct_answer_wrong_route_rate`: correct verdict AND different route /
  labelled attempted items. `lucky_hit_rate` is a deprecated equal-value alias;
  it does not establish that an answer was luck.
- `escalation_routes`: explicit escalation role declarations.
- `escalation_precision`: labelled escalations whose expected route belongs to
  the escalation group / labelled observed escalations. Null with no observed
  escalations or no declared escalation role.
- `escalation_recall`: correctly escalated / labelled required escalations.
  **Zero**, not null, when escalation was required but none occurred. Null if
  none were required or roles are undeclared.
- `n_required_escalations`, `n_observed_escalations`: group counts on labelled
  cases; zero when group roles are undeclared.

Groups permit several escalation paths; exact route agreement still
requires the exact expected name. A failed attempt can have a known route:
route correctness remains distinct from final-answer correctness.

Optional `stages.<name> = {n, accuracy}` tallies only explicit boolean
`stages[name].correct`. Each stage denominator is its own scored records;
coverage is not assumed to equal all attempted items.
Stage scores are diagnostic and are not watched by the built-in baseline gate.
The handoff recipe demonstrates a separate coverage and quality check.

## Baselines and exit codes

Compare only complete schema-1 artifacts with recomputable item aggregates,
no measurement errors, matching golden-set/pricing digests, scorer identity
and version, route policy, and cost basis. A change of code commit is expected.
Built-in scorer versions describe scoring rules, not the installed package
version; 0.1.1 retains the 0.1.0 rule version because those rules are unchanged.
Adding route labels changes the golden-set digest and requires a new baseline.
Notes and external policy/rate files are not automatically hashed into comparison
compatibility; record and control them in your application.
Full provenance helps reproducibility but is not a signature or tamper-proof
attestation. File and list golden inputs have different hash conventions.

Every cost must be known. A watched metric present on one side and null on the
other invalidates comparison (including a run with zero correct answers).
A metric null on both sides is skipped; this is why independent minimum
quality limits are useful. Removing all observed escalations gives recall zero
when labels require them, so the safety regression stays measurable.

Default tolerances:

| Metric | Allowed deterioration |
|---|---|
| accuracy_attempted | 0.02 absolute |
| routing_accuracy | 0.05 absolute |
| correct_answer_wrong_route_rate | 0.05 absolute increase |
| escalation_recall | 0.05 absolute |
| errors | 0 additional errors |
| cost_per_correct_usd | 0.25 relative increase |
| cost_zero_absolute_usd | $0 increase when baseline cost per correct is zero |

Only strictly greater deterioration fails. From 0.1.1, gating compares the
recorded numbers' round-trip decimal values using exact arithmetic; it does not
add an epsilon or widen tolerances. Exactly at the boundary passes, and a
representable recorded value beyond it fails. Displayed/stored float deltas
remain unchanged. This fixes binary subtraction/division noise at boundaries.
`--tolerances file.json` accepts an
object overriding these named finite nonnegative values. Zero-baseline costs
use the explicit absolute USD tolerance, so a free-to-paid change cannot be
silently skipped.
Escalation precision, stage scores, latency and automatic completion rate are
outside this comparison's watched metrics. Terminal output identifies active
tolerances and unavailable checks. A pass only covers requested, measured gates.

`baseline` records `path`, `baseline_run_id`, `baseline_started_at`,
`tolerances`, `deltas` (before/now/delta/optional regression true),
`regressions`, `issues`, `status` (`pass`, `regression`, `invalid`), and
`exit_code` (0/1/3).

CLI exit codes: **0** requested gates passed; **1** regression/quality failure
or execution errors unless explicitly allowed; **2** input/config failure or
incompatible baseline rejected before execution; **3** invalid/incomplete
measurement or comparison. Exploratory runs may have incomplete cost and exit
0 if no cost/baseline gate is requested. Optional CLI minimum accuracy,
minimum escalation recall, and maximum cost-per-correct limits fail nonzero
when violated or unavailable. Measurement failures always exit 3.

## Sharing and migration

Full artifacts contain expected answers, outputs, stage content, errors, IDs,
and hashes. Omitting input_echo does **not** anonymize a run.
`routeval summary` emits `summary_only: true`, four non-identifying manifest
fields, aggregates, and optional baseline status/exit/deltas/regressions.
It removes item content, hashes, paths, identifiers, notes, and free-form
comparison issues. Review route and stage names before sharing. Summaries
lack items and cannot gate comparisons.

Migration from schema 0: declare route roles; report costs or supply user
pricing; use a versioned scorer; regenerate golden-set baselines; replace
inferred expensive/cheap route fields with explicit roles; use the descriptive
mismatch metric instead of its legacy alias. This batch changes no Quorum
storage schema or settled architecture decisions.
