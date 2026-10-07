
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
import math
import numpy as np


MAX_VOLUME_RATIO = 0.05
MAX_OPEN_INTEREST_RATIO = 0.01
DAYS_TO_ROLLOVER = 2
MIN_HEDGE_RATIO = 0.80
MAX_HEDGE_RATIO = 1.20
MIN_STOCK_FRACTION = 0.60


@dataclass(frozen=True)
class ExpectedHedge:
    contract: str
    contract_size: int
    hedge_notional: float


def _trading_days_between(calendar: Any, start: Any, end: Any) -> int:
    start = pd.Timestamp(start).normalize()
    end = pd.Timestamp(end).normalize()
    if end <= start:
        return 0
    count = 0
    cursor = start
    while True:
        cursor = pd.Timestamp(calendar.next_trade_day(cursor.strftime("%Y-%m-%d")))
        if cursor > end:
            return count
        count += 1


def _eligible(
    futures: pd.DataFrame,
    *,
    current_date: Any,
    short_notional: float,
    calendar: Any,
    submitted_contract_size: int | None = None,
) -> pd.DataFrame:
    required = {"future", "price", "multiplier", "volume", "open_interest", "date"}
    missing = sorted(required - set(futures.columns))
    if missing:
        raise ValueError(f"futures data missing columns: {', '.join(missing)}")
    data = futures.copy()
    numeric = ["price", "multiplier", "volume", "open_interest"]
    data[numeric] = data[numeric].apply(pd.to_numeric, errors="coerce")
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data = data[
        data[numeric].notna().all(axis=1)
        & data["date"].notna()
        & (data["price"] > 0)
        & (data["multiplier"] > 0)
        & (data["volume"] >= 0)
        & (data["open_interest"] >= 0)
    ].copy()
    if submitted_contract_size is None:
        data["position_per_price"] = (
            float(short_notional) / (data["price"] * data["multiplier"])
        ).astype(int)
    else:
        data["position_per_price"] = int(submitted_contract_size)
    days = data["date"].map(
        lambda expiry: _trading_days_between(calendar, current_date, expiry)
    )
    data = data[
        (days > DAYS_TO_ROLLOVER + 1)
        & (data["volume"] * MAX_VOLUME_RATIO >= data["position_per_price"])
        & (data["open_interest"] * MAX_OPEN_INTEREST_RATIO >= data["position_per_price"])
    ]
    return data.sort_values("date", kind="stable")


def expected_next_month_hedge(
    futures: pd.DataFrame,
    *,
    current_date: Any,
    short_notional: float,
    beta_rate: float,
    calendar: Any,
    reserve_scale: float = 1.0,
) -> ExpectedHedge:
    eligible = _eligible(
        futures,
        current_date=current_date,
        short_notional=short_notional,
        calendar=calendar,
    )
    if eligible.empty:
        raise ValueError("no eligible IC futures contract")
    selected = eligible.iloc[0]
    hedge_notional = float(short_notional) * float(beta_rate) * reserve_scale
    contract_size = int(
        hedge_notional / (float(selected["price"]) * float(selected["multiplier"]))
    )
    return ExpectedHedge(str(selected["future"]), contract_size, hedge_notional)


def validate_agent_hedge(
    agent_hedge: dict[str, Any],
    futures: pd.DataFrame,
    *,
    current_date: Any,
    short_notional: float,
    beta_rate: float,
    calendar: Any,
    reserve_scale: float = 1.0,
) -> ExpectedHedge:
    value = agent_hedge.get("contract_size")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("IC contract_size must be a non-negative integer") from exc
    if isinstance(value, (bool, np.bool_)) or not math.isfinite(number) or number < 0 or not number.is_integer():
        raise ValueError("IC contract_size must be a non-negative integer")
    actual_size = int(number)
    eligible = _eligible(
        futures,
        current_date=current_date,
        short_notional=short_notional,
        calendar=calendar,
        submitted_contract_size=actual_size,
    )
    if eligible.empty:
        raise ValueError("submitted IC contract has no eligible liquid contract")
    expected_contract = str(eligible.iloc[0]["future"])
    actual_contract = str(agent_hedge.get("future", ""))
    if actual_contract != expected_contract:
        raise ValueError(
            f"IC contract {actual_contract!r} does not match expected {expected_contract!r}"
        )
    selected = futures.loc[futures["future"].astype(str) == actual_contract]
    if selected.empty:
        raise ValueError(f"agent selected unavailable IC contract {actual_contract!r}")
    row = selected.iloc[0]
    actual_notional = actual_size * float(row["price"]) * float(row["multiplier"])
    target_notional = float(short_notional) * float(beta_rate) * float(reserve_scale)
    if not math.isfinite(target_notional) or target_notional <= 0:
        raise ValueError("IC beta target notional must be positive and finite")
    ratio = actual_notional / target_notional
    if not MIN_HEDGE_RATIO <= ratio <= MAX_HEDGE_RATIO:
        raise ValueError(
            f"IC hedge ratio {ratio:.6f} is outside "
            f"[{MIN_HEDGE_RATIO:.2f}, {MAX_HEDGE_RATIO:.2f}]"
        )
    return ExpectedHedge(actual_contract, actual_size, actual_notional)


