#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

SLIPS_RELATIVE = "data/market/merged_bonds_240301_251225.csv"


def _read(view: Path) -> pd.DataFrame:
    frame = pd.read_csv(Path(view) / SLIPS_RELATIVE)
    frame["id"] = frame["id"].map(str)
    frame["instrument"] = frame["instrument"].map(str)
    frame["available"] = pd.to_numeric(frame["available"], errors="coerce").fillna(0.0)
    frame["apply_rate"] = pd.to_numeric(frame["apply_rate"], errors="coerce").fillna(0.0)
    return frame


def load_slips(view: Path, date: str) -> pd.DataFrame:
    frame = _read(view)
    return frame.loc[frame["cre_time"].astype(str).str.startswith(date)].copy()


def load_slip_index(view: Path, date: str) -> dict[str, str]:
    frame = _read(view)
    upto = frame.loc[frame["cre_time"].astype(str).str[:10] <= date]
    return dict(zip(upto["id"], upto["instrument"]))


def slips_to_stocks(frame: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    out = frame.copy()
    out["instrument"] = out["instrument"].map(str).map(lambda x: mapping.get(x, x))
    return out.groupby("instrument", as_index=False)["weight"].sum()


def stocks_to_slips(
    frame: pd.DataFrame,
    slips: pd.DataFrame,
    close: dict[str, float],
    total_value: float,
    *,
    position: pd.DataFrame | None = None,
    slip_index: dict[str, str] | None = None,
) -> pd.DataFrame:
    if not len(frame):
        return frame
    rows: list[dict[str, object]] = []
    by_stock = {
        name: group.sort_values(
            ["apply_rate", "available"], ascending=[True, False]
        )
        for name, group in slips.groupby("instrument")
    }
    held_by_stock: dict[str, list[tuple[str, float]]] = {}
    if position is not None and len(position) and slip_index and total_value:
        for record in position.itertuples(index=False):
            code = str(record.stockcode)
            stock = slip_index.get(code)
            if stock is None:
                continue
            held_w = float(record.volume) * float(record.close) / float(total_value)
            if held_w <= 0:
                continue
            held_by_stock.setdefault(stock, []).append((code, held_w))
    for record in frame.itertuples(index=False):
        instrument = str(record.instrument)
        weight = float(record.weight)
        if weight >= 0:
            rows.append({"instrument": instrument, "weight": weight})
            continue
        remaining = -weight
        price = float(close.get(instrument, 0.0))
        for slip_id, held_w in held_by_stock.get(instrument, []):
            if remaining <= 0:
                break
            take = min(held_w, remaining)
            rows.append({"instrument": slip_id, "weight": -take})
            remaining -= take
        for slip in by_stock.get(instrument, pd.DataFrame()).itertuples(index=False):
            if remaining <= 0:
                break
            capacity = float(slip.available) * price / total_value if total_value else 0.0
            if capacity <= 0:
                continue
            take = min(capacity, remaining)
            rows.append({"instrument": str(slip.id), "weight": -take})
            remaining -= take
    return pd.DataFrame(rows)


def prior_weights(
    position: pd.DataFrame | None,
    slip_index: dict[str, str],
    total_value: float,
) -> dict[str, float]:
    if position is None or not len(position) or not total_value:
        return {}
    frame = position if isinstance(position, pd.DataFrame) else pd.DataFrame(position)
    volume = pd.to_numeric(frame["volume"], errors="coerce").fillna(0.0)
    close = pd.to_numeric(frame["close"], errors="coerce").fillna(0.0)
    weight = (volume * close) / float(total_value)
    out: dict[str, float] = {}
    for code, value in zip(frame["stockcode"].map(str), weight):
        stock = slip_index.get(code)
        instrument = stock if stock is not None else code
        sign = -1.0 if stock is not None else 1.0
        out[instrument] = out.get(instrument, 0.0) + sign * float(value)
    return out


def capacity_by_stock(
    slips: pd.DataFrame, close: dict[str, float], total_value: float
) -> dict[str, float]:
    if not total_value:
        return {}
    grouped = slips.groupby("instrument")["available"].sum()
    return {
        str(name): float(shares) * float(close.get(str(name), 0.0)) / total_value
        for name, shares in grouped.items()
    }
