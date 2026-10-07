#!/usr/bin/env python3
from __future__ import annotations

_CLI_DESCRIPTION = """reserve food2 The brine replacement position and number of turns in the original schedule, exchange only (batch, product). Only relies on the standard library. """

import argparse
import json
import math
import random
import time
from pathlib import Path
from typing import Any


def improve_solution(data: dict[str, Any], solution: dict[str, Any], *,
                     iterations: int = 500_000, seed: int = 0,
                     same_product_only: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(iterations, int) or iterations < 0:
        raise ValueError("iterations must be a nonnegative integer")
    names, pt, priority = data['product_names'], data['product_time'], data['priority']
    name_index = {name: p for p, name in enumerate(names)}
    brine, nb = len(names) - 1, len(data['demand_num'])
    weight = data['priority_weight']
    if weight < 0 or any(not math.isfinite(t) or t < 0 for t in pt):
        raise ValueError('Require nonnegative finite processing times and weight')
    machines = solution['machines']
    if len(machines) != data['machine_num']:
        raise ValueError('Wrong machine count')
    result = {'machines': [{
        'machine_id': m['machine_id'], 'initial_state': m['initial_state'],
        'rounds': [{'product': r['product'], 'batch': r['batch']} for r in m['rounds']]
    } for m in machines]}
    jobs, masks, record_indices, overhead = [], [], [], []
    produced = [[0] * brine for _ in range(nb)]
    for k, machine in enumerate(machines):
        if (type(machine['machine_id']) is not int or machine['machine_id'] != k + 1
                or type(machine['initial_state']) is not int
                or machine['initial_state'] != data['machine_state'][k]):
            raise ValueError(f'Incorrect identity or initial state on machine {k + 1}')
        position, row, allowed, loc, change_time = data['machine_state'][k], [], [], [], 0
        terminated, empty_loops = False, 0
        records = machine['rounds']
        for rid, record in enumerate(records):
            p, batch = name_index[record['product']], record['batch']
            if type(batch) is not int or not 0 <= position < len(data['input_mat'][0]):
                raise ValueError('Invalid batch type or brine state')
            if p == brine:
                if batch != 0 or data['input_mat'][brine][position] != 1:
                    raise ValueError('Invalid brine operation in the starting solution')
                if rid + 1 == len(records) or records[rid + 1]['product'] == names[brine]:
                    terminated, empty_loops = True, empty_loops + 1
                position = 0
                change_time += pt[brine]
                continue
            if terminated or not 1 <= batch <= nb:
                raise ValueError('Invalid production continuity or batch')
            mask = tuple(data['input_mat'][q][position] == 1 for q in range(brine))
            if not mask[p]:
                raise ValueError('Infeasible product in the starting solution')
            row.append((batch - 1, p)); allowed.append(mask); loc.append(rid)
            produced[batch - 1][p] += 1
            position += 1
        if len(row) + empty_loops > data['max_loop']:
            raise ValueError('Starting solution exceeds the daily loop limit')
        jobs.append(row); masks.append(allowed); record_indices.append(loc)
        overhead.append(change_time)
    if produced != data['demand_num']:
        raise ValueError('Starting solution does not meet exact batch/product demands')
    flat = [(k, i) for k, row in enumerate(jobs) for i in range(len(row))]

    def penalty(row):
        counts, value = [0] * nb, 0
        for b, p in row:
            value += counts[b] * priority[p]
            counts[b] += 1
        return value

    def metrics(rows):
        penalties = [penalty(row) for row in rows]
        times = [overhead[k] + sum(pt[p] for _, p in row) for k, row in enumerate(rows)]
        return penalties, times

    def summary(rows):
        penalties, times = metrics(rows)
        makespan = max(times, default=0)
        return dict(objective=makespan + weight * sum(penalties), makespan=makespan,
                    penalty=sum(penalties), completion_times=times)

    rng = random.Random(seed)
    penalties, times = metrics(jobs)
    current = best = max(times, default=0) + weight * sum(penalties)
    best_jobs = [row.copy() for row in jobs]
    before = summary(jobs)
    start, trace, attempts, accepted = time.perf_counter(), [], 0, 0
    restart_every = 50_000
    for it in range(iterations if len(flat) >= 2 else 0):
        if it % restart_every == 0:
            if it:
                jobs = [row.copy() for row in best_jobs]
                penalties, times = metrics(jobs)
                current = best
            temperature = 4.0 * max(float(weight), 1.0)
        temperature *= 0.99985
        attempts += 1
        a = rng.randrange(len(flat))
        b = rng.randrange(len(flat) - 1); b += b >= a
        k, i = flat[a]; l, j = flat[b]
        u, v = jobs[k][i], jobs[l][j]
        if (u == v or (same_product_only and u[1] != v[1])
                or not masks[k][i][v[1]] or not masks[l][j][u[1]]):
            continue
        jobs[k][i], jobs[l][j] = v, u
        pk = penalty(jobs[k]); pl = penalty(jobs[l]) if l != k else pk
        delta_penalty = pk - penalties[k] + (pl - penalties[l] if l != k else 0)
        tk, tl = times[k], times[l]
        if k != l:
            times[k] += pt[v[1]] - pt[u[1]]
            times[l] += pt[u[1]] - pt[v[1]]
        candidate = max(times) + weight * (sum(penalties) + delta_penalty)
        delta = candidate - current
        if delta <= 0 or rng.random() < math.exp(-delta / max(temperature, 0.01)):
            penalties[k], penalties[l], current = pk, pl, candidate
            accepted += 1
            if candidate < best:
                best = candidate
                best_jobs = [row.copy() for row in jobs]
                trace.append({'iteration': it + 1, 'objective': best})
        else:
            jobs[k][i], jobs[l][j] = u, v
            times[k], times[l] = tk, tl
    for k, row in enumerate(best_jobs):
        for i, (batch, product) in enumerate(row):
            result['machines'][k]['rounds'][record_indices[k][i]] = {
                'product': names[product], 'batch': batch + 1}
    after = summary(best_jobs)
    if after['objective'] > before['objective'] or abs(after['objective'] - best) > 1e-6:
        raise AssertionError('Internal objective consistency failure')
    stats = dict(seed=seed, requested_iterations=iterations, attempted_swaps=attempts,
                 accepted_swaps=accepted, same_product_only=same_product_only,
                 elapsed_seconds=time.perf_counter() - start,
                 restart_every=restart_every, cooling_factor=0.99985,
                 before=before, after=after, improvements=trace)
    return result, stats


def improve_file(input_path: str | Path, solution_path: str | Path, output_path: str | Path,
                 *, iterations: int = 500_000, seed: int = 0) -> dict[str, Any]:
    input_path, solution_path, output_path = map(Path, (input_path, solution_path, output_path))
    if output_path.resolve() in (input_path.resolve(), solution_path.resolve()):
        raise ValueError('Use a different output path; preserve the original reference')
    data = json.loads(input_path.read_text(encoding='utf-8'))
    solution = json.loads(solution_path.read_text(encoding='utf-8'))
    improved, stats = improve_solution(data, solution, iterations=iterations, seed=seed)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(improved, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    output_path.with_suffix('.stats.json').write_text(
        json.dumps(stats, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return stats


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=_CLI_DESCRIPTION)
    ap.add_argument('--input', required=True)
    ap.add_argument('--solution', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--iterations', type=int, default=500_000)
    ap.add_argument('--seed', type=int, default=0)
    args = ap.parse_args()
    info = improve_file(args.input, args.solution, args.output, iterations=args.iterations, seed=args.seed)
    print(json.dumps({k: info[k] for k in ('before', 'after', 'elapsed_seconds')}, ensure_ascii=False, indent=2))
