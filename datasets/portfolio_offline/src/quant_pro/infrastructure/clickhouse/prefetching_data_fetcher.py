
from __future__ import annotations

import atexit
import logging
import sys
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from quant_pro.infrastructure.calendar import factor_client_adapter

logger = logging.getLogger(__name__)

_SHAPED_TS_MEMO_MAXSIZE = 2


@dataclass
class PrefetchScope:

    range_start: str
    range_end: str
    exact_dates: list[str] = field(default_factory=list)
    benchmarks: list[str] = field(default_factory=list)
    factor_exposure_ts_raw_start: str | None = None


class PrefetchingDataFetcher:

    def __init__(self, delegate: Any) -> None:
        self._delegate = delegate
        self._scope: PrefetchScope | None = None
        self._exact_date_set: set[str] = set()
        self._raw_close_price: dict[str, pd.DataFrame] = {}
        self._raw_factor_exposure: dict[str, pd.DataFrame] = {}
        self._raw_factor_exposure_today: dict[str, pd.DataFrame] = {}
        self._raw_specific_risk: dict[str, pd.DataFrame] = {}
        self._raw_index_weight: dict[tuple[str, str], pd.DataFrame] = {}
        self._raw_period_close_turnover: pd.DataFrame | None = None
        self._raw_specific_return_ts: pd.DataFrame | None = None
        self._raw_factor_return_ts: pd.DataFrame | None = None
        self._raw_factor_exposure_ts: pd.DataFrame | None = None
        self._shaped_factor_exposure_ts: OrderedDict[tuple[str, str], pd.DataFrame] = OrderedDict()
        self._stats: dict[str, dict[str, int]] = {}
        self._loaded_rows: int = 0
        self._atexit_registered: bool = False


    @property
    def _market(self) -> Any:
        return self._delegate._market

    @property
    def _factor(self) -> Any:
        return self._delegate._factor

    @property
    def _index(self) -> Any:
        return self._delegate._index

    @property
    def _suspend(self) -> Any:
        return self._delegate._suspend

    def __getattr__(self, name: str) -> Any:
        if name == "_delegate":
            raise AttributeError(name)
        return getattr(self._delegate, name)


    def _reset_caches(self) -> None:
        self._raw_close_price = {}
        self._raw_factor_exposure = {}
        self._raw_factor_exposure_today = {}
        self._raw_specific_risk = {}
        self._raw_index_weight = {}
        self._raw_period_close_turnover = None
        self._raw_specific_return_ts = None
        self._raw_factor_return_ts = None
        self._raw_factor_exposure_ts = None
        self._shaped_factor_exposure_ts = OrderedDict()
        self._loaded_rows = 0

    def prefetch(self, scope: PrefetchScope) -> None:
        self._reset_caches()
        self._scope = scope
        self._exact_date_set = {_date_only(d) for d in scope.exact_dates}
        client = self._delegate._market.client

        from quant_pro.infrastructure.clickhouse import queries as Q

        self._raw_period_close_turnover = self._safe_query(
            client,
            Q.PERIOD_CLOSE_TURNOVER_QUERY.format(
                start_date=scope.range_start, end_date=scope.range_end
            ),
            label="period_close_turnover",
        )
        self._raw_specific_return_ts = self._safe_query(
            client,
            Q.SPECIFIC_RETURN_TIME_SERIES_QUERY.format(
                start_date=scope.range_start, end_date=scope.range_end
            ),
            label="specific_return_ts",
        )
        self._raw_factor_return_ts = self._safe_query(
            client,
            Q.FACTOR_RETURN_TIME_SERIES_QUERY.format(
                start_date=scope.range_start, end_date=scope.range_end
            ),
            label="factor_return_ts",
        )

        ts_start = scope.factor_exposure_ts_raw_start or scope.range_start
        self._raw_factor_exposure_ts = self._safe_query(
            client,
            Q.FACTOR_EXPOSURE_TIME_SERIES_QUERY.format(
                start_date=ts_start, end_date=scope.range_end
            ),
            label="factor_exposure_ts",
        )

        for date in scope.exact_dates:
            cp = self._safe_query(
                client, Q.CLOSE_PRICE_QUERY.format(date=date), label="close_price"
            )
            if cp is not None:
                self._raw_close_price[date] = cp

            fe_today = self._safe_query(
                client, Q.FACTOR_EXPOSURE_QUERY.format(date=date), label="factor_exposure_today"
            )
            if fe_today is not None:
                self._raw_factor_exposure_today[date] = fe_today
                self._raw_factor_exposure[date] = fe_today

            sr = self._safe_query(
                client, Q.SPECIFIC_RISK_QUERY.format(date=date), label="specific_risk"
            )
            if sr is not None:
                self._raw_specific_risk[date] = sr

            for bench in scope.benchmarks:
                iw = self._safe_query(
                    client,
                    Q.INDEX_WEIGHT_QUERY.format(date=date, bench=bench),
                    label="index_weight",
                )
                if iw is not None:
                    self._raw_index_weight[(date, bench)] = iw

        if self._loaded_rows <= 0:
            logger.warning(
                "PrefetchingDataFetcher: prefetch loaded 0 rows for scope [%s..%s] "
                "(all queries failed/empty) -- marker suppressed; every read will delegate",
                scope.range_start,
                scope.range_end,
            )
            return
        logger.info(
            "PrefetchingDataFetcher: prefetched scope [%s..%s] exact_dates=%d benchmarks=%s "
            "loaded_rows=%d",
            scope.range_start,
            scope.range_end,
            len(scope.exact_dates),
            scope.benchmarks,
            self._loaded_rows,
        )
        if not self._atexit_registered:
            atexit.register(self._log_final_stats)
            self._atexit_registered = True

    def _safe_query(self, client: Any, sql: str, *, label: str) -> pd.DataFrame | None:
        try:
            df = client.query(sql)
        except Exception as exc:
            logger.warning(
                "PrefetchingDataFetcher: prefetch %s failed (%s); will delegate", label, exc
            )
            return None
        if df is not None:
            try:
                self._loaded_rows += int(len(df))
            except TypeError:
                pass
        return df

    def _record(self, method: str, hit: bool) -> None:
        bucket = self._stats.setdefault(method, {"hit": 0, "miss": 0})
        bucket["hit" if hit else "miss"] += 1

    @property
    def cache_stats(self) -> dict[str, dict[str, int]]:
        return {m: dict(v) for m, v in self._stats.items()}

    @property
    def total_hits(self) -> int:
        return sum(v.get("hit", 0) for v in self._stats.values())

    @property
    def total_misses(self) -> int:
        return sum(v.get("miss", 0) for v in self._stats.values())

    @property
    def loaded_rows(self) -> int:
        return self._loaded_rows

    def _log_final_stats(self) -> None:
        line = (
            f"PrefetchingDataFetcher: cache stats hits={self.total_hits} "
            f"misses={self.total_misses} loaded_rows={self._loaded_rows}"
        )
        try:
            stream = sys.stderr
            if stream is not None and not getattr(stream, "closed", False):
                stream.write(line + "\n")
                stream.flush()
        except (ValueError, OSError):
            pass


    def get_close_price(self, date: str) -> pd.DataFrame:
        raw = self._raw_close_price.get(date) if self._in_scope_exact(date) else None
        if raw is None:
            self._record("get_close_price", hit=False)
            return self._delegate.get_close_price(date)
        self._record("get_close_price", hit=True)
        return raw.copy(deep=True)

    def get_period_close_turnover(self, start_date: str, end_date: str) -> pd.DataFrame:
        if not self._range_covered(start_date, end_date) or self._raw_period_close_turnover is None:
            self._record("get_period_close_turnover", hit=False)
            return self._delegate.get_period_close_turnover(start_date, end_date)
        self._record("get_period_close_turnover", hit=True)
        df = self._raw_period_close_turnover
        sliced = _inclusive_date_slice(df, start_date, end_date, date_col="datetime")
        out = _deterministic_order(sliced.copy(deep=True), date_col="datetime")
        out["datetime"] = out["datetime"].astype(str)
        return out

    def get_specific_return_time_series(self, start_date: str, end_date: str) -> pd.DataFrame:
        if not self._range_covered(start_date, end_date) or self._raw_specific_return_ts is None:
            self._record("get_specific_return_time_series", hit=False)
            return self._delegate._market.get_specific_return_time_series(start_date, end_date)
        self._record("get_specific_return_time_series", hit=True)
        sliced = _inclusive_date_slice(
            self._raw_specific_return_ts, start_date, end_date, date_col="datetime"
        )
        out = _deterministic_order(sliced.copy(deep=True), date_col="datetime")
        out["datetime"] = out["datetime"].astype(str)
        return out

    def get_factor_return_time_series(self, start_date: str, end_date: str) -> pd.DataFrame:
        if not self._range_covered(start_date, end_date) or self._raw_factor_return_ts is None:
            self._record("get_factor_return_time_series", hit=False)
            return self._delegate.get_factor_return_time_series(start_date, end_date)
        self._record("get_factor_return_time_series", hit=True)
        sliced = _inclusive_date_slice(
            self._raw_factor_return_ts, start_date, end_date, date_col="datetime"
        )
        return _deterministic_order(sliced.copy(deep=True), date_col="datetime")

    def get_factor_exposure_today(self, date: str) -> pd.DataFrame:
        raw = self._raw_factor_exposure_today.get(date) if self._in_scope_exact(date) else None
        if raw is None:
            self._record("get_factor_exposure_today", hit=False)
            return self._delegate.get_factor_exposure_today(date)
        self._record("get_factor_exposure_today", hit=True)
        out = raw.copy(deep=True)
        out.drop(["datetime"], axis=1, inplace=True)
        return out

    def get_specific_risk(self, date: str) -> pd.DataFrame:
        raw = self._raw_specific_risk.get(date) if self._in_scope_exact(date) else None
        if raw is None:
            self._record("get_specific_risk", hit=False)
            return self._delegate.get_specific_risk(date)
        self._record("get_specific_risk", hit=True)
        out = raw.copy(deep=True)
        out.index = out["instrument"]
        out.drop(["datetime", "instrument"], axis=1, inplace=True)
        return out

    def get_index_weight(self, date: str, bench: str) -> pd.DataFrame:
        raw = self._raw_index_weight.get((date, bench)) if self._in_scope_exact(date) else None
        if raw is None:
            self._record("get_index_weight", hit=False)
            return self._delegate.get_index_weight(date, bench)
        self._record("get_index_weight", hit=True)
        out = raw.copy(deep=True)
        out.drop(["index"], axis=1, inplace=True)
        out["datetime"] = pd.to_datetime(out["datetime"])
        return out

    def get_index_component(self, date: str, index_code: str) -> list[str]:
        raw = self._raw_index_weight.get((date, index_code)) if self._in_scope_exact(date) else None
        if raw is None:
            self._record("get_index_component", hit=False)
            delegated: list[str] = self._delegate.get_index_component(date, index_code)
            return delegated
        self._record("get_index_component", hit=True)
        result = self.get_index_weight(date, index_code)
        return list(result["instrument"].tolist())

    def get_factor_exposure(self, date: str) -> pd.DataFrame:
        raw = self._raw_factor_exposure.get(date) if self._in_scope_exact(date) else None
        if raw is None:
            self._record("get_factor_exposure", hit=False)
            return self._delegate.get_factor_exposure(date)
        result = raw.copy(deep=True)
        if result.empty:
            previous_date = factor_client_adapter.get_previous_trade_day(date)
            prev_raw = (
                self._raw_factor_exposure.get(previous_date)
                if self._in_scope_exact(previous_date)
                else None
            )
            if prev_raw is None:
                self._record("get_factor_exposure", hit=False)
                return self._delegate.get_factor_exposure(date)
            result = prev_raw.copy(deep=True)
            if result.empty:
                self._record("get_factor_exposure", hit=False)
                return self._delegate.get_factor_exposure(date)
            logger.warning(
                "日期 %s 的因子暴露数据缺失，使用前一交易日 %s 的数据", date, previous_date
            )
        self._record("get_factor_exposure", hit=True)
        result.index = result["instrument"]
        result.drop(["datetime", "instrument"], axis=1, inplace=True)
        return result

    def get_factor_exposure_time_series(self, start_date: str, end_date: str) -> pd.DataFrame:
        prev_trading_date = factor_client_adapter.get_previous_trade_day(start_date)
        raw = self._raw_factor_exposure_ts
        if raw is None or not self._ts_covered(str(prev_trading_date), end_date):
            self._record("get_factor_exposure_time_series", hit=False)
            return self._delegate._factor.get_factor_exposure_time_series(start_date, end_date)
        self._record("get_factor_exposure_time_series", hit=True)
        memo_key = (str(start_date), str(end_date))
        cached = self._shaped_factor_exposure_ts.get(memo_key)
        if cached is not None:
            self._shaped_factor_exposure_ts.move_to_end(memo_key)
            return cached.copy(deep=True)
        res = _inclusive_date_slice(
            raw, str(prev_trading_date), end_date, date_col="datetime"
        ).copy(deep=True)
        res = _deterministic_order(res, date_col="datetime")
        res = (
            res.set_index(["datetime", "instrument"])
            .sort_values(by="datetime", ascending=True)
            .groupby("instrument")
            .shift(1)
            .reset_index()
        )
        res["datetime"] = res["datetime"].astype(str)
        res = res[res["datetime"] != str(prev_trading_date)]
        self._shaped_factor_exposure_ts[memo_key] = res
        while len(self._shaped_factor_exposure_ts) > _SHAPED_TS_MEMO_MAXSIZE:
            self._shaped_factor_exposure_ts.popitem(last=False)
        return res.copy(deep=True)


    def get_pt_stock(self, date: str) -> pd.DataFrame:
        return self._delegate.get_pt_stock(date)

    def get_suspend_stocks(self, date: str) -> list[str]:
        suspended: list[str] = self._delegate.get_suspend_stocks(date)
        return suspended

    def cal_idx_return(self, date: str, idx_code: str) -> float:
        idx_ret: float = self._delegate.cal_idx_return(date, idx_code)
        return idx_ret

    def get_factor_covariance(self, date: str) -> pd.DataFrame:
        return self._delegate.get_factor_covariance(date)


    def _range_covered(self, start_date: str, end_date: str) -> bool:
        if self._scope is None:
            return False
        s = _date_only(start_date)
        e = _date_only(end_date)
        return self._scope.range_start <= s and e <= self._scope.range_end

    def _ts_covered(self, prev_trading_date: str, end_date: str) -> bool:
        if self._scope is None:
            return False
        ts_start = _date_only(self._scope.factor_exposure_ts_raw_start or self._scope.range_start)
        p = _date_only(prev_trading_date)
        e = _date_only(end_date)
        return ts_start <= p and e <= self._scope.range_end

    def _in_scope_exact(self, date: str) -> bool:
        return _date_only(date) in self._exact_date_set


