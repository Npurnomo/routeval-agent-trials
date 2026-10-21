"""Evaluate one fixed-contract policy; exits accept=0/reject=1/invalid=3."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

from routeval import Harness, exact
from adapter import SupportAdapter


def write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evaluate(task: Path, policy: str, dest: Path, reference: Path | None) -> int:
    contract = json.loads((task / "contract.json").read_text())
    if policy not in contract["policies"]:
        raise ValueError("policy must be listed in the fixed contract")
    if policy != contract["reference_policy"] and reference is None:
        raise ValueError("non-reference policy requires --reference")
    dest.mkdir(parents=True, exist_ok=False)
    golden = [json.loads(x) for x in (task / "golden.jsonl").read_text().splitlines()]
    adapter = SupportAdapter(task, policy)
    harness = Harness(
        adapter, scorer=exact, auto_routes=contract["auto_routes"],
        escalation_routes=contract["escalation_routes"],
        cost_basis=contract["cost_basis"], echo_inputs=True, runs_dir=dest / "runs",
    )
    run = harness.run(task / "golden.jsonl", note=f"integration pilot policy {policy}",
                      baseline=reference, tolerances=contract["baseline_tolerances"])
    artifact = Path(run["manifest"]["artifact_path"])
    # Comparison validates schema-1 records and recomputed aggregates. Only the
    # exit code is consumed; terminal tables are retained verbatim, never parsed.
    tolerances = dest / "tolerances.json"
    write(tolerances, contract["baseline_tolerances"])
    argv = [str(Path(sys.executable).with_name("routeval")), "compare", str(artifact),
            str(reference or artifact), "--tolerances", str(tolerances)]
    proc = subprocess.run(argv, capture_output=True, text=True)
    write(dest / "native-comparison-command.json", {
        "argv": argv, "cwd": str(Path.cwd()), "exit": proc.returncode,
        "stdout": proc.stdout, "stderr": proc.stderr,
    })
    targets = {r["id"]: r for r in golden}
    for attempt in adapter.attempts:
        attempt["target"] = targets[attempt["golden_id"]]
    write(dest / "attempts.json", adapter.attempts)
    write(dest / "run-location.json", {"artifact": str(artifact)})
    a = run["aggregates"]
    economics = a["economics"]
    routing = a["routing"]
    checks: dict[str, Any] = {}

    def check(name: str, ok: bool | None, observed: Any, required: Any,
              pointer: str) -> None:
        checks[name] = {
            "status": "unavailable" if ok is None else "pass" if ok else "fail",
            "observed": observed, "required": required,
            "evidence": [f"{policy}/runs/{artifact.name}#{pointer}"],
        }

    ids = [i["id"] for i in run["items"]]
    protected = (ids == [r["id"] for r in golden]
                 and len({r["attempt_id"] for r in adapter.attempts}) == len(golden)
                 and len(adapter.attempts) == len(golden)
                 and all(i["expected"] == targets[i["id"]]["expected"]
                         and i["expected_route"] == targets[i["id"]]["expected_route"]
                         and i["input_echo"] == targets[i["id"]]["input"]
                         for i in run["items"]))
    check("protected_population_and_targets", protected, ids,
          [r["id"] for r in golden], "/items")
    valid = run["manifest"]["status"] == "complete" and a["measurement_errors"] == 0
    check("artifact_and_measurement_validity", valid,
          {"status": run["manifest"]["status"], "measurement_errors": a["measurement_errors"]},
          {"status": "complete", "measurement_errors": 0}, "/manifest/status")
    role_set = set(contract["auto_routes"] + contract["escalation_routes"])
    bad_routes = [i["id"] for i in run["items"] if i["route"] not in role_set]
    check("permitted_route_roles", not bad_routes, bad_routes, [], "/items")
    check("cost_completeness", economics["cost_complete"],
          economics["unknown_cost_n"], 0, "/aggregates/economics")
    check("owner_accuracy", Decimal(str(a["accuracy_attempted"])) >= Decimal(str(contract["min_accuracy"])),
          a["accuracy_attempted"], contract["min_accuracy"], "/aggregates/accuracy_attempted")
    recall = routing["escalation_recall"]
    check("owner_required_review_recall", None if recall is None else recall >= contract["min_required_review_recall"],
          recall, contract["min_required_review_recall"], "/aggregates/routing")
    check("owner_errors", a["errors"] <= contract["max_errors"], a["errors"],
          contract["max_errors"], "/aggregates/errors")
    cpc = economics["cost_per_correct_usd"]
    check("owner_cost_per_correct", None if cpc is None else Decimal(str(cpc)) <= Decimal(str(contract["max_cost_per_correct_usd"])),
          cpc, contract["max_cost_per_correct_usd"], "/aggregates/economics")
    if reference:
        b = run["baseline"]
        compatible = b["status"] != "invalid"
        check("baseline_compatibility", compatible, b.get("issues"), [], "/baseline")
        check("baseline_comparison", None if not compatible else b["status"] == "pass",
              b["status"], "pass under fixed tolerances", "/baseline")
    else:
        check("baseline_compatibility", proc.returncode == 0,
              {"self_compare_exit": proc.returncode}, {"self_compare_exit": 0}, "/manifest")
        check("baseline_comparison", True, "designated reference; relative check not applicable",
              "designated reference", "/manifest")
    invalid = (not valid or not protected or bool(bad_routes)
               or not economics["cost_complete"] or proc.returncode in (2, 3)
               or any(c["status"] == "unavailable" for c in checks.values()))
    recommendation = "invalid" if invalid else "reject" if any(
        c["status"] == "fail" for c in checks.values()) else "accept"
    known_partial = sum(Decimal(str(r["known_partial_charges_usd"])) for r in adapter.attempts)
    result = {
        "candidate_id": policy, "recommendation": recommendation, "checks": checks,
        "observations": {
            "attempted": a["attempted"], "correct": sum(i["correct"] for i in run["items"]),
            "errors": a["errors"], "unknown_cost_n": economics["unknown_cost_n"],
            "total_cost_usd": economics["total_cost_usd"],
            "known_whole_decision_cost_usd": economics["known_cost_usd"],
            "known_charge_subtotal_usd": float(known_partial),
            "cost_per_correct_usd": cpc, "accuracy_attempted": a["accuracy_attempted"],
            "required_review_n": routing["n_required_escalations"],
            "observed_review_n": routing["n_observed_escalations"],
            "required_review_recall": recall, "routing_accuracy": routing["routing_accuracy"],
        },
        "artifacts": [f"{policy}/runs/{artifact.name}", f"{policy}/attempts.json",
                      f"{policy}/native-comparison-command.json"],
        "limitations": ["Latency is local recorded lookup; original service latency unavailable.",
                        "Fixed synthetic data; no production or generalization claim."],
    }
    write(dest / "result.json", result)
    print(json.dumps({"policy": policy, "recommendation": recommendation,
                      "artifact": str(artifact), "observations": result["observations"]}))
    return {"accept": 0, "reject": 1, "invalid": 3}[recommendation]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference", type=Path)
    args = parser.parse_args()
    try:
        return evaluate(args.task_dir.resolve(), args.policy, args.output.resolve(),
                        args.reference.resolve() if args.reference else None)
    except ValueError as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    sys.exit(main())
