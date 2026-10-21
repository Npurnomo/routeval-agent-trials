"""Standard-library support-app adapter and contract evaluator. No provider calls."""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
from typing import Any
from uuid import uuid4

sys.dont_write_bytecode = True
Json = Any


def pairs(items: list[tuple[str, Json]]) -> dict[str, Json]:
    result: dict[str, Json] = {}
    for key, value in items:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load(text: str) -> Json:
    def bad(value: str) -> None:
        raise ValueError(f"nonfinite JSON: {value}")
    return json.loads(text, object_pairs_hook=pairs, parse_constant=bad)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: Json) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


@dataclass
class Attempt:
    attempt_id: str
    id: str
    target: Json
    original_result: Json
    answer: Json
    route: str | None
    original_error: str | None
    error: str | None
    validation_errors: list[str]
    charge_ledger: Json
    known_partial_cost_usd: float
    cost_usd: float | None
    correct: bool
    lookup_latency_ms: float


def adapt(raw: Json, golden: dict[str, Json], roles: set[str], run_id: str,
          latency: float, exception: str | None = None) -> Attempt:
    """Map the application's full result without changing source fields."""
    problems: list[str] = []
    answer: Json = None
    route: str | None = None
    original_error: str | None = exception
    ledger: Json = None
    known = Decimal(0)
    complete = True
    try:
        answer = raw['payload']['response']
        route = raw['execution']['route']
        original_error = raw['execution']['error']
        if route not in roles:
            problems.append('undeclared or missing route')
        if original_error is not None and not isinstance(original_error, str):
            problems.append('error is not string/null')
        ledger = raw['billing']['entries']
        if not isinstance(ledger, list) or not ledger:
            raise ValueError('billing entries must be a nonempty list')
        for entry in ledger:
            value = entry.get('usd')
            if value is None:
                complete = False
            elif type(value) not in (float, int):
                complete = False
                problems.append('non-numeric charge')
            else:
                cost = Decimal(str(value))
                if not cost.is_finite() or cost < 0:
                    complete = False
                    problems.append('negative/nonfinite charge')
                else:
                    known += cost
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        complete = False
        if exception is None:
            problems.append(f'{type(exc).__name__}: {exc}')
    error = original_error or ('; '.join(problems) if problems else None)
    # JSON equality is structural, with bool distinguished from numeric values.
    correct = error is None and json.dumps(answer, sort_keys=True) == json.dumps(golden['expected'], sort_keys=True)
    return Attempt(f'{run_id}:{golden["id"]}', golden['id'], golden, raw, answer,
                   route, original_error, error, problems, ledger, float(known),
                   float(known) if complete else None, correct, latency)


def aggregate(items: list[dict[str, Json]], contract: dict[str, Json]) -> dict[str, Json]:
    """All quality and route denominators include every attempted record."""
    n = len(items)
    correct = sum(x['correct'] for x in items)
    labelled = [x for x in items if x['target'].get('expected_route')]
    review = set(contract['escalation_routes'])
    required = [x for x in labelled if x['target']['expected_route'] in review]
    observed = [x for x in labelled if x['route'] in review]
    right_review = sum(x['route'] in review for x in required)
    unknown = sum(x['cost_usd'] is None for x in items)
    known = sum((Decimal(str(x['known_partial_cost_usd'])) for x in items), Decimal(0))
    total = known if unknown == 0 else None
    return {
        'attempted': n, 'correct': correct, 'errors': sum(x['error'] is not None for x in items),
        'measurement_errors': sum(bool(x['validation_errors']) for x in items),
        'accuracy_attempted': correct / n,
        'n_labelled': len(labelled), 'label_coverage': len(labelled) / n,
        'routing_accuracy': sum(x['route'] == x['target']['expected_route'] for x in labelled) / len(labelled) if labelled else None,
        'correct_answer_wrong_route_rate': sum(x['correct'] and x['route'] != x['target']['expected_route'] for x in labelled) / len(labelled) if labelled else None,
        'n_required_reviews': len(required), 'n_observed_reviews': len(observed),
        'n_correctly_reviewed': right_review,
        'required_review_recall': right_review / len(required) if required else None,
        'escalation_recall': right_review / len(required) if required else None,
        'escalation_precision': sum(x['target']['expected_route'] in review for x in observed) / len(observed) if observed else None,
        'unknown_cost_n': unknown, 'known_partial_cost_usd': float(known),
        'total_cost_usd': float(total) if total is not None else None,
        'cost_per_correct_usd': float(total / correct) if total is not None and correct else None,
        'per_route_n': {str(route): sum(x['route'] == route for x in items) for route in sorted(set(x['route'] for x in items), key=str)},
    }


