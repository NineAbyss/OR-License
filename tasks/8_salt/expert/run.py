#!/usr/bin/env python3
_CLI_DESCRIPTION = """Run the rolling expert in an isolated output directory."""
from pathlib import Path
import argparse, contextlib, json, os, runpy, shutil, sys

def main():
    parser=argparse.ArgumentParser(description=_CLI_DESCRIPTION)
    parser.add_argument('--output',type=Path,required=True,help='New run directory')
    parser.add_argument('--max-periods',type=int,default=5000)
    parser.add_argument('--max-no-feasible',type=int,default=20)
    parser.add_argument('--start',default=None)
    parser.add_argument('--dependency-path',type=Path,help='Optional additional site-packages for OR-Tools')
    args=parser.parse_args()
    import pandas,openpyxl
    if args.dependency_path:sys.path.append(str(args.dependency_path.resolve()))
    from ortools.linear_solver import pywraplp
    assert pywraplp.Solver.CreateSolver('CBC') is not None
    root=Path(__file__).resolve().parents[3];source=Path(__file__).resolve().parent;dest=args.output.resolve()
    if dest.exists() and any(dest.iterdir()):raise SystemExit('Output directory must be new or empty')
    dest.mkdir(parents=True,exist_ok=True)
    names=['scheduler.py','orders.xlsx','capacity.xlsx']
    for name in names:shutil.copy2(source/name,dest/name)
    flags=['--until-complete','--max-periods',str(args.max_periods),'--max-no-feasible',str(args.max_no_feasible),'--checkpoint-every','100','--quiet','--output','result.xlsx']
    if args.start:flags+=['--start',args.start]
    manifest=dict(source=str((source/names[0]).relative_to(root)),flags=flags,pandas=pandas.__version__)
    (dest/'source_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    previous=Path.cwd();argv=sys.argv[:]
    try:
        os.chdir(dest);sys.argv=[str(dest/names[0]),*flags]
        with (dest/'stdout.log').open('w') as log,contextlib.redirect_stdout(log):
            runpy.run_path(str(dest/names[0]),run_name='__main__')
    finally:os.chdir(previous);sys.argv=argv
    print(f'Current expert run saved to {dest}. Use convert_output.py --run to verify.')
    return 0
if __name__=='__main__':raise SystemExit(main())
