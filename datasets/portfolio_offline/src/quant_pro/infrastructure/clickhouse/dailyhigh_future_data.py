
from __future__ import annotations

from types import MappingProxyType
from typing import Any

import pandas as pd


_SPOT_TO_FAMILY = MappingProxyType(
    {"IN000300": "IF", "IN399905": "IC", "IN000852": "IM"}
)
_FUTURE_FAMILIES = frozenset(_SPOT_TO_FAMILY.values())
_FUTURE_DAILY_TABLE = "ods.ods_quant_future_marketdata_post_1day_di"
_FUTURE_INFO_TABLE = "ods.ods_quant_future_marketdata_info_di"
_FUTURE_DOMINANT_TABLE = "ods.ods_quant_future_marketdata_dominant_di"
_INDEX_DAILY_TABLE = "ods.ods_quant_stock_marketdata_index_1day_di"
_TRADE_DATE_TABLE = "ods.ods_quant_stock_marketdata_cn_trade_date_di"


def is_legacy_dailyhigh_contract(instrument: str) -> bool:

    value = str(instrument)
    return len(value) > 2 and value[2].isdigit() and int(value[2]) <= 3


def _date_text(value: Any) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _validate_spots(values: list[str]) -> list[str]:
    spots = [str(value) for value in values]
    unsupported = sorted(set(spots) - set(_SPOT_TO_FAMILY))
    if unsupported:
        raise ValueError(f"unsupported DailyHigh spot indices: {unsupported}")
    return spots


def _validate_families(values: list[str]) -> list[str]:
    families = [str(value) for value in values]
    unsupported = sorted(set(families) - _FUTURE_FAMILIES)
    if unsupported:
        raise ValueError(f"unsupported DailyHigh future families: {unsupported}")
    return families


