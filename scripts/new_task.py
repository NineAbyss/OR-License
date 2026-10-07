#!/usr/bin/env python3
from __future__ import annotations

_CLI_DESCRIPTION = """Create a new task directory from templates/task and register it in tasks/paths.py.

Example:
  python scripts/new_task.py 32_cold_chain_routing --author "Ada Lovelace" \\
      --email ada@example.edu --organization "Example University" \\
      --experience "Ten years of vehicle-routing projects for grocery retailers."

The new task is a working copy of the packaging-line example. Replace its brief,
problem description, instances, verifier, evaluator, ledger and reference solution
with your own, then run scripts/validate_task.py on it."""

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates/task"
TASKS_ROOT = ROOT / "tasks"
PLACEHOLDER = "example_task"
NAME_PATTERN = re.compile(r"^[1-9][0-9]*_[a-z0-9]+(?:_[a-z0-9]+)*$")
RENAMED_FILES = (
    "task.toml",
    "README.md",
    "simulator/simulator_config.yaml",
    "simulator/interaction/ledger.json",
    "problem/evaluation_groups.json",
)


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def scaffold(name: str, destination: Path, *, author: str, email: str, organization: str,
             experience: str = "") -> Path:
    if not NAME_PATTERN.match(name):
        raise ValueError(f"task name {name!r} must look like <number>_<lowercase_words>")
    if "sharedbike" in name:
        raise ValueError("names containing 'sharedbike' are reserved for the shared bike suite")
    target = destination / name
    if target.exists():
        raise FileExistsError(f"{target} already exists")
    shutil.copytree(TEMPLATE, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for relative in RENAMED_FILES:
        path = target / relative
        path.write_text(path.read_text(encoding="utf-8").replace(PLACEHOLDER, name), encoding="utf-8")
    manifest = target / "task.toml"
    text = manifest.read_text(encoding="utf-8")
    replacements = {
        '{ name = "Example Author", email = "author@example.org" }':
            f"{{ name = {_toml_string(author)}, email = {_toml_string(email)} }}",
        'author_organization = "Example Organization"': f"author_organization = {_toml_string(organization)}",
        'relevant_experience = ""': f"relevant_experience = {_toml_string(experience)}",
    }
    for old, new in replacements.items():
        if old not in text:
            raise RuntimeError(f"template task.toml no longer contains {old!r}")
        text = text.replace(old, new)
    manifest.write_text(text, encoding="utf-8")
    return target


def register(name: str, paths_file: Path = TASKS_ROOT / "paths.py") -> bool:
    text = paths_file.read_text(encoding="utf-8")
    match = re.search(r"TASKS: tuple\[str, \.\.\.\] = \(\n(.*?)\n\)", text, flags=re.DOTALL)
    if match is None:
        raise RuntimeError("cannot find the TASKS tuple in tasks/paths.py")
    if f'"{name}"' in match.group(1):
        return False
    body = match.group(1) + f'\n    "{name}",'
    paths_file.write_text(text[:match.start(1)] + body + text[match.end(1):], encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=_CLI_DESCRIPTION, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("name", help="task directory name, for example 32_cold_chain_routing")
    parser.add_argument("--author", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--organization", required=True, help='affiliation, or "Independent Researcher"')
    parser.add_argument("--experience", default="", help="one or two sentences on your relevant background")
    parser.add_argument("--no-register", action="store_true", help="do not add the task to tasks/paths.py")
    args = parser.parse_args(argv)
    try:
        target = scaffold(args.name, TASKS_ROOT, author=args.author, email=args.email,
                          organization=args.organization, experience=args.experience)
    except (ValueError, FileExistsError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not args.no_register:
        register(args.name)
    print(f"Created {target.relative_to(ROOT)}")
    print(f"Next: edit the files listed in TASK_FORMAT.md, then run")
    print(f"  python scripts/validate_task.py tasks/{args.name} --strict --oracle")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
