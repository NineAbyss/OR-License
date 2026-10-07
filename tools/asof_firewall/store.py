#!/usr/bin/env python3

from __future__ import annotations

_CLI_DESCRIPTION = """Rebuild the time-varying bundle surfaces as month chunks.

A view for decision day t is mostly whole months, which hardlink for free, plus
one partial month that has to be written. Day-level chunking was measured at
~48 GB because a 5476-column parquet carries ~3 MB of column metadata per file
regardless of row count, so months are the smallest chunk that stays cheap.
"""

import argparse
import fcntl
import json
import shutil
import tempfile
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from surfaces import BUNDLE, Surface, scan

STORE = Path(__file__).resolve().parents[2] / ".asof" / "store"
CHUNK_FMT = "%Y-%m"


def _chunk_dir(surface: Surface, store: Path | None = None) -> Path:
    return (store if store is not None else STORE) / surface.rel


def _write_chunks(
    frame: pd.DataFrame, dates: pd.Series, target: Path, keep_index: bool
) -> list[str]:
    target.mkdir(parents=True, exist_ok=True)
    schema = pa.Table.from_pandas(frame, preserve_index=keep_index).schema
    keys = dates.dt.strftime(CHUNK_FMT)
    written = []
    for key, chunk in frame.groupby(keys.to_numpy(), sort=True):
        table = pa.Table.from_pandas(chunk, schema=schema, preserve_index=keep_index)
        pq.write_table(table, target / f"{key}.parquet")
        written.append(str(key))
    return written


def build_wide(surface: Surface, store: Path | None = None) -> list[str]:
    frame = pd.read_parquet(surface.path)
    index = pd.Series(pd.to_datetime(frame.index), index=frame.index)
    return _write_chunks(frame, index, _chunk_dir(surface, store), keep_index=True)


def build_long(surface: Surface, store: Path | None = None) -> list[str]:
    frame = pd.read_parquet(surface.path)
    dates = pd.to_datetime(frame[surface.date_field])
    return _write_chunks(frame, dates, _chunk_dir(surface, store), keep_index=False)


def build_feather(surface: Surface, store: Path | None = None) -> list[str]:
    frame = pd.read_feather(surface.path)
    dates = pd.to_datetime(frame[surface.date_field])
    return _write_chunks(frame, dates, _chunk_dir(surface, store), keep_index=False)


def build_csv(surface: Surface, store: Path | None = None) -> list[str]:
    frame = pd.read_csv(surface.path)
    dates = pd.to_datetime(frame[surface.date_field])
    return _write_chunks(frame, dates, _chunk_dir(surface, store), keep_index=False)


BUILDERS = {
    "wide": build_wide,
    "long": build_long,
    "feather": build_feather,
    "csv": build_csv,
}


def ensure(force: bool = False) -> None:
    destination = STORE
    if not force and (destination / "catalog.json").is_file():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    with (destination.parent / "store.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not force and (destination / "catalog.json").is_file():
            return
        staging = Path(tempfile.mkdtemp(prefix="store-build-", dir=destination.parent))
        try:
            build(store=staging)
            if destination.exists():
                shutil.rmtree(destination)
            staging.rename(destination)
        finally:
            if staging.exists():
                shutil.rmtree(staging)


def build(force: bool = False, *, store: Path | None = None) -> dict[str, list[str]]:
    store = store if store is not None else STORE
    inventory = scan()
    catalog: dict[str, list[str]] = {}
    for kind, builder in BUILDERS.items():
        for surface in inventory.by_kind(kind):
            target = _chunk_dir(surface, store)
            if target.exists() and not force:
                catalog[surface.rel] = sorted(p.stem for p in target.glob("*.parquet"))
                continue
            if target.exists():
                shutil.rmtree(target)
            catalog[surface.rel] = builder(surface, store)
            print(f"  chunked {surface.rel} -> {len(catalog[surface.rel])} months")
    store.mkdir(parents=True, exist_ok=True)
    (store / "catalog.json").write_text(
        json.dumps(catalog, indent=2, sort_keys=True), encoding="utf-8"
    )
    return catalog


def main() -> int:
    parser = argparse.ArgumentParser(description=_CLI_DESCRIPTION)
    parser.add_argument("--force", action="store_true", help="rebuild existing chunks")
    args = parser.parse_args()
    ensure(force=args.force)
    catalog = json.loads((STORE / "catalog.json").read_text())
    total = sum(len(v) for v in catalog.values())
    print(f"\n{len(catalog)} surfaces chunked into {total} month files")
    print(f"store at {STORE} ({sum(p.stat().st_size for p in STORE.rglob('*.parquet')) / 1e9:.2f} GB)")
    print(f"bundle source {BUNDLE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
