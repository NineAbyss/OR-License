
from __future__ import annotations

from typing import Any


def calculate_trade_sequence_daily_pnl(
    *,
    prev_size: float,
    prev_avg_price: float,
    prev_close: float | None,
    current_size: float,
    current_avg_price: float,
    current_price: float,
    trades: list[dict[str, Any]] | None = None,
) -> dict[str, float]:
    if trades is None:
        trades = []

    lots: list[dict[str, float | str]] = []
    if prev_size > 0:
        lots.append(
            {
                "side": "long",
                "size": float(prev_size),
                "avg_price": float(prev_avg_price),
                "prev_close": float(prev_close if prev_close is not None else prev_avg_price),
                "source": "old",
            }
        )
    elif prev_size < 0:
        lots.append(
            {
                "side": "short",
                "size": abs(float(prev_size)),
                "avg_price": float(prev_avg_price),
                "prev_close": float(prev_close if prev_close is not None else prev_avg_price),
                "source": "old",
            }
        )

    realized_pnl_today = 0.0
    realized_pnl_full = 0.0

    def _close_lots(side: str, qty: float, price: float) -> float:
        nonlocal realized_pnl_today, realized_pnl_full
        remaining = qty
        idx = 0
        while remaining > 1e-12 and idx < len(lots):
            lot = lots[idx]
            if lot["side"] != side or float(lot["size"]) <= 1e-12:
                idx += 1
                continue
            closed = min(remaining, float(lot["size"]))
            avg = float(lot["avg_price"])
            ref = float(lot["prev_close"] if lot["source"] == "old" else lot["avg_price"])
            if side == "long":
                realized_pnl_full += (price - avg) * closed
                realized_pnl_today += (price - ref) * closed
            else:
                realized_pnl_full += (avg - price) * closed
                realized_pnl_today += (ref - price) * closed
            lot["size"] = float(lot["size"]) - closed
            remaining -= closed
            if float(lot["size"]) <= 1e-12:
                lots.pop(idx)
            else:
                idx += 1
        return remaining

    for trade in trades:
        action = str(trade.get("action", "")).lower()
        if action not in {"buy", "sell"}:
            continue
        qty = abs(float(trade.get("size", 0.0) or 0.0))
        price = float(trade.get("price", 0.0) or 0.0)
        if qty <= 1e-12 or price <= 0:
            continue

        if action == "buy":
            remaining = _close_lots("short", qty, price)
            if remaining > 1e-12:
                lots.append(
                    {
                        "side": "long",
                        "size": remaining,
                        "avg_price": price,
                        "prev_close": price,
                        "source": "new",
                    }
                )
        else:
            remaining = _close_lots("long", qty, price)
            if remaining > 1e-12:
                lots.append(
                    {
                        "side": "short",
                        "size": remaining,
                        "avg_price": price,
                        "prev_close": price,
                        "source": "new",
                    }
                )

    continuing_pnl = 0.0
    new_position_pnl = 0.0
    for lot in lots:
        qty = float(lot["size"])
        avg = float(lot["avg_price"])
        ref = float(lot["prev_close"])
        if qty <= 1e-12:
            continue
        if lot["source"] == "old":
            if lot["side"] == "long":
                continuing_pnl += (current_price - ref) * qty
            else:
                continuing_pnl += (ref - current_price) * qty
        else:
            if lot["side"] == "long":
                new_position_pnl += (current_price - avg) * qty
            else:
                new_position_pnl += (avg - current_price) * qty

    if not trades and prev_size == 0 and abs(current_size) > 1e-12:
        new_position_pnl = (current_price - current_avg_price) * current_size

    return {
        "continuing_pnl": continuing_pnl,
        "new_position_pnl": new_position_pnl,
        "realized_pnl_today": realized_pnl_today,
        "realized_pnl": realized_pnl_full,
        "daily_pnl": continuing_pnl + new_position_pnl + realized_pnl_today,
    }


def calculate_holding_daily_pnl(
    *,
    prev_size: float,
    prev_close: float | None,
    position_size: float,
    position_price: float,
    current_price: float,
    trade_type: str,
    trade_summary: dict[str, Any] | None = None,
) -> tuple[float, float]:
    continuing_pnl = 0.0
    new_position_pnl = 0.0

    if trade_summary is None:
        trade_summary = {}

    if trade_type in ("ADD_LONG", "ADD_SHORT"):
        if prev_close is not None:
            continuing_pnl = (current_price - prev_close) * prev_size

        opened_size = trade_summary.get("opened_size", 0)
        if opened_size > 0:
            if trade_type == "ADD_LONG":
                avg_open_price = trade_summary.get("net_buy_value", 0) / max(
                    trade_summary.get("net_buy_size", 1), 1
                )
                new_position_pnl = (current_price - avg_open_price) * opened_size
            else:
                avg_open_price = trade_summary.get("net_sell_value", 0) / max(
                    trade_summary.get("net_sell_size", 1), 1
                )
                new_position_pnl = (avg_open_price - current_price) * opened_size

    elif trade_type in ("REDUCE_LONG", "REDUCE_SHORT"):
        if prev_close is not None:
            continuing_pnl = (current_price - prev_close) * position_size

    elif trade_type in ("REVERSE_LONG_TO_SHORT", "REVERSE_SHORT_TO_LONG"):
        new_position_pnl = (current_price - position_price) * position_size

    elif trade_type in ("PURE_OPEN_LONG", "PURE_OPEN_SHORT"):
        new_position_pnl = (current_price - position_price) * position_size

    else:
        if prev_size != 0 and prev_close is not None:
            continuing_pnl = (current_price - prev_close) * position_size
        else:
            new_position_pnl = (current_price - position_price) * position_size

    return continuing_pnl, new_position_pnl


def finalize_stock_summary(
    stock_summary: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    for _stock_code, summary in stock_summary.items():
        summary["net_position_size"] = (
            summary["long_position_size"] + summary["short_position_size"]
        )
        summary["net_market_value"] = summary["long_market_value"] + summary["short_market_value"]

        prev_position_size: float = summary.get("prev_position_size", 0)
        summary["long_position_change"] = summary["long_position_size"] - (
            prev_position_size if prev_position_size > 0 else 0
        )
        summary["short_position_change"] = summary["short_position_size"] - (
            prev_position_size if prev_position_size < 0 else 0
        )
        summary["net_position_change"] = summary["net_position_size"] - prev_position_size

        summary["total_daily_pnl"] = summary["long_daily_pnl"] + summary["short_daily_pnl"]

        summary["total_daily_return"] = 0.0

    return stock_summary
