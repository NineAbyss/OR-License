from __future__ import annotations

_CLI_DESCRIPTION = """Add a final exact-pattern polishing pass to an existing batching solution.

Uses only the input instance and incumbent solution: no target score, material
IDs, reference-to-agent mapping or precomputed batches are embedded.
Requires NumPy and SciPy. Intended for small (2--4 piece) batching instances.
The ordered-leftover strategy requires total weight < 1000 (checked below).
Timeout / enumeration cap / an unresolved cheaper candidate returns the valid
incumbent rather than silently skipping an unknown candidate or claiming proof.
"""

import argparse
import copy
import json
import math
import time
from collections import Counter
from decimal import Decimal
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, linprog, milp
from scipy.sparse import csc_matrix


def _integer_values(values: list[Any]) -> tuple[list[int], int]:
    numbers = [Decimal(str(v)) for v in values]
    if not all(v.is_finite() for v in numbers):
        raise ValueError('Input numbers must be finite.')
    scale = 10 ** max(0, max(-v.as_tuple().exponent for v in numbers))
    return [int(v * scale) for v in numbers], scale


def _prepare(case: dict[str, Any]):
    ms, req = case['materials'], case['requirements']
    ids = [m['id'] for m in ms]
    if not ids or len(set(ids)) != len(ids) or not all(isinstance(i, str) for i in ids):
        raise ValueError('Materials must have unique string IDs.')
    n = len(ids)
    wv, scale = _integer_values([m['weight'] for m in ms] + req['weight'])
    w, (wlo, whi) = wv[:n], wv[n:]
    if any(v <= 0 for v in w) or not 0 < wlo <= whi:
        raise ValueError('Weights must be positive and bounds ordered.')
    vectors = []
    for key in ('fe', 'c'):
        v, _ = _integer_values([m[key] for m in ms] + req[key])
        lo, hi = v[n:]
        if lo > hi:
            raise ValueError(f'Invalid {key} bounds.')
        vectors += [[w[i]*(v[i]-lo) for i in range(n)],
                    [w[i]*(hi-v[i]) for i in range(n)]]
    plo, phi = req['pieces']
    if type(plo) is not int or type(phi) is not int or not 1 <= plo <= phi <= 4:
        raise ValueError('This polishing module supports batch sizes 1--4.')
    tmax = req['type1_max']
    if type(tmax) is not int or tmax < 0:
        raise ValueError('type1_max must be a nonnegative integer.')
    t1 = [int(m['type'] == 1) for m in ms]
    return ids, w, scale, vectors, t1, (plo, phi, wlo, whi, tmax)


def _legal(group, w, vectors, t1, limits):
    plo, phi, wlo, whi, tmax = limits
    return (plo <= len(group) <= phi and wlo <= sum(w[i] for i in group) <= whi
            and sum(t1[i] for i in group) <= tmax
            and all(sum(a[i] for i in group) >= 0 for a in vectors))


def _validate(solution, ids, w, vectors, t1, limits):
    ix = {mid: i for i, mid in enumerate(ids)}
    groups = []
    for g in solution['groups']:
        if type(g['group_id']) is not int:
            raise ValueError('Each group_id must be an integer.')
        group = tuple(sorted(ix[s] for s in g['material_ids']))
        if not _legal(group, w, vectors, t1, limits):
            raise ValueError(f'Illegal batch: {g["material_ids"]}')
        groups.append(group)
    left = tuple(sorted(ix[s] for s in solution['unassigned_ids']))
    if Counter(i for g in groups for i in g) + Counter(left) != Counter(range(len(ids))):
        raise ValueError('Solution must cover every material exactly once.')
    return groups, left


