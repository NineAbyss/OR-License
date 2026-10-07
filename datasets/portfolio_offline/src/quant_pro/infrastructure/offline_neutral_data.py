
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from quant_pro.infrastructure.clickhouse.dailyhigh_future_data import (
    is_legacy_dailyhigh_contract,
)
from quant_pro.infrastructure.clickhouse.data_fetcher_facade import ClickHouseDataFetcher
from quant_pro.infrastructure.clickhouse.factor_data import FactorDataFetcher
from quant_pro.infrastructure.clickhouse.index_data import IndexDataFetcher
from quant_pro.infrastructure.clickhouse.snapshot_client import SnapshotClickHouseClient


def _date(value: Any) -> pd.Timestamp:
    return pd.Timestamp(value).normalize()


class WideParquetTradingCalendar:

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if not self.path.is_file():
            raise FileNotFoundError(f"offline calendar missing: {self.path}")
        frame = pd.read_csv(self.path)
        if frame.empty:
            raise ValueError(f"offline calendar is empty: {self.path}")
        column = "date" if "date" in frame.columns else str(frame.columns[0])
        dates = pd.DatetimeIndex(pd.to_datetime(frame[column], errors="raise")).normalize()
        if dates.has_duplicates:
            raise ValueError(f"offline calendar contains duplicate dates: {self.path}")
        self.dates = dates.sort_values()

    def _positioned(self, value: Any, *, after: bool) -> pd.DatetimeIndex:
        target = _date(value)
        return self.dates[self.dates > target] if after else self.dates[self.dates < target]

    def next_trade_day(self, value: str, n: int = 1) -> str:
        if n < 1:
            raise ValueError("n must be >= 1")
        candidates = self._positioned(value, after=True)
        if len(candidates) < n:
            raise IndexError(f"offline calendar has no {n}-th next trade day after {value}")
        return candidates[n - 1].strftime("%Y-%m-%d")

    def previous_trade_day(self, value: str, n: int = 1) -> str:
        if n < 1:
            raise ValueError("n must be >= 1")
        candidates = self._positioned(value, after=False)
        if len(candidates) < n:
            raise IndexError(f"offline calendar has no {n}-th previous trade day before {value}")
        return candidates[-n].strftime("%Y-%m-%d")

    def get_trading_days_between(self, start_date: Any, end_date: Any) -> int:
        start, end = _date(start_date), _date(end_date)
        return int(((self.dates > start) & (self.dates <= end)).sum())


class _WideParquetStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        if not self.root.is_dir():
            raise FileNotFoundError(f"offline factor directory missing: {self.root}")
        self._cache: dict[tuple[str, str], pd.DataFrame] = {}

    def frame(self, frequency: str, factor: str) -> pd.DataFrame:
        key = (frequency, factor)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        path = self.root / frequency / f"{factor}.parquet"
        if path.is_dir():
            parts = sorted(path.glob("*.parquet"))
            if not parts:
                raise FileNotFoundError(f"offline factor missing: {path}")
            frame = pd.concat([pd.read_parquet(part) for part in parts], axis=0)
        elif path.is_file():
            frame = pd.read_parquet(path)
        else:
            raise FileNotFoundError(f"offline factor missing: {path}")
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            raise ValueError(f"offline factor is empty: {path}")
        result = frame.copy()
        result.index = pd.DatetimeIndex(pd.to_datetime(result.index, errors="raise")).normalize()
        if result.index.has_duplicates:
            raise ValueError(f"offline factor has duplicate dates: {path}")
        result = result.sort_index()
        result.columns = result.columns.map(str)
        self._cache[key] = result
        return result

    def row(self, frequency: str, factor: str, value: Any) -> pd.Series:
        frame = self.frame(frequency, factor)
        target = _date(value)
        if target not in frame.index:
            raise KeyError(
                f"offline factor {frequency}/{factor} has no row for "
                f"{target.strftime('%Y-%m-%d')}"
            )
        return frame.loc[target].copy()


