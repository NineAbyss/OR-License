
from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

FUTURE_PREFIX = "IM"


def _future_get_margin_rate(market_data: Any, future_name: str) -> float:

    margin_rate = market_data.future_day.margin_rate[future_name]
    if hasattr(margin_rate, "iloc"):
        return float(margin_rate.iloc[0])
    return float(margin_rate)



ENHANCED_INDEX_FACTORS: list[str] = [
    "close",
    "open",
    "high",
    "low",
    "volume",
    "total_turnover",
    "open_up_limit",
    "open_down_limit",
    "factor",
    "reach_limit_up_in_5",
    "reach_limit_down_in_5",
    (
        "=:temp_factors.temp_quant_stock_day_vop_liqu_liquidity_zhxiao_di"
        ":datetime,instrument,rank_cap,rank_vol,rank_amount,rank_turnover,rank_amihud"
    ),
    (
        "=:temp_factors.temp_quant_stock_lvl2_vop_liqu_liquidity_zhxiao_di"
        ":datetime,instrument,rank_bid_ask_spread_01,rank_bid_ask_spread_05,"
        "rank_bid_ask_spread_10,rank_bid_ask_spread_all,rank_sellvol,"
        "rank_buyvol,rank_sellcount,rank_buycount,rank_allcount"
    ),
    (
        "=:temp_factors.temp_quant_stock_multi_alt_news_risk_event_accepted_v1_benchmark_di"
        ":datetime,instrument,is_event_accepted_v2"
    ),
]

LONGSHORT_FACTORS: list[str] = [
    "close",
    "open",
    "high",
    "low",
    "volume",
    "total_turnover",
]


_cached_market_data: Any | None = None


def _dedup_datas_day(datas: Any) -> None:
    day = getattr(datas, "day", None)
    if day is None:
        return
    if not hasattr(day, "keys"):
        return
    changed = False
    for key in list(day.keys()):
        df = day[key]
        if hasattr(df, "index") and df.index.duplicated().any():
            day[key] = df[~df.index.duplicated(keep="last")]
            changed = True
    if changed:
        logger.warning(
            "data_process.datas.day 存在重复日期索引，已自动去重。"
            "请检查数据目录下是否有重叠的 parquet 文件。"
        )


def lazy_load_market_data(
    limit_start: str | datetime | None = None,
    limit_end: str | datetime | None = None,
    factors: Sequence[str] | None = None,
    *,
    force_reload: bool = False,
) -> Any:
    global _cached_market_data

    if _cached_market_data is not None and not force_reload:
        return _cached_market_data

    logger.info("开始加载 market data ...")

    _start: str | None = None
    _end: str | None = None
    if limit_start is not None:
        _start = pd.to_datetime(limit_start).strftime("%Y-%m-%d")
    if limit_end is not None:
        _end = pd.to_datetime(limit_end).strftime("%Y-%m-%d")

    if factors is None:
        factors = ENHANCED_INDEX_FACTORS

    from data_process import align_datas, datas, load_factors

    _ = load_factors(list(factors), limit_start=_start, limit_end=_end)

    _dedup_datas_day(datas)

    align_datas("close", dataset=datas.day, inplace=True)

    _cached_market_data = datas
    logger.info("market data 加载完成")
    return datas


def reset_market_data_cache() -> None:
    global _cached_market_data
    _cached_market_data = None



_REQUIRE_COLUMNS: list[str] = [
    "open",
    "high",
    "low",
    "close",
    "volume",
    "openinterest",
]


def init_cerebro_data(
    instruments: Sequence[str],
    start_date: str | datetime | pd.Timestamp,
    end_date: str | datetime | pd.Timestamp,
    market_data: Any,
    *,
    broker_cls: type | None = None,
    cash: float = 10_000_000.0,
    commission: float = 0.045,
    slippage_perc: float = 0.0003,
    maxcpus: int = 4,
    configure_futures: bool = False,
) -> Any:
    import backtrader as bt

    require_columns = _REQUIRE_COLUMNS

    date_range = pd.date_range(start_date, end_date, freq="D")
    available_dates = market_data.day.close.index
    valid_dates = date_range.intersection(available_dates)
    df_exchange_calendar = pd.DataFrame(1, index=valid_dates, columns=require_columns)

    cerebro = bt.Cerebro(
        maxcpus=maxcpus,
        preload=True,
        runonce=True,
        optdatas=True,
        optreturn=True,
        stdstats=False,
    )

    if broker_cls is not None:
        cerebro.broker = broker_cls()

    valid_instruments: list[str] = []
    for inst in instruments:
        if inst in market_data.day.close.columns:
            if not market_data.day.close.loc[start_date:end_date, inst].isna().all():
                valid_instruments.append(inst)

    datafeed = bt.feeds.PandasData(
        dataname=df_exchange_calendar, fromdate=start_date, todate=end_date
    )
    cerebro.adddata(datafeed, name="exchange_calendar")

    data_price: dict[str, pd.DataFrame] = {}
    for c in require_columns:
        if market_data.day.get(c) is not None:
            data_price[c] = (
                market_data.day.get(c)
                .loc[start_date:end_date, valid_instruments]
                .copy()
            )

    close_data = data_price["close"]
    ffill_close = close_data.ffill().shift(1).fillna(1)
    for c in ["high", "low", "close", "open"]:
        data_price[c] = data_price[c].where(data_price[c].notna(), ffill_close)

    available_columns = [c for c in require_columns if c in data_price]
    data_price_stacked = pd.concat(
        [data_price[c].stack() for c in available_columns],
        axis=1,
        keys=available_columns,
    )

    for col in ["volume", "openinterest"]:
        if col not in data_price_stacked.columns:
            data_price_stacked[col] = 0
        else:
            data_price_stacked[col] = data_price_stacked[col].fillna(0)

    data_price_stacked = data_price_stacked.reindex(require_columns, axis=1, fill_value=0)
    data_price_stacked.index.set_names(["datetime", "instrument"], inplace=True)

    for i in valid_instruments:
        instrument_data = data_price_stacked.xs(i, level="instrument")
        datafeed = bt.feeds.PandasData(dataname=instrument_data)
        cerebro.adddata(datafeed, name=i)

    cerebro.broker.set_shortcash(False)
    cerebro.broker.setcash(cash)
    cerebro.broker.addcommissioninfo(bt.CommInfoBase(commission=commission))
    cerebro.broker.set_slippage_perc(perc=slippage_perc)

    if configure_futures:
        for i in market_data.future_day.margin_rate.columns:
            if FUTURE_PREFIX in i and int(i[2]) <= 2:
                margin = _future_get_margin_rate(market_data, i)
                cerebro.broker.setcommission(
                    commission=0.00002,
                    commtype=0,
                    stocklike=False,
                    automargin=margin,
                    name=i,
                )

    return cerebro
