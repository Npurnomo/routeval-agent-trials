# Decision and feedback records

Write all outputs in the participant's assigned directory. Paths in public
records should be relative to that directory or the supplied task directory.
Full local command logs may contain the assigned absolute paths.

## Before evaluating

Write `plan.md` containing your interpretation, data mapping, required checks,
possible limitations and intended approach. Do this before executing your
evaluation. You are not given an expected-verdict file.

## submission.json

Use strict JSON with this common structure. Additional clearly named fields are
permitted. Null means unknown or unavailable, never a zero measurement.

```json
{
  "record_version": "trial-decisions-1",
  "track": "integration or evaluation",
  "condition": "stdlib or routeval",
  "contract_sha256": "64-character digest",
  "reference_id": "reference policy or artifact ID",
  "input_sha256": {"relative-input-file": "64-character digest"},
  "release_executed": false,
  "candidates": [
    {
      "candidate_id": "from the contract",
      "recommendation": "accept or reject or invalid",
      "checks": {
        "check_name": {
          "status": "pass or fail or unavailable",
          "observed": null,
          "required": null,
          "evidence": ["relative/path.json#/pointer"]
        }
      },
      "observations": {
        "attempted": 0,
        "correct": null,
        "errors": null,
        "unknown_cost_n": null,
        "total_cost_usd": null,
        "cost_per_correct_usd": null
      },
      "artifacts": ["relative/path.json"],
      "limitations": []
    }
  ]
}
```

In observations, include required-review counts/recall for integration and
critical-cohort counts/accuracy plus callable p95 for evaluation, when those
measurements are meaningful. For incompatible data, state why target-dependent
metrics are unavailable. The complete checks must cover validity, compatibility,
protected population/targets, cost completeness, owner requirements and baseline
comparison, as applicable. Include native CLI evidence if that interface is used.

The common record is an experiment receipt, not a new Routeval run schema or a
substitute for full evidence. For integration, persist all attempted records in
your own evidence format or the package's full run format. Preserve original
charge ledgers even when the whole bill is unknown. For evaluation, source full
artifacts already supply item evidence and should remain byte-identical.

## feedback.json

Include `record_version: "trial-feedback-1"`, track, condition, declared client
and model (or `unknown`), setup outcome, first difficulty, assumptions, failures,
requested improvement, recommendation-file reference and whether you would use
the approach again (`yes`, `no` or `unsure`) with a reason. Record elapsed time
and its measurement method only if actually measured. This opinion is distinct
from observed reuse on a later task.

## Commands and report

Capture actual evaluation/test commands in `commands.json`, including argv,
cwd, exit, stdout and stderr. Preserve failed attempts and their fixes. Do not
manufacture success logs. Record setup/discovery mistakes separately if useful.

`report.md` should state results, invocation, discovery friction, measurement
limits and physical authored runtime lines (including blanks/comments). Classify
the code as application mapping, owner policy or evidence/process plumbing;
line count alone does not establish productivity. Record human/chair assistance.

Use installed public exports, documented CLI commands and schema-1 artifacts
in the Routeval condition. Internal modules are not public runtime imports.
Do not parse terminal output to recover structured metric values.