def validated_stock_fraction(agent_hedge: dict[str, Any]) -> float:

    value = agent_hedge.get("stock_fraction")
    try:
        fraction = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("stock_fraction must be a finite number in [0.60, 1.00]") from exc
    if (
        isinstance(value, (bool, np.bool_))
        or not math.isfinite(fraction)
        or not MIN_STOCK_FRACTION <= fraction <= 1.0
    ):
        raise ValueError("stock_fraction must be a finite number in [0.60, 1.00]")
    return fraction


class PublicCalendar:
    def __init__(self, dates):
        self.dates = pd.DatetimeIndex(pd.to_datetime(dates)).sort_values()

    def next_trade_day(self, value):
        later = self.dates[self.dates > pd.Timestamp(value)]
        if later.empty:
            raise ValueError("public trading calendar does not cover expiry")
        return later[0].strftime("%Y-%m-%d")


def verify_submission(stock_target, agent_hedge, futures, market, exposures, day, portfolio_nav):

    nav = float(portfolio_nav)
    if not math.isfinite(nav) or nav <= 0:
        raise ValueError("portfolio_nav must be positive and finite")
    stock_budget = nav * validated_stock_fraction(agent_hedge)
    weights = (
        stock_target.assign(instrument=stock_target["instrument"].map(str))
        .groupby("instrument")["weight"]
        .sum()
    )
    if "beta" not in exposures:
        raise ValueError("Barra beta exposure is unavailable")
    beta = pd.to_numeric(exposures["beta"], errors="coerce")
    beta.index = beta.index.map(str)
    aligned_beta = beta.reindex(weights.index)
    if aligned_beta.loc[weights.abs() > 1e-12].isna().any():
        raise ValueError("Barra beta exposure is missing for a stock target")
    output_beta = float((weights * aligned_beta.fillna(0.0)).sum())
    bench = pd.DataFrame(market["benchmark"])
    if not {"weight", "beta"}.issubset(bench):
        raise ValueError("benchmark Barra beta exposure is unavailable")
    bench_weights = pd.to_numeric(bench["weight"], errors="coerce")
    bench_beta = pd.to_numeric(bench["beta"], errors="coerce")
    if bench_weights.isna().any() or bench_beta.isna().any():
        raise ValueError("benchmark Barra beta exposure is not finite")
    benchmark_beta = float((bench_weights * bench_beta).sum())
    if not math.isfinite(benchmark_beta) or benchmark_beta <= 0:
        raise ValueError("benchmark Barra beta must be positive and finite")
    if not math.isfinite(output_beta) or output_beta < benchmark_beta - 0.1:
        raise ValueError("stock portfolio active Barra beta must be at least -0.1")
    hedge = validate_agent_hedge(
        agent_hedge, futures, current_date=day, short_notional=stock_budget,
        beta_rate=output_beta / benchmark_beta,
        calendar=PublicCalendar(market["calendar"]),
    )
    row = futures.loc[futures["future"].astype(str) == hedge.contract].iloc[0]
    try:
        margin_rate = float(row["exchange_margin_rate"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("exchange margin rate is unavailable for the submitted IC") from exc
    if not math.isfinite(margin_rate) or margin_rate <= 0:
        raise ValueError("exchange margin rate must be positive and finite")
    funding_roundoff = 4.0 * math.ulp(nav)
    if math.fsum((stock_budget, hedge.hedge_notional * margin_rate)) > nav + funding_roundoff:
        raise ValueError("stock budget and IC initial margin exceed portfolio_nav")
    return hedge
