#!/usr/bin/env python3

from __future__ import annotations

_CLI_DESCRIPTION = """Prove a view exposes nothing dated after its decision day.

Every file is reopened and its own timestamps are read back, so the check does
not trust the builder's bookkeeping. Only the announced-halt calendar may reach
past the decision day, and it may not reach past the execution day.
"""

import argparse
import json
import pickle
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from surfaces import ISO_DATE, SENTINEL_DATES

VIEWS = Path(__file__).resolve().parents[2] / ".asof" / "views"
BANNED_NAMES = ("results", "performance_summary", "daily_nav_and_returns")


@dataclass
class Leak:
    path: str
    latest: str
    detail: str


@dataclass
class Report:
    asof: str
    files_checked: int = 0
    rows_checked: int = 0
    leaks: list[Leak] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)
    exempt: int = 0

    @property
    def clean(self) -> bool:
        return not self.leaks and not self.unreadable

    def render(self) -> str:
        head = (
            f"as-of {self.asof}: {self.files_checked} files, "
            f"{self.rows_checked:,} dated rows, {self.exempt} sanctioned exemptions"
        )
        if self.clean:
            return f"{head}\n  PASS - no data past {self.asof}"
        lines = [head, f"  FAIL - {len(self.leaks)} leaks, {len(self.unreadable)} unreadable"]
        for leak in self.leaks[:10]:
            lines.append(f"    {leak.path}: latest={leak.latest} ({leak.detail})")
        for item in self.unreadable[:5]:
            lines.append(f"    unreadable: {item}")
        return "\n".join(lines)


def _frame_max(frame: pd.DataFrame) -> pd.Timestamp | None:
    stamps: list[pd.Timestamp] = []
    if isinstance(frame.index, pd.DatetimeIndex) and len(frame.index):
        stamps.append(frame.index.max())
    for column in frame.columns:
        if str(column).lower() in {"datetime", "date", "cre_time"}:
            values = pd.to_datetime(frame[column], errors="coerce").dropna()
            if len(values):
                stamps.append(values.max())
    return max(stamps) if stamps else None


def _is_suspend_blob(blob_id: str, manifest: dict) -> bool:
    record = manifest.get(blob_id, {})
    payload = f"{record.get('name', '')} {record.get('args', '')}"
    return "SuspendResumption" in payload or "get_suspend_stocks" in payload


def check(view_root: Path, execution_day: str | None = None) -> Report:
    stamp = json.loads((view_root / "ASOF.json").read_text(encoding="utf-8"))
    asof = stamp["as_of"]
    limit = pd.Timestamp(asof)
    horizon = pd.Timestamp(execution_day or stamp.get("execution_day", asof))
    report = Report(asof=asof)

    manifests: dict[Path, dict] = {}
    for path in sorted(view_root.rglob("index.json")):
        manifests[path.parent] = json.loads(path.read_text(encoding="utf-8"))

    for path in sorted(view_root.rglob("*")):
        if not path.is_file() or path.name in {"ASOF.json", "index.json"}:
            continue
        rel = str(path.relative_to(view_root))
        if any(token in rel for token in BANNED_NAMES):
            report.leaks.append(Leak(rel, "-", "vendor answer surface present"))
            continue
        report.files_checked += 1

        try:
            latest, rows = _latest_stamp(path)
        except Exception as exc:
            report.unreadable.append(f"{rel}: {exc}")
            continue

        report.rows_checked += rows
        if latest is None or latest <= limit:
            continue
        if path.suffix == ".pkl" and _is_suspend_blob(path.stem, manifests.get(path.parent, {})):
            if latest <= horizon:
                report.exempt += 1
                continue
        report.leaks.append(Leak(rel, str(latest.date()), f"{rows} rows"))
    return report


def _latest_stamp(path: Path) -> tuple[pd.Timestamp | None, int]:
    if path.suffix == ".parquet":
        frame = pd.read_parquet(path)
        return _frame_max(frame), len(frame)
    if path.suffix == ".pkl":
        obj = pickle.loads(path.read_bytes())
        if isinstance(obj, pd.DataFrame):
            return _frame_max(obj), len(obj)
        return None, 0
    if path.name == "calendar.csv":
        return None, 0
    if ISO_DATE.fullmatch(path.name):
        return pd.Timestamp(path.name), 1
    if path.suffix in {".csv", ".yaml", ".yml", ".json"}:
        text = path.read_text(encoding="utf-8", errors="ignore")
        found = [d for d in ISO_DATE.findall(text) if d not in SENTINEL_DATES]
        return (pd.Timestamp(max(found)) if found else None), len(found)
    return None, 0


def main() -> int:
    parser = argparse.ArgumentParser(description=_CLI_DESCRIPTION)
    parser.add_argument("dates", nargs="+")
    parser.add_argument("--execution-day", default=None)
    args = parser.parse_args()
    failed = False
    for date in args.dates:
        report = check(VIEWS / date, args.execution_day)
        print(report.render())
        failed |= not report.clean
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
