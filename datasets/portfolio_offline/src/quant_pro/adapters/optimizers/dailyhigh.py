from __future__ import annotations
from dataclasses import asdict, dataclass
import math
from typing import Any, Mapping
import pandas as pd


@dataclass(frozen=True, slots=True)
class BenchmarkFutureSpec:

    benchmark: str
    spot_index: str
    future_family: str


@dataclass(slots=True)
class DailyHighState:

    current_future: str | None = None
    best_basis_return: float = float("-inf")
    last_close_price: float = 0.0
    portfolio_benchmark_beta_rate: float = 0.0
    short_value_after_beta: float = 0.0
    last_change_day: pd.Timestamp | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if not math.isfinite(self.best_basis_return):
            payload["best_basis_return"] = None
        if self.last_change_day is not None:
            payload["last_change_day"] = self.last_change_day.isoformat()
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> DailyHighState:
        values = dict(payload)
        if values.get("best_basis_return") is None:
            values["best_basis_return"] = float("-inf")
        if values.get("last_change_day") is not None:
            values["last_change_day"] = pd.Timestamp(values["last_change_day"])
        return cls(**values)


@dataclass(frozen=True, slots=True)
class DailyHighHedgeResult:

    benchmark: str
    spot_index: str
    future_family: str
    contract: str
    contract_size: int
    stock_value: float
    short_cash: float
    short_value_after_beta: float
    beta_rate: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
