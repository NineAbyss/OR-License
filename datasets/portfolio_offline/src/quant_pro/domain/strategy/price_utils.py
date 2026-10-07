
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


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
            "请检查 data/snapshot/factors/day/ 下是否有重叠的 parquet 文件。"
        )


class StrategyUtils:

    def __init__(self) -> None:
        from data_process import datas, load_factors

        logger.debug("初始化 quant_pro StrategyUtils")
        _ = load_factors(
            [
                "close",
                "open",
                "factor",
            ]
        )

        _dedup_datas_day(datas)

        self.none_open = round(datas.day.open / datas.day.factor.ffill().fillna(1), 2)
        self.none_close = round(datas.day.close / datas.day.factor.ffill().fillna(1), 2)
        self.post_factor = datas.day.factor.ffill().fillna(1)
        self.datas = datas
        logger.debug("quant_pro StrategyUtils 初始化完成")

    def get_none_open(self, dt: datetime, stockcode: str) -> float:
        val = self.none_open.loc[dt, stockcode]
        if isinstance(val, pd.Series):
            val = val.iloc[-1]
        return float(val)

    def get_none_close(self, dt: datetime, stockcode: str) -> float:
        val = self.none_close.loc[dt, stockcode]
        if isinstance(val, pd.Series):
            val = val.iloc[-1]
        return float(val)

    def batch_get_none_close(self, dt: datetime, stockcodes: list[str]) -> list[float]:
        result = self.none_close.loc[dt, stockcodes]
        if isinstance(result, pd.DataFrame):
            result = result.iloc[-1]
        return list(result.tolist())

    def get_post_factor(self, dt: datetime, stockcode: str) -> float | int:
        val = self.post_factor.loc[dt, stockcode]
        if isinstance(val, pd.Series):
            val = val.iloc[-1]
        return float(val)


_strategy_utils: StrategyUtils | None = None


def _ensure_loaded() -> StrategyUtils:
    global _strategy_utils
    if _strategy_utils is None:
        _strategy_utils = StrategyUtils()
    return _strategy_utils


def get_none_open(dt: datetime, stockcode: str) -> float:
    return _ensure_loaded().get_none_open(dt, stockcode)


def get_none_close(dt: datetime, stockcode: str) -> float:
    return _ensure_loaded().get_none_close(dt, stockcode)


def batch_get_none_close(dt: datetime, stockcodes: list[str]) -> list[float]:
    return _ensure_loaded().batch_get_none_close(dt, stockcodes)


def get_post_factor(dt: datetime, stockcode: str) -> float | int:
    return _ensure_loaded().get_post_factor(dt, stockcode)


__all__ = [
    "StrategyUtils",
    "get_none_open",
    "get_none_close",
    "batch_get_none_close",
    "get_post_factor",
]