def _quoted(values: list[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class DailyHighClickHouseFutureData:

    def __init__(self, client: Any) -> None:
        self.client = client

    def get_all_index_close_prices(
        self,
        current_date: Any,
        indices_of_interest: list[str],
    ) -> pd.DataFrame:
        spots = _validate_spots(indices_of_interest)
        if not spots:
            return pd.DataFrame(columns=["price"], index=pd.Index([], name="instrument"))
        result = self.client.query(
            f"""
            SELECT instrument, close AS price
            FROM {_INDEX_DAILY_TABLE}
            WHERE datetime = '{_date_text(current_date)}'
              AND instrument IN ({_quoted(spots)})
            ORDER BY instrument
            """
        )
        if result.empty:
            return pd.DataFrame(columns=["price"], index=pd.Index([], name="instrument"))
        frame = result[["instrument", "price"]].copy()
        frame["instrument"] = frame["instrument"].map(_SPOT_TO_FAMILY)
        return frame.set_index("instrument")

    def get_all_future_close_prices(
        self,
        current_date: Any,
        contracts_of_interest: list[str],
    ) -> pd.DataFrame:
        families = _validate_families(contracts_of_interest)
        result = self._daily_rows(current_date, families, "settlement AS price")
        if result.empty:
            return pd.DataFrame(
                columns=["future", "price"], index=pd.Index([], name="instrument")
            )
        frame = result.rename(columns={"instrument": "future"})
        frame = frame[frame["future"].map(is_legacy_dailyhigh_contract)].dropna(
            subset=["price"]
        )
        frame["instrument"] = frame["future"].str[:2]
        return frame.set_index("instrument")[["future", "price"]]

    def get_future_delisted_dates(
        self,
        current_date: Any,
        contracts_of_interest: list[str],
    ) -> pd.DataFrame:
        families = _validate_families(contracts_of_interest)
        if not families:
            return pd.DataFrame(
                columns=["future", "date"], index=pd.Index([], name="instrument")
            )
        family_predicate = " OR ".join(
            f"startsWith(instrument, '{family}')" for family in families
        )
        result = self.client.query(
            f"""
            SELECT instrument AS future, de_listed_date AS date
            FROM {_FUTURE_INFO_TABLE}
            WHERE ({family_predicate})
              AND de_listed_date IS NOT NULL
            ORDER BY instrument
            """
        )
        if result.empty:
            return pd.DataFrame(
                columns=["future", "date"], index=pd.Index([], name="instrument")
            )
        frame = result[result["future"].map(is_legacy_dailyhigh_contract)].copy()
        frame["instrument"] = frame["future"].str[:2]
        return frame.set_index("instrument")[["future", "date"]]

    def get_future_volume_interest_multiplier(
        self,
        current_date: Any,
        contracts_of_interest: list[str],
    ) -> pd.DataFrame:
        families = _validate_families(contracts_of_interest)
        if not families:
            return pd.DataFrame(
                columns=["volume", "open_interest", "multiplier"],
                index=pd.Index([], name="future"),
            )
        family_predicate = " OR ".join(
            f"startsWith(day.instrument, '{family}')" for family in families
        )
        result = self.client.query(
            f"""
            SELECT
                day.instrument AS future,
                day.volume AS volume,
                day.open_interest AS open_interest,
                info.contract_multiplier AS multiplier
            FROM {_FUTURE_DAILY_TABLE} AS day
            LEFT ANY JOIN {_FUTURE_INFO_TABLE} AS info
                ON day.instrument = info.instrument
            WHERE day.datetime = '{_date_text(current_date)}'
              AND ({family_predicate})
            ORDER BY day.instrument
            """
        )
        if result.empty:
            return pd.DataFrame(
                columns=["volume", "open_interest", "multiplier"],
                index=pd.Index([], name="future"),
            )
        frame = result[result["future"].map(is_legacy_dailyhigh_contract)].copy()
        frame = frame.dropna(subset=["volume", "open_interest", "multiplier"])
        return frame.set_index("future")[["volume", "open_interest", "multiplier"]]

    def get_allocation_margin_rate(
        self,
        current_date: Any,
        future_family: str,
        *,
        adjustment: float = 0.03,
    ) -> float:

        family = _validate_families([future_family])[0]
        result = self.client.query(
            f"""
            SELECT dominant.instrument AS future, info.margin_rate AS margin_rate
            FROM {_FUTURE_DOMINANT_TABLE} AS dominant
            LEFT ANY JOIN {_FUTURE_INFO_TABLE} AS info
                ON dominant.instrument = info.instrument
            WHERE dominant.datetime = '{_date_text(current_date)}'
              AND dominant.underlying_symbol = '{family}'
            LIMIT 1
            """
        )
        if result.empty or pd.isna(result["margin_rate"].iloc[0]):
            raise ValueError(
                f"dominant {family} margin rate missing for {_date_text(current_date)}"
            )
        allocation_rate = float(result["margin_rate"].iloc[0]) - float(adjustment)
        if allocation_rate <= 0:
            raise ValueError(
                f"invalid adjusted allocation margin rate {allocation_rate} for {family}"
            )
        return allocation_rate

    def _daily_rows(
        self,
        current_date: Any,
        families: list[str],
        columns: str,
    ) -> pd.DataFrame:
        if not families:
            return pd.DataFrame()
        family_predicate = " OR ".join(
            f"startsWith(instrument, '{family}')" for family in families
        )
        return self.client.query(
            f"""
            SELECT instrument, {columns}
            FROM {_FUTURE_DAILY_TABLE}
            WHERE datetime = '{_date_text(current_date)}'
              AND ({family_predicate})
            ORDER BY instrument
            """
        )


class DailyHighClickHouseCalendar:

    def __init__(self, client: Any) -> None:
        self.client = client

    def get_trading_days_between(self, start_date: Any, end_date: Any) -> int:
        result = self.client.query(
            f"""
            SELECT count() AS trading_days
            FROM {_TRADE_DATE_TABLE}
            WHERE date > '{_date_text(start_date)}'
              AND date <= '{_date_text(end_date)}'
            """
        )
        return int(result["trading_days"].iloc[0])

    def next_trade_day(self, value: str, n: int = 1) -> str:
        if n < 1:
            raise ValueError("n must be >= 1")
        result = self.client.query(
            f"""
            SELECT date
            FROM {_TRADE_DATE_TABLE}
            WHERE date > '{_date_text(value)}'
            ORDER BY date ASC
            LIMIT {int(n)}
            """
        )
        if len(result) < n:
            raise IndexError(f"calendar has no {n}-th next trade day after {value}")
        return pd.Timestamp(result["date"].iloc[n - 1]).strftime("%Y-%m-%d")

    def previous_trade_day(self, value: str, n: int = 1) -> str:
        if n < 1:
            raise ValueError("n must be >= 1")
        result = self.client.query(
            f"""
            SELECT date
            FROM {_TRADE_DATE_TABLE}
            WHERE date < '{_date_text(value)}'
            ORDER BY date DESC
            LIMIT {int(n)}
            """
        )
        if len(result) < n:
            raise IndexError(f"calendar has no {n}-th previous trade day before {value}")
        return pd.Timestamp(result["date"].iloc[n - 1]).strftime("%Y-%m-%d")


__all__ = (
    "DailyHighClickHouseCalendar",
    "DailyHighClickHouseFutureData",
    "is_legacy_dailyhigh_contract",
)
