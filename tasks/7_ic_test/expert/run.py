#!/usr/bin/env python3
_CLI_DESCRIPTION = """Run the expert in an isolated workspace and export its scheduling trace.

Use the dependencies declared in expert/requirements.txt.
"""
from pathlib import Path
import argparse, json, os, random, shutil, sys, time, traceback

ROOT = Path(__file__).resolve().parents[3]
RAW = Path(__file__).resolve().parent
SOURCE = RAW / 'scheduler.py'
import pandas as pd
import numpy as np
from ortools.linear_solver import pywraplp


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + '\n')


def records(df):
    return json.loads(df.to_json(orient='records', date_format='iso', force_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=_CLI_DESCRIPTION)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source', type=Path, default=SOURCE)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    work = out / 'work'; work.mkdir()
    traces = out / 'trace'; traces.mkdir()
    source = args.source.resolve()
    for name in (source.name, 'oracle.xlsx', 'result_template.xlsx', 'merge_template.xlsx'):
        src = source if name == source.name else RAW / name
        shutil.copyfile(src, work / name)
    dump(out/'manifest.json', {'pandas':pd.__version__, 'numpy':np.__version__,
         'solver':pywraplp.Solver.CreateSolver('CBC').SolverVersion(), 'seed':0,
         'changes':'Call wrappers only; fixed random seed for reproducibility; no objective/constraint/state changes.',
         'timestamp_policy':'Recorded dates are source state, never labeled as actual load time unless source assigns one.'})
    os.chdir(work)
    random.seed(0); np.random.seed(0)
    text = source.read_text()
    marker = '"""*************************main\u4e3b\u51fd\u6570\u5f00\u59cb*************************"""'
    definitions, main_code = text.split(marker)
    ns = {'__name__':'__expert__','__file__':str(work/SOURCE.name)}
    exec(compile(definitions,str(SOURCE),'exec'),ns)
    original_schedule = ns['scheduling2']
    original_init = ns['initStatus']
    original_add = ns['add_days']
    events=[]
    def traced_add(start, days):
        end=original_add(start,days)
        events.append({'input_date':start,'days':float(days),'returned_date':end})
        return end
    ns['add_days']=traced_add
    def traced_schedule(day, df, ability, boards, areas, equips, tasks, target, t0, tend):
        stamp=time.monotonic()
        trace={'round':day+1,'t0':str(t0),'tend':str(tend),'tasks_before':records(tasks),
               'areas_before':records(areas),'boards_before':records(boards),'equipment_before':records(equips)}
        dump(traces/f'round_{day+1:02d}_before.json',trace)
        print(f'TRACE begin round={day+1} t0={t0} tend={tend}',flush=True)
        result,used=original_schedule(day,df,ability,boards,areas,equips,tasks,target,t0,tend)
        labeled=records(result)
        for j,row in enumerate(labeled):
            row['_trace_label']=f'round_{day+1:02d}_row_{j:04d}'
            row['_trace_round']=day+1
            row['_trace_t0']=str(t0);row['_trace_tend']=str(tend)
        dump(traces/f'round_{day+1:02d}_assignments.json',labeled)
        print(f'TRACE solved round={day+1} rows={len(result)} qty={result["\u672c\u6b21\u4e0a\u677f\u5668\u4ef6\u6570\u91cf"].sum()} seconds={time.monotonic()-stamp:.2f}',flush=True)
        return result,used
    def traced_init(writer,endDate,ability,boards,areas,equips,data):
        events.clear()
        returned=original_init(writer,endDate,ability,boards,areas,equips,data)
        day=ns['day']
        dump(traces/f'round_{day:02d}_state_update.json',{'round':day,'endDate':endDate,
             't0':str(ns['t0']),'tend':str(ns['tend']),'date_operations':list(events),
             'assignment_rows_before_day_label_overwrite':records(data)})
        return returned
    ns['scheduling2']=traced_schedule;ns['initStatus']=traced_init
    started=time.monotonic()
    try:
        exec(compile('\n'* (definitions.count('\n')+1)+main_code,str(SOURCE),'exec'),ns)
    except BaseException:
        (out/'failure.txt').write_text(traceback.format_exc())
        dump(out/'status.json',{'status':'failed','seconds':time.monotonic()-started,'completed_rounds':ns.get('day')})
        raise
    dump(out/'status.json',{'status':'completed','seconds':time.monotonic()-started,'completed_rounds':ns['day'],
         'rows':len(ns['final_result'])})
    print('TRACE complete',flush=True)

if __name__=='__main__':main()
