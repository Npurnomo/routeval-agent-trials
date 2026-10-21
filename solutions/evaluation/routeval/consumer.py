"""Evaluate fixed saved runs as data; no recorded callable is imported or executed."""
from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import subprocess
from typing import Any

from routeval import exact
from run_command import run

# APPLICATION MAPPING: strict artifact parsing and measurement reconstruction.
def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_constant(value: str) -> Any:
    raise ValueError(f"Nonfinite JSON value: {value}")


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(), object_pairs_hook=no_duplicates,
                       parse_constant=reject_constant)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def numeric(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def dec(value: int | float) -> Decimal:
    return Decimal(str(value))


def ratio(numerator: int | float, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def p95(items: list[dict[str, Any]]) -> float | None:
    values = [i.get('latency_ms') for i in items]
    if not values or not all(numeric(v) for v in values):
        return None
    return sorted(values)[math.ceil(len(values) * 0.95) - 1]


def cost_stats(items: list[dict[str, Any]]) -> dict[str, Any]:
    known = [i['cost_usd'] for i in items if numeric(i.get('cost_usd'))]
    subtotal = math.fsum(known)
    missing = len(items) - len(known)
    return {'known_cost_usd': subtotal, 'cost_usd': None if missing else subtotal,
            'mean_cost_usd': None if missing else ratio(subtotal, len(items)),
            'unknown_cost_n': missing}


def reconstruct(record: dict[str, Any]) -> dict[str, Any]:
    items = record['items']
    n = len(items)
    correct = sum(i.get('correct') is True for i in items)
    errors = sum(i.get('error') is not None for i in items)
    roles = record['manifest']['route_policy']
    auto, escalation = roles['auto_routes'], roles['escalation_routes']
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        groups.setdefault(item.get('route') or '[unknown route]', []).append(item)
    routes: dict[str, Any] = {}
    for route, group in groups.items():
        routes[route] = {'n': len(group), 'share': ratio(len(group), n),
                         'accuracy': ratio(sum(i.get('correct') is True for i in group), len(group)),
                         'errors': sum(i.get('error') is not None for i in group),
                         **cost_stats(group), 'p95_latency_ms': p95(group)}
    costs = cost_stats(items)
    total = costs['cost_usd']
    result: dict[str, Any] = {
        'attempted': n, 'succeeded': n-errors, 'errors': errors,
        'measurement_errors': sum(i.get('error_stage') in ('validation', 'scorer') for i in items),
        'accuracy_attempted': ratio(correct, n), 'per_route': routes,
        'economics': {'known_cost_usd': costs['known_cost_usd'], 'total_cost_usd': total,
                      'cost_per_correct_usd': None if total is None else ratio(total, correct),
                      'cost_complete': costs['unknown_cost_n'] == 0,
                      'unknown_cost_n': costs['unknown_cost_n'],
                      'deflection_rate': ratio(sum(i.get('error') is None and i.get('route') in auto for i in items), n) if auto else None,
                      'auto_routes': auto}}
    labelled = [i for i in items if i.get('expected_route') is not None]
    if labelled:
        grid = {f'route_{r}_verdict_{v}': 0 for r in ('right', 'wrong') for v in ('right', 'wrong')}
        for item in labelled:
            r = 'right' if item.get('route') == item['expected_route'] else 'wrong'
            v = 'right' if item.get('correct') is True else 'wrong'
            grid[f'route_{r}_verdict_{v}'] += 1
        required = sum(i['expected_route'] in escalation for i in labelled)
        observed = sum(i.get('route') in escalation for i in labelled)
        matched = sum(i['expected_route'] in escalation and i.get('route') in escalation for i in labelled)
        mismatch = ratio(grid['route_wrong_verdict_right'], len(labelled))
        result['routing'] = {
            'n_labelled': len(labelled), 'label_coverage': ratio(len(labelled), n),
            'routing_accuracy': ratio(sum(i.get('route') == i['expected_route'] for i in labelled), len(labelled)),
            'grid': grid, 'correct_answer_wrong_route_rate': mismatch, 'lucky_hit_rate': mismatch,
            'escalation_routes': escalation,
            'escalation_precision': ratio(matched, observed) if escalation else None,
            'escalation_recall': ratio(matched, required) if escalation else None,
            'n_required_escalations': required, 'n_observed_escalations': observed}
    stages: dict[str, list[bool]] = {}
    for item in items:
        for name, stage in (item.get('stages') or {}).items():
            if isinstance(stage, dict) and type(stage.get('correct')) is bool:
                stages.setdefault(name, []).append(stage['correct'])
    if stages:
        result['stages'] = {name: {'n': len(values), 'accuracy': sum(values)/len(values)} for name, values in stages.items()}
    return result


def differences(actual: Any, expected: Any, pointer: str = '') -> list[dict[str, Any]]:
    if isinstance(expected, dict) and isinstance(actual, dict):
        result: list[dict[str, Any]] = []
        for key in sorted(set(actual) | set(expected)):
            if key not in actual or key not in expected:
                result.append({'pointer': pointer+'/'+key, 'recorded': actual.get(key), 'recomputed': expected.get(key), 'missing_key': True})
            else:
                result.extend(differences(actual[key], expected[key], pointer+'/'+key))
        return result
    if type(expected) in (int, float) and type(actual) in (int, float):
        # Aggregate consistency tolerates only binary summation noise, never owner gates.
        equal = math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-15)
    else:
        equal = type(actual) is type(expected) and actual == expected
    return [] if equal else [{'pointer': pointer, 'recorded': actual, 'recomputed': expected}]

# OWNER POLICY: validity, absolute requirements and fixed baseline arithmetic.
def check(status: str, observed: Any, required: Any, evidence: list[str]) -> dict[str, Any]:
    return {'status': status, 'observed': observed, 'required': required, 'evidence': evidence}


def evaluate(candidate_id: str, record: dict[str, Any], reference: dict[str, Any],
             contract: dict[str, Any], native_exit: int) -> tuple[dict[str, Any], dict[str, Any]]:
    source = f'{candidate_id}.json'
    evidence_path = f'evidence/{candidate_id}.json'
    checks: dict[str, Any] = {}
    invalid: list[str] = []
    def add(name: str, ok: bool | None, observed: Any, required: Any,
            pointers: list[str], validity: bool = False) -> None:
        checks[name] = check('unavailable' if ok is None else 'pass' if ok else 'fail', observed, required, pointers)
        if validity and ok is not True:
            invalid.append(name)
    items, originals = record['items'], reference['items']
    m, rm = record['manifest'], reference['manifest']
    counts = Counter(i.get('id') for i in items)
    ref_by_id = {i['id']: i for i in originals}
    missing = sorted(set(ref_by_id)-set(counts))
    extra = sorted(set(counts)-set(ref_by_id))
    duplicate = {str(k):v for k,v in counts.items() if v != 1}
    population_ok = not missing and not extra and not duplicate and len(items) == len(originals)
    add('complete_unique_population', population_ok,
        {'attempted': len(items), 'missing': missing, 'extra': extra, 'duplicates': duplicate},
        {'attempted': len(originals), 'each_reference_id_once': True}, [source+'#/items', 'reference.json#/items'], True)
    protected: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        original = ref_by_id.get(item.get('id'))
        if original is not None:
            for field in ('input_hash','expected','expected_route','tier'):
                if type(item.get(field)) is not type(original.get(field)) or item.get(field) != original.get(field):
                    protected.append({'id': item['id'], 'field': field, 'observed': item.get(field), 'required': original.get(field), 'pointer': source+f'#/items/{index}/{field}'})
    add('protected_fields', not protected, protected, 'byte hashes and targets/routes/tiers equal trusted reference per ID', [source+'#/items','reference.json#/items'], True)
    add('schema_and_complete_measurement', record.get('schema_version') == '1' and m.get('status') == 'complete' and not any(i.get('error_stage') in ('scorer','validation') for i in items),
        {'schema': record.get('schema_version'), 'status': m.get('status'), 'measurement_errors': sum(i.get('error_stage') in ('scorer','validation') for i in items)},
        {'schema': '1','status':'complete','measurement_errors':0}, [source+'#/schema_version',source+'#/manifest/status',source+'#/items'], True)
    identities = {
        'dataset': (m['golden_set']['sha256'], rm['golden_set']['sha256']),
        'dataset_n': (m['golden_set']['n'], len(originals)),
        'pricing': (m['pricing_file']['sha256'],rm['pricing_file']['sha256']),
        'scorer': (m['scorer'],rm['scorer']), 'route_roles': (m['route_policy'],rm['route_policy']),
        'cost_basis': (m['cost_basis'],rm['cost_basis'])}
    for name,(observed,required) in identities.items():
        add('compatible_'+name, observed == required, observed, required, [source+'#/manifest','reference.json#/manifest'], True)
    recomputed = reconstruct(record)
    aggregate_diff = differences(record['aggregates'], recomputed)
    add('aggregate_consistency', not aggregate_diff, aggregate_diff, 'all recorded aggregates agree with item reconstruction (binary summation noise only)', [source+'#/aggregates',evidence_path+'#/recomputed_aggregates'], True)
    scoring_ok = m['scorer'] == rm['scorer'] and rm['scorer'] == {'id':'routeval.scorers.exact','version':'0.1.0'}
    score_diffs = []
    if scoring_ok:
        for index,item in enumerate(items):
            expected_correct = item.get('error') is None and exact(item['expected'],item['answer'])
            if type(item.get('correct')) is not bool or item['correct'] != expected_correct:
                score_diffs.append({'id': item['id'], 'pointer': source+f'#/items/{index}/correct','recomputed':expected_correct})
    add('correctness_consistency', not score_diffs if scoring_ok else None, score_diffs if scoring_ok else None,
        'public exact scorer under matching declared rule version, with errors false', [source+'#/items'], True)
    costs = cost_stats(items)
    bad_latency = [i['id'] for i in items if not numeric(i.get('latency_ms'))]
    add('complete_whole_decision_cost', costs['unknown_cost_n'] == 0,
        {'unknown_cost_n':costs['unknown_cost_n'],'known_cost_usd':costs['known_cost_usd'], 'cost_basis':m['cost_basis']},
        {'unknown_cost_n':0,'meaning':'whole-decision USD under fixed declared cost basis'}, [source+'#/items',source+'#/manifest/cost_basis'], True)
    add('complete_callable_latency', not bad_latency, {'missing_or_invalid_ids':bad_latency,'measured_n':len(items)-len(bad_latency)},
        {'measured_n':len(originals),'finite_nonnegative':True}, [source+'#/items'], True)
    target_ok = population_ok and not protected and scoring_ok and not score_diffs
    correct = sum(i['correct'] is True for i in items) if target_ok else None
    critical = [i for i in items if i.get('tier') == contract['critical_tier']]
    critical_correct = sum(i['correct'] is True for i in critical) if target_ok else None
    accuracy = ratio(correct,len(items)) if correct is not None else None
    critical_accuracy = ratio(critical_correct,len(critical)) if critical_correct is not None else None
    cpc = ratio(costs['cost_usd'],correct) if costs['cost_usd'] is not None and correct is not None else None
    latency = p95(items)
    errors = sum(i.get('error') is not None for i in items)
    metrics = {
        'overall_accuracy': (accuracy, contract['min_accuracy'], 'min'),
        'critical_count': (len(critical) if population_ok and not protected else None,contract['min_critical_attempted'],'min'),
        'critical_accuracy': (critical_accuracy,contract['min_critical_accuracy'],'min'),
        'cost_per_correct_usd': (cpc,contract['max_cost_per_correct_usd'],'max'),
        'callable_p95_ms': (latency,contract['max_callable_p95_ms'],'max'),
        'error_count': (errors,contract['max_errors'],'max')}
    for name,(value,limit,direction) in metrics.items():
        ok = None if value is None else dec(value) >= dec(limit) if direction == 'min' else dec(value) <= dec(limit)
        add('owner_'+name,ok,value,{direction:limit},[source+'#/items',evidence_path+'#/owner_metrics'])
    baseline: dict[str, Any] = {}
    base_aggs = reference['aggregates']
    paths = {'accuracy_attempted': ('accuracy_attempted',), 'errors':('errors',),
             'routing_accuracy':('routing','routing_accuracy'),
             'correct_answer_wrong_route_rate':('routing','correct_answer_wrong_route_rate'),
             'escalation_recall':('routing','escalation_recall'),
             'cost_per_correct_usd':('economics','cost_per_correct_usd')}
    for name,path in paths.items():
        before,now = base_aggs,record['aggregates']
        for part in path:
            before,now = before.get(part),now.get(part)
        tolerance = contract['baseline_tolerances'][name]
        if before is None and now is None:
            baseline[name] = {'status':'unavailable','before':None,'now':None,'skipped':True,'tolerance':tolerance}
            continue
        if before is None or now is None:
            ok, deterioration = None,None
        elif name == 'cost_per_correct_usd':
            deterioration = dec(now)-dec(before) if before == 0 else dec(now)/dec(before)-1
            tolerance = contract['baseline_tolerances']['cost_zero_absolute_usd'] if before == 0 else tolerance
            ok = deterioration <= dec(tolerance)
        else:
            deterioration = dec(now)-dec(before) if name in ('errors','correct_answer_wrong_route_rate') else dec(before)-dec(now)
            ok = deterioration <= dec(tolerance)
        usable = target_ok and costs['unknown_cost_n'] == 0 and all(v[0] == v[1] for v in identities.values())
        baseline[name] = {'status': 'unavailable' if not usable or ok is None else 'pass' if ok else 'fail',
                          'before':before,'now':now,'deterioration':str(deterioration) if deterioration is not None else None,'tolerance':tolerance,'skipped':False}
    for name,result in baseline.items():
        checks['baseline_'+name] = check(result['status'],result, {'max_deterioration':result['tolerance']},[evidence_path+'#/baseline/'+name,'reference.json#/aggregates',source+'#/aggregates'])
    add('native_baseline_comparison', native_exit == 0 if native_exit in (0,1) else None,
        {'exit':native_exit}, {'exit':0,'scope':'native watched baseline metrics only'}, [f'native/{candidate_id}.json'])
    if native_exit not in (0,1):
        invalid.append('native_baseline_comparison')
    failed = [name for name,value in checks.items() if value['status'] == 'fail']
    recommendation = 'invalid' if invalid else 'reject' if failed else 'accept'
    limitations = ['Saved synthetic evidence does not authenticate actual execution, original billing/latency, or trusted-label correctness.',
                   'Whole-decision coverage is declared; no independent charge ledger is supplied.']
    if not target_ok:
        limitations.append('Target-dependent owner metrics unavailable because scoring, protected targets, or population are incompatible; reported aggregates remain diagnostic only.')
    observations = {'attempted':len(items),'correct':correct,'errors':errors,
                    'unknown_cost_n':costs['unknown_cost_n'],'known_cost_usd':costs['known_cost_usd'],
                    'total_cost_usd':costs['cost_usd'],'cost_per_correct_usd':cpc,
                    'critical_attempted':len(critical) if population_ok and not protected else None,
                    'critical_correct':critical_correct,'critical_accuracy':critical_accuracy,
                    'callable_p95_ms':latency,'reported_correct':sum(i['correct'] is True for i in items)}
    evidence = {'recomputed_aggregates':recomputed,'aggregate_differences':aggregate_diff,
                'protected_changes':protected,'invalid_reasons':invalid,'failed_checks':failed,
                'owner_metrics':observations,'baseline':baseline,'native_exit':native_exit}
    return {'candidate_id':candidate_id,'recommendation':recommendation,'checks':checks,
            'observations':observations,'artifacts':[evidence_path,f'native/{candidate_id}.json'],
            'limitations':limitations},evidence

# EVIDENCE PROCESS: CLI receipt capture, exact hashes and neutral submission.
def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task-dir', type=Path, required=True)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--routeval', type=Path, required=True)
    args = parser.parse_args()
    task, out = args.task_dir.resolve(), args.out_dir.resolve()
    contract = load(task/'contract.json')
    reference = load(task/contract['reference'])
    inputs = ['TASK.md','contract.json',contract['reference']]+[f'{c}.json' for c in contract['candidates']]
    hashes = {name:digest(task/name) for name in inputs}
    write(out/'input-hashes-before.json', hashes)
    write(out/'tolerances.json', contract['baseline_tolerances'])
    results = []
    for candidate_id in contract['candidates']:
        record = load(task/f'{candidate_id}.json')
        result = run([str(args.routeval),'compare',str(task/f'{candidate_id}.json'),
                      str(task/contract['reference']),'--tolerances',str(out/'tolerances.json')],out)
        write(out/f'native/{candidate_id}.json', {'argv':result.args,'exit':result.returncode,
                                                 'stdout':result.stdout,'stderr':result.stderr})
        candidate,evidence = evaluate(candidate_id,record,reference,contract,result.returncode)
        write(out/f'evidence/{candidate_id}.json', evidence)
        results.append(candidate)
        print(candidate_id,candidate['recommendation'], 'native_exit',result.returncode,
              'failed',','.join(evidence['failed_checks']),'invalid',','.join(evidence['invalid_reasons']))
    after = {name:digest(task/name) for name in inputs}
    write(out/'input-hashes-after.json', after)
    if hashes != after:
        raise RuntimeError('Input changed during evaluation')
    submission = {'record_version':'trial-decisions-1','track':'evaluation','condition':'routeval',
                  'contract_sha256':hashes['contract.json'],'reference_id':reference['manifest']['run_id'],
                  'input_sha256':hashes,'release_executed':False,'candidates':results,
                  'inputs_unchanged':True,'evidence_pointer_base':'input filenames resolve beneath supplied evaluation task directory; evidence/native paths resolve beneath this session'}
    write(out/'submission.json', submission)


if __name__ == '__main__':
    main()