_DEFAULT_COMPONENT_POOLS: tuple[str, ...] = (
    "IN000905",
    "IN000852",
    "IN000300",
    "IN932000",
    "IN000922",
    "IN866006",
)

_DEFAULT_LOOKBACK_TRADE_DAYS = 400


def build_prefetch_scope(
    *,
    score_dates: list[str],
    benchmark: str | None,
    calendar: Any,
    lookback_trade_days: int = _DEFAULT_LOOKBACK_TRADE_DAYS,
    extra_benchmarks: list[str] | None = None,
) -> PrefetchScope | None:
    clean = sorted({_date_only(d) for d in score_dates if d and str(d).strip()})
    if not clean:
        return None

    earliest = clean[0]
    exact_dates: set[str] = set(clean)
    for d in clean:
        try:
            exact_dates.add(_date_only(calendar.next_trade_day(d)))
        except Exception:
            logger.debug("build_prefetch_scope: next_trade_day(%s) failed; skipping", d)

    try:
        range_start = _date_only(calendar.previous_trade_day(earliest, lookback_trade_days))
    except Exception:
        range_start = _date_only(
            str(pd.to_datetime(earliest) - pd.Timedelta(days=int(lookback_trade_days * 1.6)))
        )

    range_end = max(exact_dates)

    try:
        ts_raw_start = _date_only(calendar.previous_trade_day(range_start))
    except Exception:
        ts_raw_start = _date_only(str(pd.to_datetime(range_start) - pd.Timedelta(days=4)))

    benches: list[str] = []
    for b in [benchmark, *_DEFAULT_COMPONENT_POOLS, *(extra_benchmarks or [])]:
        if b and b not in benches:
            benches.append(b)

    return PrefetchScope(
        range_start=range_start,
        range_end=range_end,
        exact_dates=sorted(exact_dates),
        benchmarks=benches,
        factor_exposure_ts_raw_start=ts_raw_start,
    )


def _date_only(value: str) -> str:
    text = str(value)
    return text.split()[0] if " " in text else text


def _inclusive_date_slice(
    df: pd.DataFrame, start_date: str, end_date: str, *, date_col: str
) -> pd.DataFrame:
    dt = pd.to_datetime(df[date_col]).dt.normalize()
    start = pd.to_datetime(_date_only(start_date)).normalize()
    end = pd.to_datetime(_date_only(end_date)).normalize()
    mask = (dt >= start) & (dt <= end)
    return df.loc[mask]


def _deterministic_order(df: pd.DataFrame, *, date_col: str) -> pd.DataFrame:
    sort_cols: list[str] = []
    if date_col in df.columns:
        sort_cols.append(date_col)
    if "instrument" in df.columns and "instrument" not in sort_cols:
        sort_cols.append("instrument")
    if not sort_cols:
        return df.reset_index(drop=True)
    return df.sort_values(by=sort_cols, kind="stable").reset_index(drop=True)