class WideParquetICFutureData:

    _FUTURE_FACTORS = (
        "settlement",
        "open",
        "high",
        "low",
        "volume",
        "open_interest",
        "contract_multiplier",
        "de_listed_date",
        "margin_rate",
        "is_dominant",
    )

    def __init__(self, factor_snapshot_dir: str | Path) -> None:
        self.store = _WideParquetStore(factor_snapshot_dir)
        for factor in self._FUTURE_FACTORS:
            self.store.frame("future_day", factor)
        self.store.frame("index_day", "close")

    @staticmethod
    def _require_ic(values: Iterable[str], *, kind: str) -> None:
        unsupported = sorted({str(value) for value in values} - {"IC" if kind == "future" else "IN399905"})
        if unsupported:
            raise ValueError(f"offline IC adapter does not support {kind}: {unsupported}")

    @staticmethod
    def _contracts(row: pd.Series, family: str = "IC") -> list[str]:
        return sorted(
            str(column)
            for column in row.index
            if str(column).startswith(family) and is_legacy_dailyhigh_contract(str(column))
        )

    def get_all_index_close_prices(
        self, current_date: Any, indices_of_interest: list[str]
    ) -> pd.DataFrame:
        self._require_ic(indices_of_interest, kind="index")
        row = self.store.row("index_day", "close", current_date)
        price = row.get("IN399905")
        if pd.isna(price):
            raise ValueError(f"offline IN399905 close missing for {_date(current_date).date()}")
        return pd.DataFrame(
            {"price": [float(price)]}, index=pd.Index(["IC"], name="instrument")
        )

    def get_all_future_close_prices(
        self, current_date: Any, contracts_of_interest: list[str]
    ) -> pd.DataFrame:
        self._require_ic(contracts_of_interest, kind="future")
        row = self.store.row("future_day", "settlement", current_date)
        contracts = [contract for contract in self._contracts(row) if pd.notna(row[contract])]
        if not contracts:
            raise ValueError(f"offline IC settlement missing for {_date(current_date).date()}")
        return pd.DataFrame(
            {"future": contracts, "price": [float(row[item]) for item in contracts]},
            index=pd.Index(["IC"] * len(contracts), name="instrument"),
        )

    def get_future_delisted_dates(
        self, current_date: Any, contracts_of_interest: list[str]
    ) -> pd.DataFrame:
        self._require_ic(contracts_of_interest, kind="future")
        row = self.store.row("future_day", "de_listed_date", current_date)
        contracts = [contract for contract in self._contracts(row) if pd.notna(row[contract])]
        if not contracts:
            raise ValueError(f"offline IC delisting metadata missing for {_date(current_date).date()}")
        return pd.DataFrame(
            {
                "future": contracts,
                "date": pd.to_datetime([row[item] for item in contracts], errors="raise"),
            },
            index=pd.Index(["IC"] * len(contracts), name="instrument"),
        )

    def get_future_volume_interest_multiplier(
        self, current_date: Any, contracts_of_interest: list[str]
    ) -> pd.DataFrame:
        self._require_ic(contracts_of_interest, kind="future")
        rows = {
            factor: self.store.row("future_day", factor, current_date)
            for factor in ("volume", "open_interest", "contract_multiplier")
        }
        contracts = self._contracts(rows["volume"])
        records: list[dict[str, Any]] = []
        for contract in contracts:
            values = [rows[name].get(contract) for name in rows]
            if all(pd.notna(value) for value in values):
                records.append(
                    {
                        "future": contract,
                        "volume": float(values[0]),
                        "open_interest": float(values[1]),
                        "multiplier": float(values[2]),
                    }
                )
        if not records:
            raise ValueError(f"offline IC liquidity metadata missing for {_date(current_date).date()}")
        return pd.DataFrame.from_records(records).set_index("future")

    def get_allocation_margin_rate(
        self, current_date: Any, future_family: str, *, adjustment: float = 0.03
    ) -> float:
        self._require_ic([future_family], kind="future")
        dominant = self.store.row("future_day", "is_dominant", current_date)
        margin = self.store.row("future_day", "margin_rate", current_date)
        candidates = [
            contract
            for contract in self._contracts(dominant)
            if pd.notna(dominant[contract]) and bool(dominant[contract])
        ]
        if len(candidates) != 1:
            raise ValueError(
                f"offline IC dominant contract must be unique for {_date(current_date).date()}; "
                f"found {candidates}"
            )
        raw = margin.get(candidates[0])
        if pd.isna(raw):
            raise ValueError(f"offline margin rate missing for dominant {candidates[0]}")
        value = float(raw) - float(adjustment)
        if value <= 0:
            raise ValueError(f"invalid adjusted allocation margin rate {value}")
        return value

    def load_feed_frames(
        self, *, family: str, start_date: Any, end_date: Any
    ) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
        self._require_ic([family], kind="future")
        start, end = _date(start_date), _date(end_date)
        matrices = {
            factor: self.store.frame("future_day", factor).loc[start:end]
            for factor in ("open", "high", "low", "settlement", "volume", "open_interest")
        }
        if any(frame.empty for frame in matrices.values()):
            raise ValueError(f"offline IC feed has no rows for {start.date()} .. {end.date()}")
        contracts = sorted(
            set.intersection(
                *(
                    {column for column in frame.columns if column.startswith("IC")}
                    for frame in matrices.values()
                )
            )
        )
        frames: dict[str, pd.DataFrame] = {}
        for contract in contracts:
            frame = pd.DataFrame(
                {
                    "open": matrices["open"][contract],
                    "high": matrices["high"][contract],
                    "low": matrices["low"][contract],
                    "close": matrices["settlement"][contract],
                    "volume": matrices["volume"][contract],
                    "openinterest": matrices["open_interest"][contract],
                }
            ).dropna(subset=["open", "close"])
            if not frame.empty:
                frames[contract] = frame
        if not frames:
            raise ValueError(f"offline IC feed has no usable contracts for {start.date()} .. {end.date()}")
        info_rows = []
        for contract in frames:
            values: dict[str, Any] = {"instrument": contract}
            for factor in ("contract_multiplier", "margin_rate", "de_listed_date"):
                series = self.store.frame("future_day", factor).loc[start:end, contract].dropna()
                if series.empty:
                    raise ValueError(f"offline {factor} missing for {contract}")
                values[factor] = series.iloc[-1]
            info_rows.append(values)
        return frames, pd.DataFrame.from_records(info_rows)


