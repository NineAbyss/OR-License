
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from quant_pro.infrastructure.clickhouse.factor_data import FactorDataFetcher
from quant_pro.infrastructure.clickhouse.index_data import IndexDataFetcher
from quant_pro.infrastructure.clickhouse.market_data import MarketDataFetcher
from quant_pro.infrastructure.clickhouse.suspend_data import SuspendDataFetcher
from quant_pro.infrastructure.snapshot_store import SnapshotStore


class ClickHouseDataFetcher:
    def __init__(self, client: Any) -> None:
        self._market = MarketDataFetcher(client)
        self._factor = FactorDataFetcher(client)
        self._index = IndexDataFetcher(client)
        self._suspend = SuspendDataFetcher(client)
        self._snapshots = SnapshotStore("optimizer_fetcher_calls")
        self._period_daily_cache: dict[str, pd.DataFrame | None] = {}

    def _call(self, name: str, args: tuple[Any, ...], fn: Callable[[], Any]) -> Any:
        try:
            return self._snapshots.call(name, args, {}, fn)
        except FileNotFoundError:
            if os.environ.get("QUANT_PRO_SNAPSHOT_MODE", "").lower() != "replay":
                raise
            return fn()

    def get_close_price(self, date: str) -> pd.DataFrame:
        return self._call("get_close_price", (date,), lambda: self._market.get_close_price(date))

    def get_suspend_stocks(self, date: str) -> list[str]:
        return self._call("get_suspend_stocks", (date,), lambda: self._suspend.get_suspend_stocks(date))

    def get_pt_stock(self, date: str) -> pd.DataFrame:
        return self._call("get_pt_stock", (date,), lambda: self._market.get_pt_stock(date))

    def get_index_component(self, date: str, index_code: str) -> list[str]:
        return self._call(
            "get_index_component", (date, index_code), lambda: self._index.get_index_component(date, index_code)
        )

    def get_factor_covariance(self, date: str) -> pd.DataFrame:
        def load_covariance() -> pd.DataFrame:
            local_root = os.environ.get("QUANT_PRO_RISK_COVARIANCE_DIR")
            if not local_root:
                return self._factor.get_factor_covariance(date)
            result = pd.read_csv(Path(local_root) / date, index_col="index")
            result.index.name = None
            return result

        return self._call("get_factor_covariance", (date,), load_covariance)

    def get_factor_exposure(self, date: str) -> pd.DataFrame:
        return self._call("get_factor_exposure", (date,), lambda: self._factor.get_factor_exposure(date))

    def get_factor_exposure_today(self, date: str) -> pd.DataFrame:
        return self._call(
            "get_factor_exposure_today", (date,), lambda: self._factor.get_factor_exposure_today(date)
        )

    def get_specific_risk(self, date: str) -> pd.DataFrame:
        return self._call("get_specific_risk", (date,), lambda: self._factor.get_specific_risk(date))

    def get_period_close_turnover(self, start_date: str, end_date: str) -> pd.DataFrame:
        try:
            return self._call(
                "get_period_close_turnover",
                (start_date, end_date),
                lambda: self._market.get_period_close_turnover(start_date, end_date),
            )
        except FileNotFoundError:
            if os.environ.get("QUANT_PRO_SNAPSHOT_MODE", "").lower() != "replay":
                raise

            daily_frames: list[pd.DataFrame] = []
            for timestamp in pd.date_range(start_date, end_date, freq="D"):
                date = timestamp.strftime("%Y-%m-%d")
                if date not in self._period_daily_cache:
                    try:
                        frame = self._market.get_close_price(date)
                    except FileNotFoundError:
                        frame = None
                    if frame is None or frame.empty:
                        self._period_daily_cache[date] = None
                    else:
                        normalized = frame.copy()
                        normalized["datetime"] = normalized["datetime"].astype(str)
                        self._period_daily_cache[date] = normalized[
                            ["datetime", "instrument", "close", "total_turnover", "turnover"]
                        ]
                cached = self._period_daily_cache[date]
                if cached is not None:
                    daily_frames.append(cached)

            if not daily_frames:
                raise
            return pd.concat(daily_frames, ignore_index=True).sort_values(
                ["datetime", "instrument"]
            ).reset_index(drop=True)

    def get_open_price(self, date: str) -> pd.DataFrame:
        return self._call("get_open_price", (date,), lambda: self._market.get_open_price(date))

    def get_stock_return_time_series(self, start_date: str, end_date: str) -> pd.DataFrame:
        return self._call(
            "get_stock_return_time_series",
            (start_date, end_date),
            lambda: self._market.get_stock_return_time_series(start_date, end_date),
        )

    def get_benchmark_daily_return(self, start_date: str, end_date: str, bench: str) -> pd.DataFrame:
        return self._call(
            "get_benchmark_daily_return",
            (start_date, end_date, bench),
            lambda: self._market.get_benchmark_daily_return(start_date, end_date, bench),
        )

    def get_previous_trade_day(self, date: str, verbose: bool = False) -> str:
        return self._call(
            "get_previous_trade_day", (date, verbose), lambda: self._market.get_previous_trade_day(date, verbose)
        )

    def get_index_weight(self, date: str, bench: str) -> pd.DataFrame:
        return self._call("get_index_weight", (date, bench), lambda: self._index.get_index_weight(date, bench))

    def get_component_exposure(self, date: str) -> pd.DataFrame:
        return self._call("get_component_exposure", (date,), lambda: self._index.get_component_exposure(date))

    def cal_idx_return(self, date: str, idx_code: str) -> float:
        return self._call("cal_idx_return", (date, idx_code), lambda: self._market.cal_idx_return(date, idx_code))

    def get_factor_return(self, date: str) -> pd.DataFrame:
        return self._call("get_factor_return", (date,), lambda: self._factor.get_factor_return(date))

    def get_factor_return_time_series(self, start_date: str, end_date: str) -> pd.DataFrame:
        return self._call(
            "get_factor_return_time_series",
            (start_date, end_date),
            lambda: self._factor.get_factor_return_time_series(start_date, end_date),
        )
