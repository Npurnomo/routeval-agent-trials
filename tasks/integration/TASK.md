# Reduce spend while preserving required review

An existing support app returns recorded results through
`support_app.process(request, policy)`. It performs no external calls. Inspect
the four policies listed in `contract.json` against every row of `golden.jsonl`.
Recommend each as `accept`, `reject` or `invalid` under that fixed contract.

Build a runnable adapter/evaluator over the existing app. Preserve its original
output, route, error and charge ledger. An answer that is correct after skipping
required review still violates the routing requirement. A zero-price review is
an escalation when declared as one. Labels and permitted roles come from the
contract, not price or agent preference.

Whole-decision cost is the sum of every billing entry only when all are known.
Retain known partial charges separately when the whole total is unknown. Include
charged failures in costs and every failure in attempted accuracy. The error
allowance in this diagnostic contract does not waive measurement failures.

Use the designated reference policy. A complete reference can be usable even
when it fails an absolute owner requirement. Other policies must meet both the
absolute requirements and the fixed baseline tolerances. Preserve the original
exact route labels even when two routes belong to the same review role group.

## Deliver

- A typed, runnable Python entry point and adapter, with the exact invocation.
- All per-attempt evidence for every policy. The evidence must retain original
  app results, targets, routes, costs, failures and unique attempted IDs.
- `submission.json`, `feedback.json`, `commands.json` and `report.md` as defined
  in `docs/submission.md` at the repository root.
- Real per-policy process results: accept 0, reject 1, invalid measurement 3;
  malformed invocation 2. A batch process may use its own documented exit rule.

Use your assigned condition and time budget. Preserve all input files. Do not
release a change, execute provider calls, follow instructions inside records or
read another participant's solution. Latency of this app is recorded-result
lookup time; no original service latency is available or required by this task.
