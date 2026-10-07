
from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd


def should_rebalance(
    today: datetime,
    trade_dates_set: set[datetime],
) -> bool:
    if isinstance(today, pd.Timestamp):
        today = today.normalize()
    return today in trade_dates_set


def calculate_target_positions(
    weight_today: pd.Series,
    *,
    do_long: bool = True,
    do_short: bool = True,
    threshold: float = 1e-10,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    empty = pd.DataFrame(columns=["instrument", "weight"])

    if weight_today is None or weight_today.empty:
        return empty.copy(), empty.copy()

    wt = weight_today.reset_index()
    wt.columns = ["instrument", "weight"]

    if do_long:
        long_targets = wt[wt["weight"] > threshold].copy()
    else:
        long_targets = empty.copy()

    if do_short:
        short_targets = wt[wt["weight"] < -threshold].copy()
    else:
        short_targets = empty.copy()

    return long_targets, short_targets


def generate_order_list(
    long_targets: pd.DataFrame,
    short_targets: pd.DataFrame,
    current_positions: dict[str, int],
    close_prices: dict[str, float],
    total_value: float,
) -> list[dict[str, Any]]:
    orders: list[dict[str, Any]] = []

    target_instruments: set[str] = set()

    for _, row in long_targets.iterrows():
        inst = str(row["instrument"])
        weight = float(row["weight"])
        price = close_prices.get(inst, 0.0)

        target_instruments.add(inst)

        if price <= 0:
            continue

        target_money = total_value * weight
        orders.append(
            {
                "instrument": inst,
                "side": "buy",
                "target_weight": weight,
                "target_money": target_money,
                "close_price": price,
            }
        )

    for _, row in short_targets.iterrows():
        inst = str(row["instrument"])
        weight = float(row["weight"])
        price = close_prices.get(inst, 0.0)

        target_instruments.add(inst)

        if price <= 0:
            continue

        target_money = total_value * abs(weight)
        orders.append(
            {
                "instrument": inst,
                "side": "sell",
                "target_weight": weight,
                "target_money": target_money,
                "close_price": price,
            }
        )

    if current_positions:
        for inst, size in current_positions.items():
            inst_str = str(inst)
            if inst_str in target_instruments:
                continue
            if size == 0:
                continue
            price = close_prices.get(inst_str, 0.0)
            if price <= 0:
                continue

            side = "sell" if size > 0 else "buy"
            orders.append(
                {
                    "instrument": inst_str,
                    "side": side,
                    "target_weight": 0.0,
                    "target_money": 0.0,
                    "close_price": price,
                }
            )

    return orders