class HybridOfflineNeutralDataFetcher:

    def __init__(self, factor_snapshot_dir: str | Path) -> None:
        if os.environ.get("QUANT_PRO_SNAPSHOT_MODE", "").lower() != "replay":
            raise RuntimeError("HybridOfflineNeutralDataFetcher requires snapshot replay mode")
        snapshot_root = os.environ.get("QUANT_PRO_SNAPSHOT_DIR")
        if not snapshot_root or not Path(snapshot_root).is_dir():
            raise FileNotFoundError("QUANT_PRO_SNAPSHOT_DIR must name an existing offline snapshot")
        snapshot_path = Path(snapshot_root)
        for namespace in ("clickhouse_queries", "optimizer_fetcher_calls"):
            manifest = snapshot_path / namespace / "index.json"
            if not manifest.is_file():
                raise FileNotFoundError(f"offline snapshot manifest missing: {manifest}")
        self._wide = _WideParquetStore(factor_snapshot_dir)
        self._wide.frame("day", "close")
        self._wide.frame("day", "total_turnover")
        self._wide.frame("index_day", "close")
        self.client = SnapshotClickHouseClient(delegate=None)
        self._factor = FactorDataFetcher(self.client)
        self._index = IndexDataFetcher(self.client)
        self._optimizer_snapshots = ClickHouseDataFetcher(self.client)

    def get_close_price(self, date: str) -> pd.DataFrame:
        row = self._wide.row("day", "close", date).dropna()
        if row.empty:
            raise ValueError(f"offline stock close has no values for {date}")
        return pd.DataFrame({"instrument": row.index, "close": row.astype(float).values}).sort_values(
            "instrument"
        ).reset_index(drop=True)

    def get_period_close_turnover(self, start_date: str, end_date: str) -> pd.DataFrame:
        start, end = _date(start_date), _date(end_date)
        close = self._wide.frame("day", "close")
        turnover = self._wide.frame("day", "total_turnover")
        for name, frame in (("close", close), ("total_turnover", turnover)):
            if start not in frame.index or end not in frame.index:
                raise KeyError(f"offline stock {name} does not cover {start.date()} .. {end.date()}")
        close_long = close.loc[start:end].rename_axis("datetime").stack().rename("close")
        turnover_long = (
            turnover.loc[start:end]
            .rename_axis("datetime")
            .stack()
            .rename("total_turnover")
        )
        result = pd.concat([close_long, turnover_long], axis=1, join="inner").dropna().reset_index()
        result.columns = ["datetime", "instrument", "close", "total_turnover"]
        if result.empty:
            raise ValueError(f"offline stock history has no common values for {start.date()} .. {end.date()}")
        result["datetime"] = pd.to_datetime(result["datetime"]).dt.strftime("%Y-%m-%d")
        return result.sort_values(["datetime", "instrument"]).reset_index(drop=True)

    def cal_idx_return(self, date: str, idx_code: str) -> float:

        frame = self._wide.frame("index_day", "close")
        code = str(idx_code)
        if code not in frame.columns:
            raise KeyError(f"offline index_day/close has no benchmark column {code!r}")
        closes = frame.loc[frame.index <= _date(date), code].dropna()
        if len(closes) < 2:
            raise ValueError(
                f"cal_idx_return: offline index {code!r} has fewer than 2 quote "
                f"dates on-or-before {date!r}"
            )
        previous, current = float(closes.iloc[-2]), float(closes.iloc[-1])
        if previous == 0.0:
            raise ValueError(f"cal_idx_return: offline previous close is zero for {code!r}")
        return float(current / previous - 1.0)

    def get_factor_exposure(self, date: str) -> pd.DataFrame:
        return self._factor.get_factor_exposure(date)

    def get_factor_exposure_today(self, date: str) -> pd.DataFrame:
        return self._factor.get_factor_exposure_today(date)

    def get_specific_risk(self, date: str) -> pd.DataFrame:
        return self._factor.get_specific_risk(date)

    def get_index_weight(self, date: str, bench: str) -> pd.DataFrame:
        return self._index.get_index_weight(date, bench)

    def get_index_component(self, date: str, bench: str) -> list[str]:
        return self._index.get_index_component(date, bench)

    def get_factor_covariance(self, date: str) -> pd.DataFrame:
        return self._optimizer_snapshots.get_factor_covariance(date)

    def get_suspend_stocks(self, date: str) -> list[str]:
        return self._optimizer_snapshots.get_suspend_stocks(date)

    def get_pt_stock(self, date: str) -> pd.DataFrame:
        return self._optimizer_snapshots.get_pt_stock(date)


__all__ = (
    "HybridOfflineNeutralDataFetcher",
    "WideParquetICFutureData",
    "WideParquetTradingCalendar",
)
