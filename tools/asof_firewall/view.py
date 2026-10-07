#!/usr/bin/env python3

from __future__ import annotations

_CLI_DESCRIPTION = """Assemble the data root an agent may read on one decision day.

A view holds everything knowable at the close of day t and nothing else. Whole
months hardlink from the chunk store at no cost; only the month containing t
gets rewritten. Replay blobs are gated by the as-of date recorded in their
manifest, and the handful of range fetches are truncated row-wise.

Suspension lookups are the one sanctioned exception: the replay runtime asks
which names halt on t+1, which the exchange announces before t closes.
"""

import argparse
import json
import pickle
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from store import CHUNK_FMT, STORE, ensure
from surfaces import BUNDLE, DATA, DUP_SUFFIX, Surface, plan_blobs, scan

VIEWS = Path(__file__).resolve().parents[2] / ".asof" / "views"
ROW_KINDS = ("wide", "long", "feather", "csv")
CALENDAR = DATA / "snapshot" / "calendar.csv"


def next_trade_day(day: pd.Timestamp) -> pd.Timestamp:
    sessions = pd.to_datetime(pd.read_csv(CALENDAR)["date"])
    later = sessions[sessions > day]
    if later.empty:
        raise ValueError(f"calendar ends before {day.date()}")
    return later.iloc[0]


@dataclass
class ViewStats:
    linked: int = 0
    written: int = 0
    blobs_kept: int = 0
    blobs_dropped: int = 0
    blobs_truncated: int = 0
    seconds: float = 0.0

    def render(self) -> str:
        return (
            f"linked={self.linked} written={self.written} "
            f"blobs kept={self.blobs_kept} truncated={self.blobs_truncated} "
            f"dropped={self.blobs_dropped} in {self.seconds:.1f}s"
        )


def _link(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        dst.hardlink_to(src)
    except OSError:
        shutil.copy2(src, dst)


def _row_dates(frame: pd.DataFrame, surface: Surface) -> pd.Series:
    if surface.kind == "wide":
        return pd.Series(pd.to_datetime(frame.index), index=frame.index)
    return pd.to_datetime(frame[surface.date_field])


def _place_chunks(surface: Surface, asof: pd.Timestamp, root: Path, stats: ViewStats) -> None:
    source = STORE / surface.rel
    if not source.exists():
        raise FileNotFoundError(f"chunk store missing {surface.rel}; run store.py first")
    chunks = [c for c in sorted(source.glob("*.parquet")) if c.stem <= asof.strftime(CHUNK_FMT)]

    if surface.kind in {"feather", "csv"}:
        _place_single_file(surface, asof, root, chunks, stats)
        return

    target = root / surface.rel
    target.mkdir(parents=True, exist_ok=True)
    current = asof.strftime(CHUNK_FMT)
    for chunk in chunks:
        if chunk.stem < current:
            _link(chunk, target / chunk.name)
            stats.linked += 1
            continue
        frame = pd.read_parquet(chunk)
        kept = frame.loc[_row_dates(frame, surface) <= asof]
        kept.to_parquet(target / chunk.name)
        stats.written += 1


def _place_single_file(
    surface: Surface, asof: pd.Timestamp, root: Path, chunks: list[Path], stats: ViewStats
) -> None:
    target = root / surface.rel
    target.parent.mkdir(parents=True, exist_ok=True)
    frames = [pd.read_parquet(c) for c in chunks]
    frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if len(frame):
        frame = frame.loc[_row_dates(frame, surface) <= asof].reset_index(drop=True)
    if surface.kind == "feather":
        frame.to_feather(target)
    else:
        frame.to_csv(target, index=False)
    stats.written += 1


def _place_date_files(surfaces: list[Surface], asof: pd.Timestamp, root: Path, stats: ViewStats) -> None:
    for surface in surfaces:
        if pd.Timestamp(surface.path.name) <= asof:
            _link(surface.path, root / surface.rel)
            stats.linked += 1


def _place_blobs(
    cache: str,
    asof: pd.Timestamp,
    root: Path,
    stats: ViewStats,
    suspend_horizon: pd.Timestamp,
) -> None:
    cache_root = DATA / "snapshot" / cache
    plan = plan_blobs(cache_root)
    target = root / cache_root.relative_to(BUNDLE)
    target.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((cache_root / "index.json").read_text(encoding="utf-8"))
    kept_manifest: dict[str, object] = {}

    for blob_id, date_str in plan.gated.items():
        record = manifest.get(blob_id) or manifest.get(DUP_SUFFIX.sub("", blob_id), {})
        payload = f"{record.get('name', '')} {record.get('args', '')}"
        limit = suspend_horizon if _is_suspend_call(payload) else asof
        if pd.Timestamp(date_str) > limit:
            stats.blobs_dropped += 1
            continue
        _link(cache_root / f"{blob_id}.pkl", target / f"{blob_id}.pkl")
        stats.blobs_kept += 1
        if record:
            kept_manifest[blob_id] = record

    for blob_id in plan.ranged:
        frame = pickle.loads((cache_root / f"{blob_id}.pkl").read_bytes())
        kept = frame.loc[pd.to_datetime(frame["datetime"]) <= asof]
        (target / f"{blob_id}.pkl").write_bytes(pickle.dumps(kept))
        stats.blobs_truncated += 1

    for blob_id in plan.denied:
        stats.blobs_dropped += 1

    (target / "index.json").write_text(
        json.dumps(kept_manifest, indent=1, sort_keys=True), encoding="utf-8"
    )


def _is_suspend_call(payload: str) -> bool:
    return "SuspendResumption" in payload or "get_suspend_stocks" in payload


def is_complete(root: Path) -> bool:
    return (root / "ASOF.json").is_file()


def build_view(asof: str, root: Path | None = None, force: bool = False) -> Path:
    started = time.time()
    day = pd.Timestamp(asof)
    root = root or VIEWS / asof
    if root.exists():
        if not force and is_complete(root):
            return root
        shutil.rmtree(root)
    ensure()
    root.mkdir(parents=True, exist_ok=True)

    inventory = scan()
    stats = ViewStats()
    horizon = next_trade_day(day)

    for kind in ROW_KINDS:
        for surface in inventory.by_kind(kind):
            _place_chunks(surface, day, root, stats)
    _place_date_files(inventory.by_kind("date_file"), day, root, stats)
    for cache in ("clickhouse_queries", "optimizer_fetcher_calls"):
        _place_blobs(cache, day, root, stats, horizon)

    _link(DATA / "snapshot" / "calendar.csv", root / "data/snapshot/calendar.csv")
    _link(BUNDLE / "config.yaml", root / "config.yaml")
    stats.seconds = time.time() - started
    (root / "ASOF.json").write_text(
        json.dumps(
            {
                "as_of": asof,
                "execution_day": str(horizon.date()),
                "stats": stats.__dict__,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"view {asof}: {stats.render()}")
    return root


def main() -> int:
    parser = argparse.ArgumentParser(description=_CLI_DESCRIPTION)
    parser.add_argument("dates", nargs="+", help="decision dates, YYYY-MM-DD")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    for date in args.dates:
        path = build_view(date, force=args.force)
        size = sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
        print(f"  -> {path} ({size / 1e9:.2f} GB apparent)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