def check(status: str, observed: Json, required: Json, evidence: str) -> dict[str, Json]:
    return dict(status=status, observed=observed, required=required, evidence=[evidence])


def compare(now: dict[str, Json], before: dict[str, Json], tolerances: dict[str, Json]) -> dict[str, Json]:
    result: dict[str, Json] = {}
    decreasing = {'accuracy_attempted', 'routing_accuracy', 'escalation_recall'}
    for metric in ('accuracy_attempted', 'routing_accuracy', 'correct_answer_wrong_route_rate', 'escalation_recall', 'errors', 'cost_per_correct_usd'):
        a, b = now[metric], before[metric]
        if a is None or b is None:
            result[metric] = {'status': 'pass' if a is b else 'unavailable', 'before': b, 'now': a, 'deterioration': None, 'tolerance': tolerances[metric]}
            continue
        current, previous = Decimal(str(a)), Decimal(str(b))
        tolerance = Decimal(str(tolerances[metric]))
        if metric == 'cost_per_correct_usd':
            deterioration = (current - previous) / previous if previous else current - previous
            if not previous:
                tolerance = Decimal(str(tolerances['cost_zero_absolute_usd']))
        else:
            deterioration = previous - current if metric in decreasing else current - previous
        result[metric] = {'status': 'fail' if deterioration > tolerance else 'pass', 'before': b, 'now': a, 'deterioration': float(deterioration), 'tolerance': float(tolerance)}
    return result


