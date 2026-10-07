
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import pandas as pd

from quant_pro.infrastructure.cache import TTLCache
from quant_pro.infrastructure.clickhouse import queries as Q

logger = logging.getLogger(__name__)


class MarketDataFetcher:

    def __init__(self, client: Any) -> None:
        self.client = client
        self._prev_day_cache = TTLCache(ttl=86_400.0, max_size=500)


    def get_close_price(self, date: str) -> pd.DataFrame:
        sql = Q.CLOSE_PRICE_QUERY.format(date=date)
        return self.client.query(sql)

    def get_close_price_time_series(self, start_date: str, end_date: str) -> pd.DataFrame:
        sql = Q.CLOSE_PRICE_TIME_SERIES_QUERY.format(start_date=start_date, end_date=end_date)
        result: pd.DataFrame = self.client.query(sql)
        return result[["datetime", "instrument", "close"]]


    def get_open_price(self, date: str | pd.Timestamp) -> pd.DataFrame:
        date_str = (
            date.split()[0] if isinstance(date, str) else pd.to_datetime(date).strftime("%Y-%m-%d")
        )
        sql = Q.OPEN_PRICE_QUERY.format(date=date_str)
        result: pd.DataFrame = self.client.query(sql)
        if result.empty:
            return pd.DataFrame(columns=["instrument", "open"])
        return result[["instrument", "open"]]

    def get_open_price_time_series(self, start_date: str, end_date: str) -> pd.DataFrame:
        sql = Q.OPEN_PRICE_TIME_SERIES_QUERY.format(start_date=start_date, end_date=end_date)
        result: pd.DataFrame = self.client.query(sql)
        return result[["datetime", "instrument", "open"]]


    def get_stock_return_time_series(self, start_date: str, end_date: str) -> pd.DataFrame:
        sql = Q.STOCK_RETURN_QUERY.format(start_date=start_date, end_date=end_date)
        result = self.client.query(sql)
        result["datetime"] = result["datetime"].astype(str)
        return result

    def get_stock_daily_returns(self, date: str) -> pd.Series[float]:
        try:
            prev = self.get_previous_trade_day(date)
            today_prices = self.get_close_price(date)
            prev_prices = self.get_close_price(prev)

            today_prices["close"] = today_prices["close"] / today_prices["factor"]
            prev_prices["close"] = prev_prices["close"] / prev_prices["factor"]

            today_s = today_prices.set_index("instrument")["close"]
            prev_s = prev_prices.set_index("instrument")["close"]
            common = today_s.index.intersection(prev_s.index)
            if len(common) == 0:
                return pd.Series(dtype=float)
            return (today_s.loc[common] - prev_s.loc[common]) / prev_s.loc[common]
        except Exception:
            return pd.Series(dtype=float)


    def get_stock_turnover_time_series(self, start_date: str, end_date: str) -> pd.DataFrame:
        sql = Q.STOCK_TURNOVER_QUERY.format(start_date=start_date, end_date=end_date)
        result: pd.DataFrame = self.client.query(sql)
        result["datetime"] = result["datetime"].astype(str)
        return result

    def get_period_close_turnover(self, start_date: str, end_date: str) -> pd.DataFrame:
        sql = Q.PERIOD_CLOSE_TURNOVER_QUERY.format(start_date=start_date, end_date=end_date)
        result: pd.DataFrame = self.client.query(sql)
        result["datetime"] = result["datetime"].astype(str)
        return result


    def get_previous_trade_day(self, date: str, verbose: bool = False) -> str:
        cache_key = f"prev_trade_day:{date}"
        cached_result = self._prev_day_cache.get(cache_key)
        if cached_result is not None:
            if verbose:
                logger.info("[查询前一交易日] 缓存命中: %s → %s", date, cached_result)
            return str(cached_result)

        if verbose:
            logger.info("[查询前一交易日] 输入日期: %s", date)
        try:
            date_str = pd.to_datetime(date).strftime("%Y-%m-%d")
            sql = Q.PREVIOUS_TRADE_DAY_QUERY.format(date=date_str)
            df = self.client.query(sql)
            if not df.empty and "prev_date" in df.columns and pd.notna(df.loc[0, "prev_date"]):
                prev: str = pd.to_datetime(df.loc[0, "prev_date"]).strftime("%Y-%m-%d")
                if verbose:
                    logger.info("  ✓ 找到前一交易日: %s", prev)
                self._prev_day_cache.set(cache_key, prev)
                return prev
        except Exception as e:
            if verbose:
                logger.warning("  ✗ 查询异常: %s，使用回退逻辑", e)

        fallback: str = (pd.to_datetime(date) - timedelta(days=1)).strftime("%Y-%m-%d")
        if verbose:
            logger.warning("  ⚠ 回退到日历日-1: %s", fallback)
        self._prev_day_cache.set(cache_key, fallback)
        return fallback


    _IDX_RETURN_WALKBACK_LIMIT = 8

    def cal_idx_return(self, date: str, idx_code: str) -> float:
        sql = Q.INDEX_CLOSE_WALKBACK_QUERY.format(
            date=date, idx_code=idx_code, limit=self._IDX_RETURN_WALKBACK_LIMIT
        )
        df = self.client.query(sql)
        if df is None or len(df) == 0 or "datetime" not in df.columns:
            raise ValueError(
                f"cal_idx_return: index '{idx_code}' has fewer than 2 distinct "
                f"quote dates on-or-before '{date}' (found 0); cannot compute a "
                f"1-day return. Check the index quote table for missing rows."
            )
        dedup = df.dropna(subset=["datetime"]).copy()
        dedup["datetime"] = pd.to_datetime(dedup["datetime"]).dt.strftime("%Y-%m-%d")
        dedup = dedup.drop_duplicates(subset=["datetime"], keep="last")
        dedup = dedup.sort_values("datetime")
        if len(dedup) < 2:
            raise ValueError(
                f"cal_idx_return: index '{idx_code}' has fewer than 2 distinct "
                f"quote dates on-or-before '{date}' (found {len(dedup)}); cannot "
                f"compute a 1-day return. Check the index quote table for "
                f"missing rows."
            )
        closes = dedup["close"].to_numpy()
        prev_close = float(closes[-2])
        today_close = float(closes[-1])
        return float(today_close / prev_close - 1)


    def get_pt_stock(self, date: str) -> pd.DataFrame:
        sql = Q.PT_STOCK_QUERY.format(date=date)
        result: pd.DataFrame = self.client.query(sql)
        result = result[["datetime", "instrument"]]
        result = result.sort_values("datetime", ascending=True)
        result.reset_index(drop=True, inplace=True)
        return result

    def get_basis_info(self, date: str) -> pd.DataFrame:
        sql = Q.BASIS_INFO_QUERY.format(date=date)
        result: pd.DataFrame = self.client.query(sql)
        result = result.sort_values("datetime", ascending=True)
        result.reset_index(drop=True, inplace=True)
        return result

    def get_dom_future(self, date: str) -> pd.DataFrame:
        sql = Q.DOM_FUTURE_QUERY.format(date=date)
        result: pd.DataFrame = self.client.query(sql)
        result = result.sort_values("datetime", ascending=True)
        result.reset_index(drop=True, inplace=True)
        return result


    def calculate_benchmark_stock_returns(
        self,
        date: str,
        benchmark_code: str,
        index_fetcher: Any = None,
    ) -> pd.Series[float]:
        try:
            _idx: Any = index_fetcher if index_fetcher is not None else self
            benchmark_weights = _idx.get_index_weight(date, benchmark_code)
            if benchmark_weights.empty:
                return pd.Series(dtype=float)
        except Exception:
            return pd.Series(dtype=float)

        try:
            prev = self.get_previous_trade_day(date)
            today_raw = self.get_close_price(date)
            prev_raw = self.get_close_price(prev)
            today_raw["close"] = today_raw["close"] / today_raw["factor"]
            prev_raw["close"] = prev_raw["close"] / prev_raw["factor"]

            today_prices = today_raw.set_index("instrument")["close"]
            prev_prices = prev_raw.set_index("instrument")["close"]
            stocks = benchmark_weights["instrument"].tolist()
            today_prices = today_prices.loc[today_prices.index.intersection(stocks)]
            prev_prices = prev_prices.loc[prev_prices.index.intersection(stocks)]
            common = today_prices.index.intersection(prev_prices.index)
            if len(common) == 0:
                return pd.Series(dtype=float)
            return (today_prices.loc[common] - prev_prices.loc[common]) / prev_prices.loc[common]
        except Exception:
            return pd.Series(dtype=float)

    def calculate_benchmark_stock_returns_time_series(
        self,
        start_date: str,
        end_date: str,
        benchmark_code: str,
        index_fetcher: Any = None,
    ) -> pd.DataFrame:
        _idx: Any = index_fetcher if index_fetcher is not None else self
        try:
            benchmark_weights = _idx.get_index_weight_time_series(
                start_date, end_date, benchmark_code
            )
            all_instruments: list[str] = benchmark_weights["instrument"].unique().tolist()
            if benchmark_weights.empty:
                return pd.DataFrame()
        except Exception:
            return pd.DataFrame()

        try:
            first_day = self.get_previous_trade_day(start_date)
            close_prices = self.get_close_price_time_series(first_day, end_date)
            if close_prices.empty:
                return pd.DataFrame()
            close_prices = close_prices[close_prices["instrument"].isin(all_instruments)]
            close_prices["returns"] = close_prices.groupby("instrument")["close"].transform(
                lambda x: x / x.shift(1) - 1
            )
            close_prices["datetime"] = pd.to_datetime(close_prices["datetime"]).dt.strftime(
                "%Y-%m-%d"
            )
            daily_returns = close_prices.pivot(
                index="datetime", columns="instrument", values="returns"
            )
            daily_returns = daily_returns.reindex(columns=all_instruments).sort_index().iloc[1:]
            daily_returns = daily_returns.ffill().bfill()
            return daily_returns
        except Exception:
            return pd.DataFrame()

    def get_benchmark_daily_return(
        self,
        date: str,
        benchmark_code: str,
        index_fetcher: Any = None,
    ) -> float:
        _idx: Any = index_fetcher if index_fetcher is not None else self
        try:
            benchmark_weights = _idx.get_index_weight(date, benchmark_code)
            if benchmark_weights.empty:
                return 0.0
            benchmark_returns = self.calculate_benchmark_stock_returns(
                date, benchmark_code, index_fetcher=_idx
            )
            if benchmark_returns.empty:
                return 0.0
            stocks = list(set(benchmark_weights["instrument"]) & set(benchmark_returns.index))
            if not stocks:
                return 0.0
            total_weight = 0.0
            weighted_return = 0.0
            for stock in stocks:
                w = benchmark_weights.loc[benchmark_weights["instrument"] == stock, "weight"].iloc[
                    0
                ]
                weighted_return += w * benchmark_returns[stock]
                total_weight += w
            return float(weighted_return / total_weight) if total_weight > 0 else 0.0
        except Exception:
            return 0.0


    def get_stock_return(self, date: str) -> pd.DataFrame:
        sql = Q.STOCK_RETURN_SINGLE_QUERY.format(date=date)
        return self.client.query(sql).drop(columns="datetime")

    def get_specific_return(self, date: str) -> pd.DataFrame:
        sql = Q.SPECIFIC_RETURN_QUERY.format(date=date)
        return self.client.query(sql).drop(columns="datetime")

    def get_specific_return_time_series(self, start_date: str, end_date: str) -> pd.DataFrame:
        sql = Q.SPECIFIC_RETURN_TIME_SERIES_QUERY.format(start_date=start_date, end_date=end_date)
        result: pd.DataFrame = self.client.query(sql)
        result["datetime"] = result["datetime"].astype(str)
        return result

    def get_stock_size(self, date: str) -> pd.DataFrame:
        sql = Q.STOCK_SIZE_QUERY.format(date=date)
        return self.client.query(sql)

    def get_value_pb_time_series(self, start_date: str, end_date: str) -> pd.DataFrame:
        sql = Q.VALUE_PB_TIME_SERIES_QUERY.format(start_date=start_date, end_date=end_date)
        result: pd.DataFrame = self.client.query(sql)
        result["datetime"] = result["datetime"].astype(str)
        return result

    def get_value_sp_ttm_time_series(self, start_date: str, end_date: str) -> pd.DataFrame:
        sql = Q.VALUE_SP_TTM_TIME_SERIES_QUERY.format(start_date=start_date, end_date=end_date)
        result: pd.DataFrame = self.client.query(sql)
        result["datetime"] = result["datetime"].astype(str)
        return result

    def get_west_ep_FTM_time_series(self, start_date: str, end_date: str) -> pd.DataFrame:
        sql = Q.WEST_EP_FTM_TIME_SERIES_QUERY.format(start_date=start_date, end_date=end_date)
        result: pd.DataFrame = self.client.query(sql)
        result["datetime"] = result["datetime"].astype(str)
        return result
