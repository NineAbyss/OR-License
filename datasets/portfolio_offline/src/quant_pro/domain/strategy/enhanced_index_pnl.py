
from __future__ import annotations

import logging
from typing import Literal, TypedDict

logger = logging.getLogger(__name__)

LongOnlyTradeType = Literal[
    "HOLD_LONG",
    "ADD_LONG",
    "REDUCE_LONG",
    "CLOSE_LONG",
    "PURE_OPEN_LONG",
    "NONE",
]


class DailyTradeSummary(TypedDict, total=False):

    net_buy_size: float
    net_buy_value: float
    net_sell_size: float
    net_sell_value: float
    opened_size: float


def classify_long_only_trade_type(
    *,
    prev_size: float,
    current_size: float,
    net_buy_size: float = 0.0,
    net_sell_size: float = 0.0,
) -> LongOnlyTradeType:
    if prev_size < 0 or current_size < 0:
        return "NONE"

    _ = net_buy_size, net_sell_size

    if prev_size == 0 and current_size == 0:
        return "NONE"
    if prev_size == 0 and current_size > 0:
        return "PURE_OPEN_LONG"
    if prev_size > 0 and current_size == 0:
        return "CLOSE_LONG"
    if current_size > prev_size:
        return "ADD_LONG"
    if current_size < prev_size:
        return "REDUCE_LONG"
    return "HOLD_LONG"


def calculate_long_only_daily_pnl(
    *,
    prev_size: float,
    prev_close: float | None,
    current_size: float,
    current_close: float,
    buy_value: float = 0.0,
    sell_value: float = 0.0,
) -> float:
    if prev_size < 0 or current_size < 0:
        logger.warning(
            "calculate_long_only_daily_pnl: negative size (prev=%.2f current=%.2f) "
            "— returning 0.0 (long-only contract violation)",
            prev_size,
            current_size,
        )
        return 0.0

    prev_mv = 0.0
    if prev_size != 0:
        if prev_close is None:
            prev_mv = 0.0
        else:
            prev_mv = float(prev_size) * float(prev_close)

    current_mv = float(current_size) * float(current_close)

    return current_mv - prev_mv - float(buy_value) + float(sell_value)


__all__ = [
    "DailyTradeSummary",
    "LongOnlyTradeType",
    "calculate_long_only_daily_pnl",
    "classify_long_only_trade_type",
]
