
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from quant_pro.domain.strategy.volume_utils import refine_buy_vol, refine_sell_vol


@dataclass(frozen=True)
class SellOrderPlan:

    instrument: str
    action: str
    refined_vol: int
    none_close: float
    bt_vol: float
    money: float


@dataclass(frozen=True)
class BuyOrderPlan:

    instrument: str
    action: str
    refined_vol: int
    none_close: float
    bt_vol: float
    money: float


def generate_sell_orders(
    sell_todo: pd.DataFrame,
    position_sizes: dict[str, int],
    close_prices: dict[str, float],
    none_close_prices: dict[str, float],
) -> list[SellOrderPlan]:
    plans: list[SellOrderPlan] = []

    for _, row in sell_todo.iterrows():
        idx: str = row["instrument"]
        target_money = abs(row["update_money"])
        none_close: float = none_close_prices.get(idx, 0.0)

        if none_close == 0.0:
            plans.append(
                SellOrderPlan(
                    instrument=idx,
                    action="skip",
                    refined_vol=0,
                    none_close=0.0,
                    bt_vol=0.0,
                    money=0.0,
                )
            )
            continue

        target_vol = target_money / none_close
        posi_vol = position_sizes.get(idx, 0)

        is_close, is_valid, real_vol = refine_sell_vol(idx, target_vol, posi_vol)

        real_money = real_vol * none_close
        bt_close = close_prices.get(idx, none_close)

        weight = row.get("weight", 0.0)
        yester_weight = row.get("yester_weight", 0.0)
        should_close = (weight < 1e-9 and yester_weight != 0) or (real_vol == posi_vol)

        if should_close:
            plans.append(
                SellOrderPlan(
                    instrument=idx,
                    action="close",
                    refined_vol=posi_vol,
                    none_close=none_close,
                    bt_vol=0.0,
                    money=posi_vol * none_close,
                )
            )
        elif is_valid:
            bt_vol = real_money / bt_close if bt_close != 0.0 else 0.0
            plans.append(
                SellOrderPlan(
                    instrument=idx,
                    action="sell",
                    refined_vol=real_vol,
                    none_close=none_close,
                    bt_vol=bt_vol,
                    money=real_money,
                )
            )
        else:
            plans.append(
                SellOrderPlan(
                    instrument=idx,
                    action="skip",
                    refined_vol=real_vol,
                    none_close=none_close,
                    bt_vol=0.0,
                    money=real_money,
                )
            )

    return plans


def generate_buy_orders(
    buy_todo: pd.DataFrame,
    close_prices: dict[str, float],
    none_close_prices: dict[str, float],
) -> list[BuyOrderPlan]:
    plans: list[BuyOrderPlan] = []

    for _, row in buy_todo.iterrows():
        idx: str = row["instrument"]
        target_money: float = row["update_money"]
        none_close: float = none_close_prices.get(idx, 0.0)

        if none_close == 0.0:
            plans.append(
                BuyOrderPlan(
                    instrument=idx,
                    action="skip",
                    refined_vol=0,
                    none_close=0.0,
                    bt_vol=0.0,
                    money=0.0,
                )
            )
            continue

        target_vol = target_money / none_close
        ok, real_vol = refine_buy_vol(idx, target_vol)
        real_money = real_vol * none_close
        bt_close = close_prices.get(idx, none_close)

        if ok:
            bt_vol = real_money / bt_close if bt_close != 0.0 else 0.0
            plans.append(
                BuyOrderPlan(
                    instrument=idx,
                    action="buy",
                    refined_vol=real_vol,
                    none_close=none_close,
                    bt_vol=bt_vol,
                    money=real_money,
                )
            )
        else:
            plans.append(
                BuyOrderPlan(
                    instrument=idx,
                    action="skip",
                    refined_vol=real_vol,
                    none_close=none_close,
                    bt_vol=0.0,
                    money=real_money,
                )
            )

    return plans


def generate_init_buy_orders(
    todo: pd.DataFrame,
    total_value: float,
    close_prices: dict[str, float],
    none_close_prices: dict[str, float],
) -> list[BuyOrderPlan]:
    plans: list[BuyOrderPlan] = []

    for _, row in todo.iterrows():
        idx: str = row["instrument"]
        wei: float = row["weight"]

        if wei <= 0:
            continue

        none_close: float = none_close_prices.get(idx, 0.0)
        if none_close == 0.0:
            plans.append(
                BuyOrderPlan(
                    instrument=idx,
                    action="skip",
                    refined_vol=0,
                    none_close=0.0,
                    bt_vol=0.0,
                    money=0.0,
                )
            )
            continue

        target_money = total_value * wei
        target_vol = target_money / none_close
        ok, real_vol = refine_buy_vol(idx, target_vol)
        real_money = real_vol * none_close
        bt_close = close_prices.get(idx, none_close)

        if ok:
            bt_vol = real_money / bt_close if bt_close != 0.0 else 0.0
            plans.append(
                BuyOrderPlan(
                    instrument=idx,
                    action="buy",
                    refined_vol=real_vol,
                    none_close=none_close,
                    bt_vol=bt_vol,
                    money=real_money,
                )
            )
        else:
            plans.append(
                BuyOrderPlan(
                    instrument=idx,
                    action="skip",
                    refined_vol=real_vol,
                    none_close=none_close,
                    bt_vol=0.0,
                    money=real_money,
                )
            )

    return plans


def handle_delisted_stocks(
    weight_today: pd.Series,
    delisted_stocks: list[str],
) -> pd.Series:
    if not delisted_stocks:
        return weight_today
    return weight_today.drop(
        labels=[s for s in delisted_stocks if s in weight_today.index],
        errors="ignore",
    )
