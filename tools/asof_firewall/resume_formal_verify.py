#!/usr/bin/env python3
from __future__ import annotations

_CLI_DESCRIPTION = "Resume a failed independent as-of formal verify in a fresh run directory."

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from harbor_integration.coding_agent.runtime import harbor_python

RUNNER = Path(__file__).with_name("formal_verify_once.py")
TASKS = {"20_enhanced_index_asof", "21_longshort", "22_sif"}


def prepare(source: Path, target: Path, requested_task: str | None) -> tuple[Path, str]:
    source = source.resolve(strict=True)
    target = target.resolve()
    if target.exists():
        raise FileExistsError(f"target run already exists: {target}")
    result_path = source / "verify_result.json"
    if result_path.is_file():
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if not result.get("finished_utc"):
            raise ValueError("source verify is still running or lacks a terminal record")
    score_path = source / "private/asof_development/asof_score.json"
    if not score_path.is_file():
        score_path = source / "private/asof_evaluation/asof_score.json"
    if not score_path.is_file():
        raise ValueError(f"source has no formal score record: {score_path}")
    score = json.loads(score_path.read_text(encoding="utf-8"))
    evaluation = (score.get("windows") or {}).get("evaluation") or {}
    calls = score_path.parent / "evaluation_calls"
    if not any(calls.glob("202*-*/daily_record.json")):
        raise ValueError(f"source has no daily replay records: {calls}")
    task_file = source / "task/task.toml"
    task_name = tomllib.loads(task_file.read_text(encoding="utf-8"))["task"]["name"]
    task = str(task_name).split("/")[-1]
    if task not in TASKS or (requested_task is not None and requested_task != task):
        raise ValueError(f"source task {task!r} does not match a supported resume task")
    if evaluation.get("failure_class") != "infrastructure_failure":
        raise ValueError("resume source must have an infrastructure failure")
    manifest_path = source / "manifest.json"
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.is_file() else {}
    )
    submission = source / "private/submitted/01.json"
    environment = source / "task/environment"
    compose_files = sorted(environment.glob("*.yaml"))
    compose = environment / "docker-compose.yaml"
    if compose not in compose_files or str(source) not in compose.read_text(encoding="utf-8"):
        raise ValueError("source compose file does not name the source run directory")

    target.mkdir(parents=True)
    shutil.copy2(source / "backtest", target / "backtest")
    for name in ("public_input", "task"):
        shutil.copytree(source / name, target / name)
    destination = target / "private/submitted"
    destination.mkdir(parents=True)
    shutil.copy2(submission, destination / "01.json")
    if (destination / "01.json").read_bytes() != submission.read_bytes():
        raise ValueError("copied submission differs from the source run")
    for name in ("output", "workspace"):
        path = target / name
        path.mkdir()
        path.chmod(0o777)
    for path in compose_files:
        (target / "task/environment" / path.name).write_text(
            path.read_text(encoding="utf-8").replace(str(source), str(target)),
            encoding="utf-8",
        )
    manifest.update({
        "task": task,
        "resumed_from": str(source),
        "resume_calls_root": str(calls),
        "resume_started_utc": datetime.now(timezone.utc).isoformat(),
        "original_artifacts_preserved": True,
    })
    (target / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return calls, task


def main() -> int:
    parser = argparse.ArgumentParser(description=_CLI_DESCRIPTION)
    parser.add_argument("--source", type=Path, required=True,
                        help="failed independent verify run directory")
    parser.add_argument("--target", type=Path, required=True,
                        help="new, nonexistent run directory")
    parser.add_argument("--task", choices=sorted(TASKS),
                        help="must match the task named in source task.toml")
    parser.add_argument("--detach", action="store_true",
                        help="return after launching the new verify")
    args = parser.parse_args()
    calls, task = prepare(args.source, args.target, args.task)
    target = args.target.resolve()
    env = dict(os.environ, ORLE_ASOF_RESUME_FROM=str(calls))
    command = [harbor_python(), "-I", str(RUNNER),
               "--root", str(target), "--task", task]
    if args.detach:
        with (target / "verify_stdout.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                command, cwd=str(target.parent), env=env,
                stdin=subprocess.DEVNULL, stdout=log,
                stderr=subprocess.STDOUT, start_new_session=True,
            )
        print(json.dumps({"target": str(target), "pid": process.pid,
                          "resume_calls_root": str(calls), "task": task}))
        return 0
    exit_code = subprocess.call(command, cwd=str(target.parent), env=env)
    result_path = target / "verify_result.json"
    if exit_code != 0 or not result_path.is_file():
        return 1
    result = json.loads(result_path.read_text(encoding="utf-8"))
    evaluation = (result.get("score") or {}).get("windows", {}).get("evaluation", {})
    return 0 if (
        result.get("completed")
        and evaluation.get("run_completed")
        and evaluation.get("covers_full_window")
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
