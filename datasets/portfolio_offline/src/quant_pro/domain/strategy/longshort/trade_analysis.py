
from __future__ import annotations


def analyze_trade_type(
    prev_size: float,
    current_size: float,
    net_buy_size: float,
    net_sell_size: float,
) -> dict[str, object]:
    result: dict[str, object] = {
        "trade_type": "NONE",
        "closed_size": 0,
        "opened_size": 0,
        "closed_direction": None,
        "opened_direction": None,
    }

    if net_buy_size == 0 and net_sell_size == 0:
        return result

    position_change = current_size - prev_size

    if prev_size == 0:
        if position_change > 0:
            result["trade_type"] = "PURE_OPEN_LONG"
            result["opened_size"] = position_change
            result["opened_direction"] = "LONG"
        elif position_change < 0:
            result["trade_type"] = "PURE_OPEN_SHORT"
            result["opened_size"] = abs(position_change)
            result["opened_direction"] = "SHORT"

    else:
        if prev_size > 0:
            if current_size > prev_size:
                result["trade_type"] = "ADD_LONG"
                result["opened_size"] = current_size - prev_size
                result["opened_direction"] = "LONG"
            elif current_size == 0:
                result["trade_type"] = "CLOSE_LONG"
                result["closed_size"] = prev_size
                result["closed_direction"] = "LONG"
            elif current_size > 0:
                result["trade_type"] = "REDUCE_LONG"
                result["closed_size"] = prev_size - current_size
                result["closed_direction"] = "LONG"
            else:
                result["trade_type"] = "REVERSE_LONG_TO_SHORT"
                result["closed_size"] = prev_size
                result["closed_direction"] = "LONG"
                result["opened_size"] = abs(current_size)
                result["opened_direction"] = "SHORT"
        else:
            if current_size < prev_size:
                result["trade_type"] = "ADD_SHORT"
                result["opened_size"] = abs(current_size - prev_size)
                result["opened_direction"] = "SHORT"
            elif current_size == 0:
                result["trade_type"] = "CLOSE_SHORT"
                result["closed_size"] = abs(prev_size)
                result["closed_direction"] = "SHORT"
            elif current_size < 0:
                result["trade_type"] = "REDUCE_SHORT"
                result["closed_size"] = abs(prev_size - current_size)
                result["closed_direction"] = "SHORT"
            else:
                result["trade_type"] = "REVERSE_SHORT_TO_LONG"
                result["closed_size"] = abs(prev_size)
                result["closed_direction"] = "SHORT"
                result["opened_size"] = current_size
                result["opened_direction"] = "LONG"

    return result