def evaluate(task: Path, out: Path, policy: str, reference: Path | None) -> tuple[dict[str, Json], Path]:
    contract = load((task / 'contract.json').read_text())
    if policy not in contract['policies']:
        raise ValueError('unknown policy')
    golden = [load(line) for line in (task / 'golden.jsonl').read_text().splitlines() if line.strip()]
    roles = set(contract['auto_routes']) | set(contract['escalation_routes'])
    if not golden or len({g.get('id') for g in golden}) != len(golden):
        raise ValueError('empty golden set or duplicate IDs')
    if set(contract['auto_routes']) & set(contract['escalation_routes']):
        raise ValueError('overlapping route roles')
    for row in golden:
        if not isinstance(row.get('id'), str) or not row['id'] or not isinstance(row.get('input'), dict) or 'expected' not in row or row.get('expected_route') not in roles:
            raise ValueError('invalid golden target/input/route')
    hashes = {p.name: digest(p) for p in sorted(task.iterdir()) if p.is_file()}
    spec = importlib.util.spec_from_file_location('assigned_support_app', task / 'support_app.py')
    assert spec is not None and spec.loader is not None
    app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app)
    run_id = uuid4().hex
    items: list[dict[str, Json]] = []
    for row in golden:
        start = time.perf_counter_ns()
        raw: Json = None
        exception = None
        try:
            raw = app.process(row['input'], policy)
        except Exception as exc:
            exception = f'{type(exc).__name__}: {exc}'
        elapsed = (time.perf_counter_ns() - start) / 1_000_000
        items.append(asdict(adapt(raw, row, roles, run_id, elapsed, exception)))
    metrics = aggregate(items, contract)
    artifact: dict[str, Json] = dict(run_id=run_id, policy=policy, input_sha256=hashes, contract=contract, scorer=contract['scorer'], items=items, metrics=metrics)
    evidence_path = out / f'{policy}-{run_id}.json'
    evidence = evidence_path.name + '#/metrics'
    checks: dict[str, Json] = {}
    same_inputs = all(digest(task / name) == sha for name, sha in hashes.items())
    for name, ok, obs, req in [
        ('validity', metrics['measurement_errors'] == 0, metrics['measurement_errors'], 0),
        ('protected_population_targets', len(items) == len(golden) and len({i['id'] for i in items}) == len(golden) and same_inputs, len(items), len(golden)),
        ('cost_completeness', metrics['unknown_cost_n'] == 0, metrics['unknown_cost_n'], 0),
    ]:
        checks[name] = check('pass' if ok else 'unavailable', obs, req, evidence)
    for name, metric, threshold, minimum in [
        ('owner_accuracy', 'accuracy_attempted', 'min_accuracy', True),
        ('owner_required_review', 'required_review_recall', 'min_required_review_recall', True),
        ('owner_errors', 'errors', 'max_errors', False),
        ('owner_cost_per_correct', 'cost_per_correct_usd', 'max_cost_per_correct_usd', False),
    ]:
        value, limit = metrics[metric], contract[threshold]
        ok = value is not None and (Decimal(str(value)) >= Decimal(str(limit)) if minimum else Decimal(str(value)) <= Decimal(str(limit)))
        checks[name] = check('unavailable' if value is None else 'pass' if ok else 'fail', value, limit, evidence)
    if policy == contract['reference_policy']:
        compatible = True
        baseline_metrics = metrics
        baseline_file = evidence_path.name
    elif reference is not None:
        ref = load(reference.read_text())
        compatible = ref['policy'] == contract['reference_policy'] and ref['input_sha256'] == hashes and ref['contract'] == contract and ref['metrics'] == aggregate(ref['items'], contract) and ref['metrics']['unknown_cost_n'] == 0 and ref['metrics']['measurement_errors'] == 0
        baseline_metrics = ref['metrics']
        baseline_file = reference.name
    else:
        compatible, baseline_metrics, baseline_file = False, metrics, None
    checks['compatibility'] = check('pass' if compatible else 'unavailable', compatible, True, evidence)
    comparisons = compare(metrics, baseline_metrics, contract['baseline_tolerances']) if compatible else {}
    artifact['baseline'] = {'reference': baseline_file, 'compatible': compatible, 'checks': comparisons}
    checks['baseline'] = check('unavailable' if not compatible or any(v['status'] == 'unavailable' for v in comparisons.values()) else 'fail' if any(v['status'] == 'fail' for v in comparisons.values()) else 'pass', comparisons, contract['baseline_tolerances'], evidence_path.name + '#/baseline')
    recommendation = 'invalid' if any(c['status'] == 'unavailable' for c in checks.values()) else 'reject' if any(c['status'] == 'fail' for c in checks.values()) else 'accept'
    candidate = dict(candidate_id=policy, recommendation=recommendation, checks=checks, observations=metrics, artifacts=[evidence_path.name], limitations=['Only recorded lookup latency is available; original service latency is unknown.', 'Synthetic API cost basis omits human time and deployment costs.'])
    artifact['candidate'] = candidate
    artifact['input_bytes_unchanged'] = same_inputs
    save(evidence_path, artifact)
    return candidate, evidence_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task-dir', required=True, type=Path)
    parser.add_argument('--out-dir', required=True, type=Path)
    parser.add_argument('--policy', required=True)
    parser.add_argument('--reference', type=Path)
    args = parser.parse_args()
    try:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        candidate, path = evaluate(args.task_dir, args.out_dir, args.policy, args.reference)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f'{type(exc).__name__}: {exc}', file=sys.stderr)
        return 2
    print(json.dumps({'candidate': candidate, 'artifact': path.name}, allow_nan=False))
    return {'accept': 0, 'reject': 1, 'invalid': 3}[candidate['recommendation']]


if __name__ == '__main__':
    raise SystemExit(main())
