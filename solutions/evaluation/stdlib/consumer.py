"""Offline saved-record evaluator. Python standard library only; no model execution."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import re
from typing import Any
from uuid import UUID

Json = Any
START = '2026-10-20T21:53:43.141624+00:00'
LIMITS = [
    'Saved declarations are not signatures; hashes cannot authenticate targets or model execution.',
    'Correctness is recorded scorer evidence, not independent human ground truth.',
    'Costs and callable latencies are synthetic saved measurements, not audited invoices or deployment latency.',
    'No network, provider, model, recorded command, release or production action was executed.',
]


def strict_load(path: Path) -> dict[str, Json]:
    """Reject duplicate keys and nonfinite JSON constants before interpretation."""
    def pairs(values: list[tuple[str, Json]]) -> dict[str, Json]:
        result: dict[str, Json] = {}
        for key, value in values:
            if key in result:
                raise ValueError(f'duplicate JSON key: {key}')
            result[key] = value
        return result
    def bad_constant(value: str) -> Json:
        raise ValueError(f'nonfinite JSON: {value}')
    result = json.loads(path.read_bytes(), object_pairs_hook=pairs, parse_constant=bad_constant)
    if not isinstance(result, dict):
        raise ValueError('top level must be an object')
    def reject_overflow(value: Json) -> None:
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError('nonfinite JSON numeric overflow')
        if isinstance(value, dict):
            for child in value.values():
                reject_overflow(child)
        elif isinstance(value, list):
            for child in value:
                reject_overflow(child)
    reject_overflow(result)
    return result


def finite(value: Json) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def equal_json(left: Json, right: Json) -> bool:
    return json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)


def close(left: Json, right: Json) -> bool:
    """Reconciliation permits float serialization noise; baseline gates do not."""
    if type(left) in (int, float) and type(right) in (int, float):
        return math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-14)
    return type(left) is type(right) and left == right


def compare_tree(recorded: Json, computed: Json, path: str = '') -> list[dict[str, Json]]:
    issues: list[dict[str, Json]] = []
    if isinstance(computed, dict):
        if not isinstance(recorded, dict):
            return [{'pointer': path, 'recorded': recorded, 'recomputed': computed}]
        for key, value in computed.items():
            child = f'{path}/{key.replace("~", "~0").replace("/", "~1")}'
            if key not in recorded:
                issues.append({'pointer': child, 'recorded': 'MISSING', 'recomputed': value})
            else:
                issues.extend(compare_tree(recorded[key], value, child))
    elif not close(recorded, computed):
        issues.append({'pointer': path, 'recorded': recorded, 'recomputed': computed})
    return issues


def p95(values: list[float]) -> float | None:
    return sorted(values)[math.ceil(len(values) * 0.95) - 1] if values else None


def metrics(run: dict[str, Json]) -> dict[str, Json]:
    items = run['items']
    policy = run['manifest']['route_policy']
    auto, escalation = policy['auto_routes'], policy['escalation_routes']
    n = len(items)
    correct = sum(item.get('correct') is True for item in items)
    errors = sum(item.get('error') is not None for item in items)
    unknown = sum(not finite(item.get('cost_usd')) for item in items)
    known = math.fsum(item.get('cost_usd') for item in items if finite(item.get('cost_usd')))
    total = None if unknown else known
    per_route: dict[str, Json] = {}
    for route in sorted({item.get('route') or '[unknown route]' for item in items}):
        group = [i for i in items if (i.get('route') or '[unknown route]') == route]
        missing = sum(not finite(i.get('cost_usd')) for i in group)
        subtotal = math.fsum(i.get('cost_usd') for i in group if finite(i.get('cost_usd')))
        per_route[route] = {
            'n': len(group), 'share': len(group) / n,
            'accuracy': sum(i.get('correct') is True for i in group) / len(group),
            'errors': sum(i.get('error') is not None for i in group),
            'known_cost_usd': subtotal, 'cost_usd': None if missing else subtotal,
            'mean_cost_usd': None if missing else subtotal / len(group),
            'unknown_cost_n': missing,
            'p95_latency_ms': p95([i.get('latency_ms') for i in group if finite(i.get('latency_ms'))]),
        }
    result: dict[str, Json] = {
        'attempted': n, 'succeeded': n - errors, 'errors': errors,
        'measurement_errors': sum(i.get('error_stage') in ('validation', 'scorer') for i in items),
        'accuracy_attempted': correct / n if n else None,
        'per_route': per_route,
        'economics': {
            'known_cost_usd': known, 'total_cost_usd': total,
            'cost_per_correct_usd': total / correct if total is not None and correct else None,
            'cost_complete': unknown == 0, 'unknown_cost_n': unknown,
            'deflection_rate': sum(i.get('route') in auto and i.get('error') is None for i in items) / n if auto and n else None,
            'auto_routes': auto,
        },
    }
    labelled = [i for i in items if i.get('expected_route') is not None]
    if labelled:
        grid = {f'route_{r}_verdict_{v}': 0 for r in ('right', 'wrong') for v in ('right', 'wrong')}
        for item in labelled:
            r = 'right' if item.get('route') == item.get('expected_route') else 'wrong'
            v = 'right' if item.get('correct') is True else 'wrong'
            grid[f'route_{r}_verdict_{v}'] += 1
        required = sum(i.get('expected_route') in escalation for i in labelled)
        observed = sum(i.get('route') in escalation for i in labelled)
        right = sum(i.get('route') in escalation and i.get('expected_route') in escalation for i in labelled)
        mismatch = grid['route_wrong_verdict_right'] / len(labelled)
        result['routing'] = {
            'n_labelled': len(labelled), 'label_coverage': len(labelled) / n,
            'routing_accuracy': sum(i.get('route') == i.get('expected_route') for i in labelled) / len(labelled),
            'grid': grid, 'correct_answer_wrong_route_rate': mismatch, 'lucky_hit_rate': mismatch,
            'escalation_routes': escalation,
            'escalation_precision': right / observed if escalation and observed else None,
            'escalation_recall': right / required if escalation and required else None,
            'n_required_escalations': required, 'n_observed_escalations': observed,
        }
    return result


def validate(run: dict[str, Json]) -> list[str]:
    issues: list[str] = []
    if run.get('schema_version') != '1':
        issues.append('schema_version must be 1')
    manifest = run.get('manifest', {})
    for field in ('run_id', 'harness_version', 'started_at', 'finished_at', 'status', 'git_sha',
                  'config_hash', 'golden_set', 'pricing_file', 'scorer', 'route_policy', 'cost_basis', 'note'):
        if field not in manifest:
            issues.append(f'missing manifest.{field}')
    try:
        uuid = UUID(hex=manifest['run_id'])
        if uuid.version != 4 or uuid.hex != manifest['run_id']:
            issues.append('run_id is not canonical UUID4 hex')
        start = datetime.fromisoformat(manifest['started_at'].replace('Z', '+00:00'))
        stop = datetime.fromisoformat(manifest['finished_at'].replace('Z', '+00:00'))
        if start.utcoffset().total_seconds() != 0 or stop.utcoffset().total_seconds() != 0 or stop < start:
            issues.append('manifest times not ordered UTC timestamps')
    except (ValueError, KeyError, TypeError, AttributeError):
        issues.append('malformed UUID or timestamps')
    for value in (manifest.get('config_hash'), manifest.get('golden_set', {}).get('sha256'),
                  manifest.get('pricing_file', {}).get('sha256')):
        if not isinstance(value, str) or not re.fullmatch('[0-9a-fA-F]{64}', value):
            issues.append('malformed manifest digest')
    policy = manifest.get('route_policy', {})
    for key in ('auto_routes', 'escalation_routes'):
        roles = policy.get(key)
        if not isinstance(roles, list) or any(not isinstance(r, str) or not r for r in roles) or roles != sorted(set(roles)):
            issues.append(f'malformed roles: {key}')
    if set(policy.get('auto_routes', [])) & set(policy.get('escalation_routes', [])):
        issues.append('roles overlap')
    if not manifest.get('cost_basis') or not manifest.get('scorer', {}).get('version'):
        issues.append('cost basis and versioned scorer required')
    items = run.get('items')
    if not isinstance(items, list) or not items:
        return issues + ['nonempty items list required']
    if manifest.get('golden_set', {}).get('n') != len(items):
        issues.append('golden_set.n differs from attempted population')
    required = ('id', 'input_hash', 'expected', 'expected_route', 'tier', 'answer', 'correct', 'route',
                'cost_usd', 'cost_source', 'model', 'tokens', 'latency_ms', 'stages', 'error', 'error_stage')
    for index, item in enumerate(items):
        prefix = f'items/{index}'
        for field in required:
            if field not in item:
                issues.append(f'{prefix}: missing {field}')
        if not isinstance(item.get('id'), str) or not item['id']:
            issues.append(f'{prefix}: invalid id')
        if not isinstance(item.get('input_hash'), str) or not re.fullmatch('[0-9a-fA-F]{64}', item['input_hash']):
            issues.append(f'{prefix}: malformed input_hash')
        if type(item.get('correct')) is not bool:
            issues.append(f'{prefix}: correctness not strict bool')
        for field in ('expected_route', 'tier', 'route', 'model', 'error'):
            value = item.get(field)
            if value is not None and (not isinstance(value, str) or not value):
                issues.append(f'{prefix}: invalid {field}')
        if item.get('error_stage') not in (None, 'pipeline', 'validation', 'scorer'):
            issues.append(f'{prefix}: invalid error_stage')
        if item.get('error') is not None and item.get('correct') is not False:
            issues.append(f'{prefix}: errored attempt marked correct')
        if (item.get('error') is None) != (item.get('error_stage') is None):
            issues.append(f'{prefix}: inconsistent error stage')
        cost = item.get('cost_usd')
        if cost is not None and not finite(cost):
            issues.append(f'{prefix}: invalid cost')
        if item.get('cost_source') not in ('reported', 'estimated', 'unknown'):
            issues.append(f'{prefix}: invalid cost_source')
        if (cost is None) != (item.get('cost_source') == 'unknown'):
            issues.append(f'{prefix}: cost completeness/source mismatch')
        if not finite(item.get('latency_ms')):
            issues.append(f'{prefix}: incomplete/invalid callable latency')
        tokens = item.get('tokens')
        if tokens is not None and (not isinstance(tokens, dict) or any(type(tokens.get(k)) is not int or tokens[k] < 0 for k in ('in', 'out'))):
            issues.append(f'{prefix}: invalid tokens')
        if item.get('error') is None and (not item.get('route') or tokens is None):
            issues.append(f'{prefix}: successful decision missing route/tokens')
        if item.get('stages') is not None and not isinstance(item['stages'], dict):
            issues.append(f'{prefix}: invalid stages')
    return issues


def deterioration(name: str, before: int | float, now: int | float) -> Decimal:
    """Exact arithmetic on recorded round-trip decimal numbers, no epsilon."""
    b, v = Decimal(str(before)), Decimal(str(now))
    if name == 'cost_per_correct_usd':
        return v - b if b == 0 else (v - b) / b
    if name in ('errors', 'correct_answer_wrong_route_rate'):
        return v - b
    return b - v


def evaluate(candidate: str, run: dict[str, Json], ref: dict[str, Json], contract: dict[str, Json],
             source_prefix: str = 'task') -> dict[str, Json]:
    checks: dict[str, Json] = {}
    artifact = f'{source_prefix}/{candidate}.json'
    evidence = f'evidence/{candidate}.json'
    invalid = False
    def add(name: str, passed: bool | None, observed: Json, required: Json, pointer: str, validity: bool = False) -> None:
        nonlocal invalid
        checks[name] = {'status': 'unavailable' if passed is None else ('pass' if passed else 'fail'),
                        'observed': observed, 'required': required, 'evidence': [f'{artifact}#{pointer}', f'{evidence}#/checks/{name}']}
        if name.startswith(('baseline_', 'identity_')) or name == 'protected_fields':
            checks[name]['evidence'].append(f'{source_prefix}/reference.json#/items' if name == 'protected_fields' else f'{source_prefix}/reference.json#/manifest' if name.startswith('identity_') else f'{source_prefix}/reference.json#/aggregates')
        owner_fields = {'owner_accuracy': 'min_accuracy', 'owner_critical_count': 'min_critical_attempted',
                        'owner_critical_accuracy': 'min_critical_accuracy', 'owner_cost_per_correct': 'max_cost_per_correct_usd',
                        'owner_callable_p95': 'max_callable_p95_ms', 'owner_errors': 'max_errors'}
        if name in owner_fields:
            checks[name]['evidence'].append(f'{source_prefix}/contract.json#/{owner_fields[name]}')
        if name.startswith('baseline_'):
            checks[name]['evidence'].append(f'{source_prefix}/contract.json#/baseline_tolerances')
        if validity and passed is not True:
            invalid = True
    problems = validate(run)
    add('schema_and_item_validity', not problems, problems, 'complete valid schema-1 measurement', '', True)
    add('complete_measurement', run['manifest']['status'] == 'complete', run['manifest']['status'], 'complete', '/manifest/status', True)
    items = run['items']
    ids = [i['id'] for i in items]
    ref_ids = [i['id'] for i in ref['items']]
    population = {'attempted': len(ids), 'unique': len(set(ids)), 'missing': sorted(set(ref_ids) - set(ids)),
                  'extra': sorted(set(ids) - set(ref_ids)), 'duplicates': [i for i, n in Counter(ids).items() if n > 1]}
    add('complete_unique_population', len(ids) == len(ref_ids) and set(ids) == set(ref_ids) and len(set(ids)) == len(ids), population,
        {'attempted': len(ref_ids), 'unique': len(ref_ids), 'missing': [], 'extra': [], 'duplicates': []}, '/items', True)
    ref_map = {i['id']: i for i in ref['items']}
    changes = [{'id': i['id'], 'field': k, 'observed': i.get(k), 'reference': ref_map[i['id']].get(k)}
               for i in items if i['id'] in ref_map for k in ('input_hash', 'expected', 'expected_route', 'tier')
               if not equal_json(i.get(k), ref_map[i['id']].get(k))]
    add('protected_fields', not changes, changes, 'per-ID input_hash, expected, expected_route, tier unchanged', '/items', True)
    identity_fields = ('golden_set', 'pricing_file', 'scorer', 'route_policy', 'cost_basis')
    incompatible: list[str] = []
    for field in identity_fields:
        left, right = run['manifest'][field], ref['manifest'][field]
        if field in ('golden_set', 'pricing_file'):
            left, right = left['sha256'], right['sha256']
        same = equal_json(left, right)
        add(f'identity_{field}', same, left, right, f'/manifest/{field}', True)
        if not same:
            incompatible.append(field)
    computed = metrics(run)
    reconciled = compare_tree(run['aggregates'], computed, '/aggregates')
    add('aggregate_consistency', not reconciled, reconciled, 'all required recomputed aggregates consistent; float reconciliation rel=1e-12 abs=1e-14', '/aggregates', True)
    add('no_measurement_errors', computed['measurement_errors'] == 0, computed['measurement_errors'], 0, '/items', True)
    unknown_cost = [i['id'] for i in items if not finite(i.get('cost_usd'))]
    missing_latency = [i['id'] for i in items if not finite(i.get('latency_ms'))]
    add('complete_whole_decision_cost', not unknown_cost, {'unknown_n': len(unknown_cost), 'ids': unknown_cost}, {'unknown_n': 0, 'basis': ref['manifest']['cost_basis']}, '/items', True)
    add('complete_callable_latency', not missing_latency, {'unknown_n': len(missing_latency), 'ids': missing_latency}, {'unknown_n': 0}, '/items', True)
    population_ok = checks['complete_unique_population']['status'] == 'pass'
    cohort_ok = population_ok and not any(c['field'] == 'tier' for c in changes)
    target_ok = not changes and 'scorer' not in incompatible and population_ok
    correct = sum(i.get('correct') is True for i in items)
    critical_ids = {i['id'] for i in ref['items'] if i['tier'] == contract['critical_tier']}
    critical = [i for i in items if i['id'] in critical_ids]
    critical_correct = sum(i.get('correct') is True for i in critical)
    accuracy = correct / len(items) if target_ok else None
    critical_accuracy = critical_correct / len(critical) if target_ok and critical else None
    cost_per = computed['economics']['cost_per_correct_usd'] if target_ok else None
    latency = p95([i.get('latency_ms') for i in items]) if not missing_latency else None
    add('owner_accuracy', None if accuracy is None else Decimal(correct) / Decimal(len(items)) >= Decimal(str(contract['min_accuracy'])),
        {'accuracy': accuracy, 'correct': correct if target_ok else None, 'attempted': len(items)}, {'min_accuracy': contract['min_accuracy']}, '/items')
    add('owner_critical_count', len(critical) >= contract['min_critical_attempted'] if cohort_ok else None,
        {'attempted': len(critical) if cohort_ok else None, 'trusted_ids': sorted(critical_ids)}, {'min_attempted': contract['min_critical_attempted']}, '/items')
    add('owner_critical_accuracy', None if critical_accuracy is None else Decimal(critical_correct) / Decimal(len(critical)) >= Decimal(str(contract['min_critical_accuracy'])),
        {'accuracy': critical_accuracy, 'correct': critical_correct if target_ok else None, 'attempted': len(critical) if target_ok else None}, {'min_accuracy': contract['min_critical_accuracy']}, '/items')
    add('owner_cost_per_correct', None if cost_per is None else Decimal(str(cost_per)) <= Decimal(str(contract['max_cost_per_correct_usd'])), cost_per,
        {'max_cost_per_correct_usd': contract['max_cost_per_correct_usd']}, '/items')
    add('owner_callable_p95', None if latency is None else Decimal(str(latency)) <= Decimal(str(contract['max_callable_p95_ms'])),
        {'p95_ms': latency, 'n': len(items), 'rank': math.ceil(0.95 * len(items)), 'method': 'nearest-rank; all attempted callable latencies'},
        {'max_ms': contract['max_callable_p95_ms']}, '/items')
    add('owner_errors', computed['errors'] <= contract['max_errors'], computed['errors'], {'max_errors': contract['max_errors']}, '/items')
    watched = {'accuracy_attempted': ('accuracy_attempted',), 'routing_accuracy': ('routing', 'routing_accuracy'),
               'correct_answer_wrong_route_rate': ('routing', 'correct_answer_wrong_route_rate'),
               'escalation_recall': ('routing', 'escalation_recall'), 'errors': ('errors',),
               'cost_per_correct_usd': ('economics', 'cost_per_correct_usd')}
    def get(data: dict[str, Json], keys: tuple[str, ...]) -> Json:
        for key in keys:
            data = data.get(key) if isinstance(data, dict) else None
        return data
    for name, keys in watched.items():
        before, now = get(ref['aggregates'], keys), get(run['aggregates'], keys)
        tolerance = contract['baseline_tolerances'][name]
        observed: dict[str, Json] = {'before': before, 'now': now, 'deterioration_decimal': None}
        passed: bool | None = None
        if before is None and now is None:
            observed['skip_reason'] = 'metric null on both sides; no declared escalation roles/required cohort'
            passed = True
        elif before is None or now is None:
            observed['unavailable_reason'] = 'watched metric available on only one side'
            invalid = True
        elif incompatible or changes or reconciled or problems:
            observed['unavailable_reason'] = 'comparison evidence incompatible or invalid'
        else:
            delta = deterioration(name, before, now)
            if name == 'cost_per_correct_usd' and before == 0:
                tolerance = contract['baseline_tolerances']['cost_zero_absolute_usd']
            observed['deterioration_decimal'] = str(delta)
            passed = delta <= Decimal(str(tolerance))
        add(f'baseline_{name}', passed, observed, {'max_deterioration': tolerance, 'strict_greater_fails': True}, '/aggregates')
    recommendation = 'invalid' if invalid else ('reject' if any(v['status'] != 'pass' for v in checks.values()) else 'accept')
    observations = {'attempted': len(items), 'correct': correct if target_ok else None, 'errors': computed['errors'],
                    'unknown_cost_n': len(unknown_cost), 'known_cost_usd': computed['economics']['known_cost_usd'],
                    'total_cost_usd': computed['economics']['total_cost_usd'], 'cost_per_correct_usd': cost_per,
                    'critical_attempted': len(critical) if cohort_ok else None,
                    'critical_correct': critical_correct if target_ok else None, 'critical_accuracy': critical_accuracy,
                    'callable_p95_ms': latency}
    limitations = LIMITS + (['Target-dependent metrics unavailable because protected population/targets or identities are incompatible.'] if not target_ok else [])
    return {'candidate_id': candidate, 'recommendation': recommendation, 'checks': checks, 'observations': observations,
            'artifacts': [artifact, evidence], 'limitations': limitations,
            'recomputed_aggregates': computed, 'critical_item_evidence': [{'id': i['id'], 'correct': i['correct'], 'error': i.get('error')} for i in critical]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--task-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    root, out = args.task_dir, args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    (out / 'evidence').mkdir(exist_ok=True)
    contract = strict_load(root / 'contract.json')
    ref = strict_load(root / contract['reference'])
    ref_issues = validate(ref) + [str(i) for i in compare_tree(ref['aggregates'], metrics(ref))]
    if ref_issues:
        raise ValueError(f'invalid trusted reference: {ref_issues}')
    files = ['contract.json', contract['reference']] + [f'{c}.json' for c in contract['candidates']]
    source_prefix = os.path.relpath(root, out)
    before = {f'{source_prefix}/{name}': digest(root / name) for name in files}
    candidates = []
    for candidate in contract['candidates']:
        value = evaluate(candidate, strict_load(root / f'{candidate}.json'), ref, contract, source_prefix)
        (out / 'evidence' / f'{candidate}.json').write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')
        candidates.append(value)
        print(candidate, value['recommendation'], json.dumps(value['observations']))
    after = {f'{source_prefix}/{name}': digest(root / name) for name in files}
    if before != after:
        raise ValueError('input bytes changed during evaluation')
    submission = {'record_version': 'trial-decisions-1', 'track': 'evaluation', 'condition': 'stdlib',
                  'contract_sha256': before[f'{source_prefix}/contract.json'], 'reference_id': ref['manifest']['run_id'],
                  'input_sha256': before, 'input_path_base': 'all input paths are relative to this participant directory',
                  'release_executed': False, 'candidates': candidates, 'input_preservation_verified': before == after,
                  'reference_validation': {'status': 'pass', 'issues': ref_issues},
                  'evaluation_finished_at_utc': datetime.now(timezone.utc).isoformat()}
    (out / 'submission.json').write_text(json.dumps(submission, indent=2, allow_nan=False) + '\n')


if __name__ == '__main__':
    main()
