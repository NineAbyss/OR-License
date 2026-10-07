#!/usr/bin/env python3
from __future__ import annotations

_CLI_DESCRIPTION = """Improve a food4/01 schedule with count repair and local search."""
import argparse
import importlib.util
import json
import math
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any



def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding='utf-8') as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f'{path}: expected a JSON object')
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def search_input(data: dict, solution: dict) -> str:
    rows = [f"{data['machine_num']} {data['max_loop']} {len(data['demand'])} "
            f"{data['order_weight']} {data.get('process_weight', 30.0)}"]
    for name in ('machine_state', 'yesterday_product', 'product_time'):
        rows.append(' '.join(map(str, data[name])))
    for name in ('demand', 'production_order_matrix', 'transformation_matrix'):
        rows.extend(' '.join(map(str, row)) for row in data[name])
    for machine in solution['machines']:
        seq = [data['product_names'].index(rec['product']) for rec in machine['rounds']
               if rec['product'] != data['product_names'][-1]]
        rows.append(str(len(seq)) + ' ' + ' '.join(map(str, seq)))
    return '\n'.join(rows) + '\n'


def decode_candidate(path: Path, data: dict) -> tuple[dict, float]:
    lines = path.read_text().splitlines()
    predicted = float(lines[0].split()[0])
    if len(lines) != data['machine_num'] + 1:
        raise ValueError('Incorrect machine count in search output')
    names = data['product_names']
    pm, tm = data['production_order_matrix'], data['transformation_matrix']
    result: dict[str, Any] = {'machines': []}
    for m, line in enumerate(lines[1:]):
        values = list(map(int, line.split()))
        if len(values) != values[0] + 1:
            raise ValueError('Incorrect sequence length')
        position, previous = data['machine_state'][m], None
        records = []
        for product in values[1:]:
            pure = position < 10 and pm[product][position] and (
                previous is None or tm[previous][product])
            if not pure:
                legal_change = (position < 10 and pm[5][position]
                                and pm[product][0] and tm[5][product]
                                and (previous is None or tm[previous][5]))
                if not legal_change:
                    raise ValueError('Search returned an illegal lifecycle/transition')
                records.append({'product': names[5], 'batch': 0})
                position = 0
            records.append({'product': names[product], 'batch': 1})
            position += 1
            previous = product
        result['machines'].append({'machine_id': m + 1,
                                   'initial_state': data['machine_state'][m],
                                   'rounds': records})
    for product in range(5):
        slots = []
        for m, machine in enumerate(result['machines']):
            circle = 0
            for rec in machine['rounds']:
                if rec['product'] == names[5]:
                    continue
                if rec['product'] == names[product]:
                    slots.append((circle, m, rec))
                circle += 1
        slots.sort(key=lambda slot: slot[:2])
        labels = [batch + 1 for batch, demand in enumerate(data['demand'])
                  for _ in range(demand[product])]
        if len(slots) != len(labels):
            raise ValueError('Incorrect product demand in search output')
        for (_, _, rec), label in zip(slots, labels):
            rec['batch'] = label
    return result, predicted


