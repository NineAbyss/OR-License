from __future__ import annotations
from typing import Any
import backtrader as bt
import pandas as pd


class IndexFutureCommissionInfo(bt.CommInfoBase):

    params = (
        ("commission", 0.00002),
        ("stocklike", False),
        ("commtype", bt.CommInfoBase.COMM_PERC),
        ("percabs", True),
        ("margin_rate", 0.12),
    )

    def get_margin(self, price: float) -> float:
        return float(price) * float(self.p.mult) * float(self.p.margin_rate)

    def _getcommission(self, size: float, price: float, pseudoexec: bool) -> float:
        del pseudoexec
        return (
            abs(float(size))
            * float(price)
            * float(self.p.mult)
            * float(self.p.commission)
        )


def add_future_feeds(
    cerebro: bt.Cerebro,
    frames: dict[str, pd.DataFrame],
    info: pd.DataFrame,
) -> None:

    metadata = info.drop_duplicates("instrument", keep="last").set_index("instrument")
    for instrument, frame in frames.items():
        if instrument not in metadata.index:
            raise ValueError(f"missing contract metadata for {instrument}")
        row = metadata.loc[instrument]
        multiplier = float(row["contract_multiplier"])
        margin_rate = float(row["margin_rate"])
        if multiplier <= 0 or margin_rate <= 0:
            raise ValueError(f"invalid multiplier/margin for {instrument}")
        cerebro.adddata(bt.feeds.PandasData(dataname=frame), name=instrument)
        cerebro.broker.addcommissioninfo(
            IndexFutureCommissionInfo(mult=multiplier, margin_rate=margin_rate),
            name=instrument,
        )


def validate_stock_factor_snapshot(
    market_data: Any,
    *,
    start_date: Any,
    end_date: Any,
) -> None:

    start = pd.Timestamp(start_date).normalize()
    end = pd.Timestamp(end_date).normalize()
    message = (
        "DailyHigh stock factor snapshot has no datas.day.close rows for "
        f"{start.strftime('%Y-%m-%d')} .. {end.strftime('%Y-%m-%d')}. "
        "Check QUANT_PRO_FACTOR_SNAPSHOT_DIR and ensure the snapshot covers "
        "the requested backtest window."
    )
    day = getattr(market_data, "day", None)
    close = getattr(day, "close", None)
    if not isinstance(close, pd.DataFrame) or close.empty:
        raise RuntimeError(message)
    try:
        dates = pd.DatetimeIndex(pd.to_datetime(close.index, errors="coerce")).normalize()
    except (TypeError, ValueError) as exc:
        raise RuntimeError(message) from exc
    in_window = (dates >= start) & (dates <= end)
    if not bool(in_window.any()) or close.loc[in_window].dropna(how="all").empty:
        raise RuntimeError(message)
