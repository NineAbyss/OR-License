
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pandas as pd
class Dict(dict):
    def __missing__(self, key):
        value = type(self)()
        self[key] = value
        return value

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            value = type(self)()
            self[name] = value
            return value

    def __setattr__(self, name, value):
        self[name] = value

datas = Dict()


def _root() -> Path:
    value = os.environ.get("QUANT_PRO_FACTOR_SNAPSHOT_DIR")
    if not value:
        raise RuntimeError("QUANT_PRO_FACTOR_SNAPSHOT_DIR is required for offline data_process")
    return Path(value)


def _names(item: str) -> list[str]:
    if "=" not in item:
        return [item]
    _, spec = item.split("=", 1)
    columns = spec.rsplit(":", 1)[-1].split(",")
    return [name for name in columns if name not in {"datetime", "date", "instrument"}]


def load_factor(
    name: str,
    freq: str = "day",
    root_path: str | None = None,
    limit_start: str | None = None,
    limit_end: str | None = None,
    **_: Any,
) -> pd.DataFrame | None:
    root = Path(root_path) if root_path else _root()
    path = root / freq / f"{name}.parquet"
    if not path.exists():
        return None
    frame = pd.read_parquet(path)
    frame.index = pd.to_datetime(frame.index)
    if limit_start is not None:
        frame = frame.loc[pd.Timestamp(limit_start):]
    if limit_end is not None:
        frame = frame.loc[:pd.Timestamp(limit_end)]
    return frame.sort_index().sort_index(axis=1)


def load_factors(
    names: list[str],
    freq: str = "day",
    refresh: bool = False,
    out: Any | None = None,
    **kwargs: Any,
) -> Any:
    target = datas[freq] if out is None else out
    for item in names:
        for name in _names(item):
            if refresh or target.get(name) is None:
                frame = load_factor(name, freq=freq, **kwargs)
                if frame is None:
                    raise FileNotFoundError(f"offline factor snapshot missing: {freq}/{name}.parquet")
                target[name] = frame
    return target


def align_datas(base: str | pd.DataFrame, dataset: Any = None, inplace: bool = False, **_: Any) -> Any:
    dataset = datas["day"] if dataset is None else dataset
    base_frame = dataset[base] if isinstance(base, str) else base
    target = dataset if inplace else Dict()
    for key in list(dataset.keys()):
        value = dataset[key]
        if hasattr(value, "reindex"):
            target[key] = value.reindex(base_frame.index).reindex(base_frame.columns, axis=1)
    return target


def join_factors(
    names: list[str],
    dataset: Any,
    index: Any = None,
    columns: Any = None,
    remove_all_nan_row: bool = True,
) -> pd.DataFrame:
    pieces = [dataset[name].stack(dropna=remove_all_nan_row).rename(name) for name in names]
    result = pd.concat(pieces, axis=1)
    if index is not None:
        result = result.reindex(index=index)
    if columns is not None:
        result = result.reindex(columns=columns)
    return result


def load_factor_from_file(path: str, limit_start: str | None = None, limit_end: str | None = None) -> pd.DataFrame:
    frame = pd.read_parquet(path) if str(path).endswith(".parquet") else pd.read_csv(path)
    if "datetime" in frame.columns:
        frame["datetime"] = pd.to_datetime(frame["datetime"])
        if limit_start is not None:
            frame = frame[frame["datetime"] >= pd.Timestamp(limit_start)]
        if limit_end is not None:
            frame = frame[frame["datetime"] <= pd.Timestamp(limit_end)]
    return frame