def main() -> int:
    parser = argparse.ArgumentParser(description=_CLI_DESCRIPTION)
    parser.add_argument('--input', type=Path, default=Path(__file__).resolve().parents[1] / 'problem/input/testdata/01.json')
    parser.add_argument('--expert', type=Path, required=True)
    parser.add_argument('--judge-dir', type=Path, default=Path(__file__).resolve().parents[1] / 'problem/input/program')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--work-dir', type=Path)
    parser.add_argument('--seed', type=int, default=6)
    parser.add_argument('--iterations', type=int, default=20_000_000)
    parser.add_argument('--compiler', default='g++')
    args = parser.parse_args()
    if args.iterations < 0 or args.seed < 0:
        parser.error('seed and iterations must be nonnegative')
    if args.output.resolve() == args.expert.resolve():
        parser.error('Choose an output path different from the input solution')
    started = time.monotonic()
    data, expert = read_json(args.input), read_json(args.expert)
    bundled = read_json(Path(__file__).resolve().parents[1] / 'problem/input/testdata/01.json')
    if data != bundled:
        raise ValueError('This refinement method supports the bundled food4/01 input')
    verifier = load_module(args.judge_dir / '_food4_verifier.py', 'food4_official_verifier')
    objective = load_module(args.judge_dir / '_food4_objective.py', 'food4_official_objective')
    checked = verifier.verify(expert, data)
    if not checked.valid:
        raise ValueError(f'Expert input is not feasible: {checked.violations}')
    initial_score, initial_details = objective.compute_objective(expert, data)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    work = args.work_dir or Path(tempfile.mkdtemp(prefix='food4_run_', dir=args.output.parent))
    work = work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    write_json(work/'instance.json', data)
    write_json(work/'expert.json', expert)
    (work/'expert_search_input.txt').write_text(search_input(data, expert), encoding='utf-8')
    here = Path(__file__).resolve().parent
    compiler = shutil.which(args.compiler)
    if compiler is None:
        raise FileNotFoundError(f'C++17 compiler not found: {args.compiler}')
    binary = work/'local_search'
    subprocess.run([compiler, '-O3', '-std=c++17', str(here/'local_search.cpp'),
                    '-o', str(binary)], check=True, timeout=120)
    with (work/'initialize_counts.log').open('w') as log:
        subprocess.run([sys.executable, str(here/'initialize_counts.py'),
                        '--work-dir', str(work)], stdout=log, stderr=subprocess.STDOUT,
                       check=True, timeout=180)
    totals = [sum(row[p] for row in data['demand']) for p in range(5)]
    initial_capacity = sum(6 - s for s in data['machine_state'])
    minimum_changes = max(0, math.ceil((sum(totals[:4]) - initial_capacity)/6))
    lower_bound = math.ceil((sum(totals[p]*data['product_time'][p] for p in range(5))
                            + minimum_changes*data['product_time'][5])/data['machine_num'])
    seed_file = work/f'count_seed_{lower_bound+1}.txt'
    if not seed_file.exists():
        seed_file = work/'expert_search_input.txt'
    raw = work/f'candidate_seed{args.seed}.txt'
    with (work/'search.log').open('w') as log:
        subprocess.run([str(binary), str(seed_file), str(raw), str(args.seed),
                        str(args.iterations)], stderr=log, check=True)
    candidate, predicted = decode_candidate(raw, data)
    valid = verifier.verify(candidate, data)
    if not valid.valid:
        raise ValueError(f'Official verifier rejected candidate: {valid.violations}')
    score, details = objective.compute_objective(candidate, data)
    if abs(score-predicted) > 1e-6:
        raise ValueError(f'Objective mismatch: internal={predicted}, official={score}')
    improved = score < initial_score - 1e-9
    selected = candidate if improved else expert
    selected_score, selected_details = (score, details) if improved else (initial_score, initial_details)
    write_json(args.output, selected)
    report = {
        'scope': 'food4/01 count repair and local search',
                'global_optimality_claim': False,
        'seed': args.seed, 'iterations': args.iterations,
        'initial_score': initial_score, 'candidate_score': score,
        'selected_score': selected_score, 'improved': improved,
        'official_verifier_pass': True, 'violations': [],
        'details': selected_details,
        'wall_seconds': time.monotonic()-started,
        'work_dir': str(work),
    }
    report_file = args.output.with_name(args.output.stem+'_evaluation.json')
    write_json(report_file, report)
    print(json.dumps({'score': selected_score, 'verifier': 'passed',
                      'output': str(args.output), 'report': str(report_file)}, ensure_ascii=False))
    return 0

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, ImportError, subprocess.SubprocessError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        raise SystemExit(1)
