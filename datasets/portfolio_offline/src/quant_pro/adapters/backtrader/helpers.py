
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

import pandas as pd


def get_today_from_bt(datas: Any) -> datetime:
    return pd.to_datetime(datas[0].datetime.date(0))


def get_next_trade_day_from_bt(datas: Any) -> datetime:
    return pd.to_datetime(datas[0].datetime.date(1))


def get_positions(
    strategy: Any,
    size_filter: Callable[[int], bool] = lambda size: True,
) -> pd.Series:
    positions_data: list[float] = []
    positions_index: list[str] = []

    for d, p in strategy.getpositions().items():
        if size_filter(p.size):
            positions_data.append(p.size * strategy.getdatabyname(d._name).close[0])
            positions_index.append(d._name)

    return pd.Series(positions_data, index=positions_index)
