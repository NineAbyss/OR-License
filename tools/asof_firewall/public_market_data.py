
from __future__ import annotations

from pathlib import Path
import json

import numpy as np
import pandas as pd


class CurrentMarketData:
    def __init__(self, context: dict):
        self.context = dict(context)
        self.date = str(self.context["decision_day"])
        self.execution_date = str(self.context.get("execution_date", self.date))
        self.benchmark = self.context.get("benchmark")
        self.cross_section_path = Path(self.context["cross_section"])
        self.factors_path = Path(self.context["factors"])
        self._table = pd.read_csv(self.cross_section_path)
        self._table["instrument"] = self._table["instrument"].astype(str)
        self.development_root = Path(
            self.context.get("development_pack", "/data_readonly/devpack")
        )
        self.development = bool(
            self.context.get("development", False)
            or self.context.get("data_scope") == "development"
        )
        self._calendar = self._load_calendar()

    @classmethod
    def from_context(cls, context_or_path):
        if isinstance(context_or_path, (str, Path)):
            context = json.loads(Path(context_or_path).read_text(encoding="utf-8"))
        else:
            context = context_or_path
        return cls(context)

    def _check_date(self, date: str | None, *, execution: bool = False) -> None:
        if self.development:
            if date is not None and str(date) not in set(self._calendar):
                raise ValueError("date is outside the released development window")
            return
        allowed = {self.date, self.execution_date} if execution else {self.date}
        if date is not None and str(date) not in allowed:
            raise ValueError("public market API only exposes the current decision date")

    def _load_calendar(self) -> list[str]:
        path = self.development_root / "calendar.csv"
        if not self.development or not path.is_file():
            return [self.date]
        return pd.read_csv(path)["date"].astype(str).tolist()

    def _check_execution_date(self, date: str) -> None:
        if date == self.execution_date:
            return
        if self.development:
            self._check_date(date)
            return
        raise ValueError("public market API only exposes the current execution date")

    def _previous_signal_date(self, execution_date: str) -> str:
        if len(self._calendar) != len(set(self._calendar)):
            raise ValueError(
                "released trading calendar contains duplicate dates; "
                "cannot determine date pairing"
            )
        try:
            parsed_calendar = pd.to_datetime(self._calendar, errors="raise")
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "released trading calendar contains invalid dates; "
                "cannot determine date pairing"
            ) from exc
        if not parsed_calendar.is_monotonic_increasing:
            raise ValueError(
                "released trading calendar is not ordered; "
                "cannot determine date pairing"
            )
        try:
            position = self._calendar.index(execution_date)
        except ValueError as exc:
            raise ValueError(
                f"execution date {execution_date} is outside the released development window"
            ) from exc
        if position == 0:
            raise ValueError(
                f"no prior trading day for execution date {execution_date}"
            )
        signal_date = self._calendar[position - 1]
        snapshot = self.development_root / "cross_section" / f"{signal_date}.csv"
        if not snapshot.is_file():
            raise ValueError(
                f"no released market snapshot for execution date {execution_date}; "
                f"signal date {signal_date} is missing"
            )
        return signal_date

    def _table_for(self, date: str | None = None) -> pd.DataFrame:
        requested = str(date or self.date)
        self._check_date(requested)
        if self.development and requested != self.date:
            path = self.development_root / "cross_section" / f"{requested}.csv"
            if not path.is_file():
                raise ValueError(f"no released market snapshot for {requested}")
            table = pd.read_csv(path)
            table["instrument"] = table["instrument"].astype(str)
            return table
        return self._table

    def _factors_for(self, date: str | None = None) -> tuple[list[str], list[str], np.ndarray, np.ndarray]:
        requested = str(date or self.date)
        self._check_date(requested)
        path = self.factors_path
        if self.development and requested != self.date:
            path = self.development_root / "factors" / f"{requested}.npz"
        with np.load(path, allow_pickle=True) as handle:
            names = [str(x) for x in handle["asset_ids"]]
            factors = [str(x) for x in handle["factor_names"]]
            exposures = np.asarray(handle["exposures"], dtype=float)
            covariance = np.asarray(handle["factor_covariance"], dtype=float)
        return names, factors, exposures, covariance

    def _future_table(self, date: str | None = None) -> pd.DataFrame:
        requested = str(date or self.date)
        if self.development:
            self._check_date(requested)
            path = self.development_root / "futures" / f"{requested}.csv"
        else:
            self._check_date(requested)
            path = self.context.get("futures")
            path = Path(path) if path else Path("")
        if not path.is_file():
            raise ValueError(f"future market data is unavailable for {requested}")
        return pd.read_csv(path)

    def get_all_future_close_prices(self, date: str | None = None, family: str = "IC") -> pd.DataFrame:
        table = self._future_table(date)
        family = family[0] if isinstance(family, (list, tuple)) else family
        return table.loc[table["future"].astype(str).str.startswith(str(family)), ["future", "price"]].copy()

    def get_future_delisted_dates(self, date: str | None = None, family: str = "IC") -> pd.DataFrame:
        table = self._future_table(date)
        family = family[0] if isinstance(family, (list, tuple)) else family
        return table.loc[table["future"].astype(str).str.startswith(str(family)), ["future", "date"]].copy()

    def get_future_volume_interest_multiplier(self, date: str | None = None, family: str = "IC") -> pd.DataFrame:
        table = self._future_table(date)
        family = family[0] if isinstance(family, (list, tuple)) else family
        columns = ["future", "volume", "open_interest", "multiplier"]
        return table.loc[table["future"].astype(str).str.startswith(str(family)), columns].set_index("future")

    def get_all_index_close_prices(self, date: str | None = None, index_code: str = "IN399905") -> pd.DataFrame:
        table = self._future_table(date)
        index_code = index_code[0] if isinstance(index_code, (list, tuple)) else index_code
        row = table.loc[table["index_code"].astype(str) == str(index_code), "index_close"]
        if row.empty:
            raise ValueError(f"index close is unavailable for {index_code}")
        return pd.DataFrame({"price": [float(row.iloc[0])] }, index=[index_code])

    def get_allocation_margin_rate(self, date: str | None = None, family: str = "IC") -> float:
        table = self._future_table(date)
        family = family[0] if isinstance(family, (list, tuple)) else family
        rows = table.loc[table["future"].astype(str).str.startswith(str(family)), "margin_rate"]
        if rows.empty:
            raise ValueError(f"margin rate is unavailable for {family}")
        return float(rows.iloc[0])

    def get_close_price(self, date: str | None = None) -> pd.DataFrame:
        return self._table_for(date)[["instrument", "close"]].copy()

    def get_suspend_stocks(self, date: str | None = None) -> list[str]:
        requested = self.execution_date if date is None else str(date)
        self._check_execution_date(requested)
        if self.development:
            if requested == self.execution_date:
                table = self._table
            else:
                signal_date = self._previous_signal_date(requested)
                path = self.development_root / "cross_section" / f"{signal_date}.csv"
                table = pd.read_csv(path)
                missing = {"instrument", "is_suspended"}.difference(table.columns)
                if missing:
                    raise ValueError(
                        f"market snapshot for signal date {signal_date} is missing "
                        f"required column(s): {', '.join(sorted(missing))}"
                    )
                table["instrument"] = table["instrument"].astype(str)
        else:
            table = self._table
        if "is_suspended" not in table.columns:
            source = "current runtime market snapshot" if table is self._table else "market snapshot"
            raise ValueError(f"{source} is missing required column: is_suspended")
        return table.loc[table["is_suspended"].astype(bool), "instrument"].tolist()

    def get_pt_stock(self, date: str | None = None) -> pd.DataFrame:
        table = self._table_for(date)
        names = table.loc[table["is_st"].astype(bool), "instrument"]
        return pd.DataFrame({"instrument": names.tolist(), "is_st": True})

    def get_delisted_stocks(self, date: str | None = None) -> list[str]:
        table = self._table_for(date)
        return table.loc[table["is_delisted"].astype(bool), "instrument"].tolist()

    def get_scores(self, date: str | None = None) -> pd.DataFrame:
        table = self._table_for(date)
        return table.loc[
            table["score_available"].astype(bool), ["instrument", "score"]
        ].copy()

    def get_index_component(self, date: str | None = None, index_code: str | None = None) -> list[str]:
        table = self._table_for(date)
        if index_code and self.benchmark and str(index_code) != str(self.benchmark):
            raise ValueError("public market API only exposes the task benchmark")
        return table.loc[table["is_constituent"].astype(bool), "instrument"].tolist()

    def get_index_weight(self, date: str | None = None, index_code: str | None = None) -> pd.DataFrame:
        table = self._table_for(date)
        if index_code and self.benchmark and str(index_code) != str(self.benchmark):
            raise ValueError("public market API only exposes the task benchmark")
        return table[["instrument", "benchmark_weight"]].rename(
            columns={"benchmark_weight": "weight"}
        )

    def get_factor_exposure(self, date: str | None = None) -> pd.DataFrame:
        names, factors, values, _ = self._factors_for(date)
        return pd.DataFrame(values, index=names, columns=factors)

    def get_factor_covariance(self, date: str | None = None) -> pd.DataFrame:
        _, factors, _, values = self._factors_for(date)
        return pd.DataFrame(values, index=factors, columns=factors)

    def get_specific_risk(self, date: str | None = None) -> pd.DataFrame:
        result = self._table_for(date)[["instrument", "specific_variance"]].copy()
        result["specific_risk"] = np.sqrt(np.maximum(result.pop("specific_variance"), 0.0))
        return result

    def get_specific_variance(self, date: str | None = None) -> pd.DataFrame:
        return self._table_for(date)[["instrument", "specific_variance"]].copy()

    def _slips_path(self, date: str) -> Path:
        if date == self.date:
            configured = self.context.get("borrow_slips")
            if configured:
                return Path(configured)
        return self.development_root / "borrow_slips" / f"{date}.csv"

    def get_borrow_slips(self, date: str | None = None) -> pd.DataFrame:
        requested = str(date or self.date)
        self._check_date(requested)
        path = self._slips_path(requested)
        if not path.is_file():
            raise ValueError(f"borrow slips are unavailable for {requested}")
        frame = pd.read_csv(path)
        for column in ("id", "instrument"):
            if column in frame.columns:
                frame[column] = frame[column].astype(str)
        return frame

    def get_borrow_slip_index(self, date: str | None = None) -> pd.DataFrame:
        requested = str(date or self.date)
        self._check_date(requested)
        configured = self.context.get("borrow_slip_index")
        path = Path(configured) if configured else (
            self.development_root / "borrow_slips" / "index.csv.gz"
        )
        if not path.is_file():
            raise ValueError(f"borrow slip index is unavailable for {requested}")
        frame = pd.read_csv(path)
        missing = {"id", "instrument", "cre_time"}.difference(frame.columns)
        if missing:
            raise ValueError(
                f"borrow slip index is missing required column(s): "
                f"{', '.join(sorted(missing))}"
            )
        frame["id"] = frame["id"].astype(str)
        frame["instrument"] = frame["instrument"].astype(str)
        frame["cre_time"] = frame["cre_time"].astype(str).str[:10]
        return frame.loc[frame["cre_time"] <= requested].reset_index(drop=True)

    def get_borrow_capacity(self, date: str | None = None) -> pd.DataFrame:
        table = self._table_for(date)
        column = "borrow_capacity_weight"
        if column not in table:
            return pd.DataFrame(columns=["instrument", column])
        return table[["instrument", column]].copy()

    def get_borrow_fee(self, date: str | None = None) -> pd.DataFrame:
        table = self._table_for(date)
        column = "borrow_fee"
        if column not in table:
            return pd.DataFrame(columns=["instrument", column])
        return table[["instrument", column]].copy()


def load_market_data(context_or_path) -> CurrentMarketData:
    return CurrentMarketData.from_context(context_or_path)
