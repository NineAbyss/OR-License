
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from quant_pro.infrastructure.cache import TTLCache

_LOCAL_DATES: pd.DatetimeIndex | None = None


def _local_dates() -> pd.DatetimeIndex | None:
    global _LOCAL_DATES
    path = os.environ.get("QUANT_PRO_CALENDAR_FILE")
    if not path:
        return None
    if _LOCAL_DATES is None:
        frame = pd.read_csv(Path(path))
        column = "date" if "date" in frame.columns else frame.columns[0]
        _LOCAL_DATES = pd.DatetimeIndex(pd.to_datetime(frame[column]).dt.normalize()).sort_values()
    return _LOCAL_DATES


def get_next_trade_day(date: str, n: int = 1) -> str:
    dates = _local_dates()
    if dates is not None:
        candidates = dates[dates > pd.Timestamp(date).normalize()]
        if len(candidates) < n:
            raise IndexError(f"calendar has no {n}-th next trade day after {date}")
        return candidates[n - 1].strftime("%Y-%m-%d")
    from factor_client import get_next_trade_day as func
    return str(func(date, n))


def get_previous_trade_day(date: str, n: int = 1) -> str:
    dates = _local_dates()
    if dates is not None:
        candidates = dates[dates < pd.Timestamp(date).normalize()]
        if len(candidates) < n:
            raise IndexError(f"calendar has no {n}-th previous trade day before {date}")
        return candidates[-n].strftime("%Y-%m-%d")
    from factor_client import get_previous_trade_day as func
    return str(func(date, n))


class FactorClientCalendar:
    def __init__(self) -> None:
        self._cache = TTLCache(ttl=86_400.0, max_size=2000)

    def next_trade_day(self, date: str, n: int = 1) -> str:
        key = f"next:{date}:{n}"
        cached = self._cache.get(key)
        if cached is None:
            cached = get_next_trade_day(date, n)
            self._cache.set(key, cached)
        return str(cached)

    def previous_trade_day(self, date: str, n: int = 1) -> str:
        key = f"prev:{date}:{n}"
        cached = self._cache.get(key)
        if cached is None:
            cached = get_previous_trade_day(date, n)
            self._cache.set(key, cached)
        return str(cached)
