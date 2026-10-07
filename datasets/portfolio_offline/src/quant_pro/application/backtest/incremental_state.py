
from __future__ import annotations

import logging
import os
import pickle
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


def resolve_daily_state_path(
    incremental_state_path: str | None,
    daily_state_path: str | None,
) -> str | None:
    if daily_state_path is not None or not incremental_state_path:
        return daily_state_path
    return os.path.dirname(os.path.abspath(incremental_state_path)) or "."


@dataclass
class IncrementalBacktestState:

    state_file_path: str
    state: dict[str, Any] = field(
        default_factory=lambda: {
            "last_date": None,
            "broker_state": {},
            "strategy_state": {},
            "sr_state": {},
            "historical_returns": [],
            "historical_positions": [],
            "historical_transactions": [],
            "config": {},
        }
    )


    def save_broker_state(
        self,
        cash: float,
        value: float,
        positions: dict[str, dict[str, float]],
        *,
        fundshares: float = 1.0,
        fundval: float = 100.0,
    ) -> None:
        self.state["broker_state"] = {
            "cash": cash,
            "value": value,
            "positions": positions,
            "fundshares": fundshares,
            "fundval": fundval,
        }
        logger.info(
            "Broker state saved: cash=%.2f, positions=%d",
            cash,
            len(positions),
        )


    def save_strategy_state(
        self,
        prev_dt: str | None,
        init_position: bool,
        *,
        max_lever_rate: float = 0.0,
        closed_daily_interest: float = 0.0,
        loss_total: float = 0.0,
        gain_total: float = 0.0,
        prev_total_value: float | None = None,
        prev_real_value: float | None = None,
        initial_cash: float | None = None,
        prev_positions: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.state["strategy_state"] = {
            "prev_dt": prev_dt,
            "init_position": init_position,
            "max_lever_rate": max_lever_rate,
            "closed_daily_interest": closed_daily_interest,
            "loss_total": loss_total,
            "gain_total": gain_total,
            "prev_total_value": prev_total_value,
            "prev_real_value": prev_real_value,
            "initial_cash": initial_cash,
            "prev_positions": prev_positions or {},
        }
        if extra:
            self.state["strategy_state"].update(extra)
        logger.info("Strategy state saved: prev_dt=%s", prev_dt)


    def save_sr_state(
        self,
        size: dict[str, float],
        money: dict[str, float],
        apply_rate: dict[str, float],
        hold_days: dict[str, float],
        open_price: dict[str, float],
        instrument_id_set: dict[str, list[str]],
        *,
        exec_size: dict[str, float] | None = None,
    ) -> None:

        def _safe_copy(d: dict[str, Any]) -> dict[str, float]:
            result: dict[str, float] = {}
            for key, value in d.items():
                k = str(key)
                try:
                    result[k] = float(value)
                except (ValueError, TypeError):
                    result[k] = 0.0
            return result

        self.state["sr_state"] = {
            "size": _safe_copy(size),
            "money": _safe_copy(money),
            "apply_rate": _safe_copy(apply_rate),
            "hold_days": _safe_copy(hold_days),
            "open_price": _safe_copy(open_price),
            "exec_size": _safe_copy(exec_size or {}),
            "instrument_id_set": {k: list(v) for k, v in instrument_id_set.items()},
        }
        logger.info("SR state saved: %d positions", len(size))


    def save_daily_results(self, daily_return: float, date_str: str) -> None:
        self.state["historical_returns"].append(daily_return)
        self.state["last_date"] = date_str


    def save_to_file(self) -> None:
        os.makedirs(os.path.dirname(self.state_file_path) or ".", exist_ok=True)
        with open(self.state_file_path, "wb") as f:
            pickle.dump(self.state, f)
        logger.info("State saved to: %s", self.state_file_path)

    def load_from_file(self) -> bool:
        if not os.path.exists(self.state_file_path):
            logger.warning("State file not found: %s", self.state_file_path)
            return False

        try:
            with open(self.state_file_path, "rb") as f:
                self.state = pickle.load(f)
            logger.info("State loaded from: %s", self.state_file_path)
            return True
        except (pickle.UnpicklingError, EOFError, OSError) as exc:
            logger.error("Failed to load state: %s", exc)
            return False


    def get_last_date(self) -> str | None:
        return self.state.get("last_date")

    def get_broker_state(self) -> dict[str, Any]:
        result: dict[str, Any] = self.state.get("broker_state", {})
        return result

    def get_strategy_state(self) -> dict[str, Any]:
        result: dict[str, Any] = self.state.get("strategy_state", {})
        return result

    def get_sr_state(self) -> dict[str, Any]:
        result: dict[str, Any] = self.state.get("sr_state", {})
        return result

    def has_positions(self) -> bool:
        broker = self.state.get("broker_state", {})
        positions = broker.get("positions", {})
        return len(positions) > 0

    def get_historical_returns(self) -> list[float]:
        result: list[float] = self.state.get("historical_returns", [])
        return result