def _enumerate_patterns(w, vectors, t1, limits, deadline, max_patterns):
    plo, phi, wlo, whi, tmax = limits
    order = sorted(range(len(w)), key=lambda i: (w[i], i))
    patterns = []
    nodes = 0
    def visit(start, group, weight, types):
        nonlocal nodes
        nodes += 1
        if nodes % 1024 == 0 and time.monotonic() >= deadline:
            raise TimeoutError('Pattern enumeration time limit.')
        if len(group) >= plo and weight >= wlo and all(sum(a[i] for i in group) >= 0 for a in vectors):
            patterns.append(tuple(sorted(group)))
            if len(patterns) > max_patterns:
                raise TimeoutError('Pattern count cap reached.')
        if len(group) == phi:
            return
        for j in range(start, len(order)):
            i = order[j]
            if weight + w[i] > whi:
                break
            if types + t1[i] <= tmax:
                visit(j+1, group+(i,), weight+w[i], types+t1[i])
    visit(0, (), 0, 0)
    return sorted(patterns)


def polish(case: dict[str, Any], incumbent: dict[str, Any], *,
           time_limit: float = 60.0, max_combinations: int = 2_000_000,
           max_patterns: int = 1_000_000) -> tuple[dict[str, Any], dict[str, Any]]:
    if not math.isfinite(time_limit) or time_limit <= 0:
        raise ValueError('time_limit must be finite and positive.')
    if max_combinations < 1 or max_patterns < 1:
        raise ValueError('Enumeration caps must be positive.')
    start = time.monotonic(); deadline = start + time_limit
    ids, w, scale, vectors, t1, limits = _prepare(case)
    if sum(w) >= 1000*scale:
        raise ValueError('Ordered-leftover mode requires total weight < 1000.')
    ref_groups, ref_left = _validate(incumbent, ids, w, vectors, t1, limits)
    ref_set = set(ref_groups)
    score_int = lambda left: 1000*scale*len(left)+sum(w[i] for i in left)
    original_score = score_int(ref_left)
    best = copy.deepcopy(incumbent)
    report = {'score_before': original_score/scale, 'score_after': original_score/scale,
              'primary_optimal_by_solver': False, 'retention_optimal_for_leftover_set': False,
              'candidate_tests': []}
    def finish(reason):
        report.update(reason=reason, elapsed_seconds=time.monotonic()-start)
        report['unchanged_original_groups'] = sum(
            frozenset(g['material_ids']) in {frozenset(ids[i] for i in c) for c in ref_groups}
            for g in best['groups'])
        return best, report
    try:
        patterns = _enumerate_patterns(w, vectors, t1, limits, deadline, max_patterns)
        report['patterns'] = len(patterns)
        coverable = {i for c in patterns for i in c}
        forced = tuple(i for i in range(len(ids)) if i not in coverable)
        optional = [i for i in range(len(ids)) if i in coverable]
        report['forced_unassigned_ids'] = [ids[i] for i in forced]
        totals = [sum(a) for a in vectors]
        forced_totals = [sum(a[i] for i in forced) for a in vectors]
        sorted_optional = [sorted(a[i] for i in optional) for a in vectors]
        lower = next(k for k in range(len(optional)+1)
                     if all(totals[j]-forced_totals[j]-sum(sorted_optional[j][:k]) >= 0
                            for j in range(len(vectors)))) + len(forced)
        report['leftover_count_lower_bound'] = lower
        enumerated = 0
        for count in range(lower, len(ref_left)+1):
            extra = count-len(forced)
            ncomb = math.comb(len(optional), extra)
            if enumerated + ncomb > max_combinations:
                return finish('Combination cap: incumbent retained, no optimality claim.')
            candidates = []
            for q, rest in enumerate(combinations(optional, extra)):
                if q % 1024 == 0 and time.monotonic() >= deadline:
                    raise TimeoutError('Leftover enumeration time limit.')
                left = tuple(sorted(forced+rest))
                score = score_int(left)
                if score >= original_score:
                    continue
                if all(totals[j]-sum(a[i] for i in left) >= 0 for j, a in enumerate(vectors)):
                    candidates.append((score, left))
            enumerated += ncomb
            candidates.sort()
            for score, left in candidates:
                dropped = set(left)
                kept = [i for i in range(len(ids)) if i not in dropped]
                row = {i: j for j, i in enumerate(kept)}
                cols = [c for c in patterns if not dropped.intersection(c)]
                entry = {'unassigned_ids': [ids[i] for i in left], 'score': score/scale}
                report['candidate_tests'].append(entry)
                if any(not any(i in c for c in cols) for i in kept):
                    entry['status'] = 'uncoverable_material'; continue
                if not kept:
                    chosen = []; result_status = 0
                else:
                    rr, cc = [], []
                    for j, c in enumerate(cols):
                        for i in c:
                            rr.append(row[i]); cc.append(j)
                    A = csc_matrix((np.ones(len(rr)), (rr, cc)), shape=(len(kept), len(cols)))
                    remaining = deadline-time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError('Time limit before LP.')
                    lp = linprog(np.zeros(len(cols)), A_eq=A, b_eq=np.ones(len(kept)),
                                 bounds=(0,1), method='highs', options={'time_limit':remaining})
                    entry['lp_status'] = int(lp.status)
                    if lp.status == 2:
                        entry['status'] = 'lp_infeasible'; continue
                    if lp.status != 0:
                        return finish('Cheaper candidate unresolved by LP; incumbent retained.')
                    remaining = deadline-time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError('Time limit before MIP.')
                    costs = np.array([-1.0 if c in ref_set else 0.0 for c in cols])
                    result = milp(costs, integrality=np.ones(len(cols)), bounds=Bounds(0,1),
                                  constraints=LinearConstraint(A,1,1),
                                  options={'time_limit':remaining, 'mip_rel_gap':0.0})
                    entry.update(mip_status=int(result.status), mip_message=result.message,
                                 mip_objective=None if result.fun is None else float(result.fun),
                                 mip_dual_bound=None if getattr(result,'mip_dual_bound',None) is None else float(result.mip_dual_bound),
                                 mip_gap=None if getattr(result,'mip_gap',None) is None else float(result.mip_gap))
                    if result.status == 2:
                        entry['status'] = 'mip_infeasible'; continue
                    if result.status not in (0,1) or result.x is None:
                        return finish('Cheaper candidate unresolved by MIP; incumbent retained.')
                    if np.max(np.abs(result.x-np.rint(result.x))) > 1e-5:
                        return finish('Nonintegral incumbent returned; original retained.')
                    chosen = [c for c, x in zip(cols, result.x) if x > 0.5]
                    result_status = int(result.status)
                candidate = {'groups':[{'group_id':j+1, 'material_ids':[ids[i] for i in c]}
                                       for j,c in enumerate(chosen)],
                             'unassigned_ids':[ids[i] for i in left]}
                try:
                    _validate(candidate, ids, w, vectors, t1, limits)
                except (ValueError, KeyError, TypeError):
                    entry['status'] = 'solver_candidate_failed_exact_validation'
                    return finish('Solver candidate failed exact validation; original retained.')
                best = candidate
                report.update(score_after=score/scale, primary_optimal_by_solver=True,
                              retention_optimal_for_leftover_set=result_status == 0,
                              enumerated_leftover_sets=enumerated)
                entry['status'] = 'feasible'
                return finish('First feasible score after exhausting all cheaper candidates.')
        report['primary_optimal_by_solver'] = True
        return finish('All strictly better scores excluded; incumbent is optimal.')
    except TimeoutError as exc:
        return finish(str(exc)+' Incumbent retained; no optimality claim.')


def main():
    parser = argparse.ArgumentParser(description=_CLI_DESCRIPTION)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--incumbent', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=float, default=60)
    args = parser.parse_args()
    case = json.loads(args.input.read_text(encoding='utf-8'))
    incumbent = json.loads(args.incumbent.read_text(encoding='utf-8'))
    solution, report = polish(case, incumbent, time_limit=args.seconds)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(solution, ensure_ascii=False, indent=2), encoding='utf-8')
    args.output.with_suffix('.report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
