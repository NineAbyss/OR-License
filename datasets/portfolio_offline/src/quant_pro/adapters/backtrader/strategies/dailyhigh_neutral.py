
from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any

import backtrader as bt
import pandas as pd

from quant_pro.adapters.optimizers.dailyhigh import DailyHighHedgeResult, DailyHighState
from quant_pro.application.optimization.score_inputs import (
    expand_weight_pivots,
    infer_period_num_from_tuning_params,
)
from quant_pro.application.services.optimizer_service import get_optimizer

logger = logging.getLogger(__name__)

_FUTURE_FAMILIES = ("IF", "IC", "IM")


def is_index_future(instrument: str) -> bool:
    value = str(instrument)
    return value.startswith(_FUTURE_FAMILIES) and len(value) > 2 and value[2].isdigit()


def stock_target_values(
    weights: pd.DataFrame,
    hedge: DailyHighHedgeResult,
) -> dict[str, float]:

    return {
        str(row.instrument): float(row.weight) * hedge.stock_value
        for row in weights[["instrument", "weight"]].itertuples(index=False)
        if float(row.weight) > 0
    }


def future_target_sizes(
    previous_contract: str | None,
    hedge: DailyHighHedgeResult,
) -> dict[str, int]:

    targets: dict[str, int] = {}
    if previous_contract is not None and previous_contract != hedge.contract:
        targets[previous_contract] = 0
    targets[hedge.contract] = -int(hedge.contract_size)
    return targets


def future_target_sizes_for_positions(
    actual_positions: dict[str, float],
    hedge: DailyHighHedgeResult,
) -> dict[str, int]:

    targets = {
        contract: 0
        for contract, size in actual_positions.items()
        if size != 0 and contract != hedge.contract
    }
    targets[hedge.contract] = -int(hedge.contract_size)
    return targets


class DailyHighNeutralStrategy(bt.Strategy):

    params = (
        ("weight", None),
        ("tuning_params_list", None),
        ("initial_optimizer_instance_id", ""),
        ("rebalance_optimizer_instance_id", ""),
        ("optimizer_initial", None),
        ("optimizer_rebalance", None),
        ("persist_path", ""),
        ("state_path", None),
        ("margin_rate_provider", None),
    )

    def __init__(self) -> None:
        super().__init__()
        self.initial_optimizer = self._resolve_optimizer(
            self.p.optimizer_initial, self.p.initial_optimizer_instance_id
        )
        self.rebalance_optimizer = self._resolve_optimizer(
            self.p.optimizer_rebalance, self.p.rebalance_optimizer_instance_id
        )
        if self.initial_optimizer is None or self.rebalance_optimizer is None:
            raise ValueError("DailyHigh neutral strategy requires both optimizers")

        params = self.p.tuning_params_list or []
        for optimizer in (self.initial_optimizer, self.rebalance_optimizer):
            setter = getattr(optimizer, "set_tuning_params_list", None)
            if params and callable(setter):
                setter(params)

        period_num = infer_period_num_from_tuning_params(params)
        self._weight_periods = self._normalize_weights(self.p.weight, period_num)
        self.trade_dates = {
            pd.Timestamp(value).normalize()
            for frame in self._weight_periods
            for value in frame.index
        }
        self._initialized = False
        self._executed_future_contract: str | None = None
        self._last_hedge: DailyHighHedgeResult | None = None
        self._state_path = self._resolve_state_path()
        engine = getattr(self.initial_optimizer, "engine", None)
        self.margin_rate_provider = self.p.margin_rate_provider or getattr(
            engine, "future_data_fetcher", None
        )
        if self.margin_rate_provider is None:
            raise ValueError("DailyHigh strategy requires a margin-rate provider")
        self.order_list: list[Any] = []
        self._pending_transition_orders: dict[int, Any] = {}
        self._compensation_orders: dict[int, Any] = {}
        self._transition_snapshot: dict[str, Any] | None = None
        self._transition_status: str | None = None

    @staticmethod
    def _resolve_optimizer(direct: Any, optimizer_id: str) -> Any:
        if direct is not None:
            return direct
        if optimizer_id:
            return get_optimizer(str(optimizer_id))
        return None

    @staticmethod
    def _normalize_weights(weight: Any, period_num: int) -> list[pd.DataFrame]:
        frames = expand_weight_pivots(weight, period_num=period_num)
        normalized: list[pd.DataFrame] = []
        for frame in frames:
            copy = frame.copy()
            copy.index = pd.to_datetime(copy.index).normalize()
            normalized.append(copy.sort_index())
        return normalized

    def _resolve_state_path(self) -> Path | None:
        if self.p.state_path:
            return Path(str(self.p.state_path))
        if self.p.persist_path:
            return Path(str(self.p.persist_path)) / "dailyhigh_neutral_state.json"
        return None

    def start(self) -> None:
        super().start()
        self._restore_state()

    def _restore_state(self) -> None:
        if self._state_path is None or not self._state_path.exists():
            return
        payload = json.loads(self._state_path.read_text(encoding="utf-8"))
        state = DailyHighState.from_dict(payload["dailyhigh_state"])
        for optimizer in (self.initial_optimizer, self.rebalance_optimizer):
            engine = getattr(optimizer, "engine", None)
            if engine is None:
                raise TypeError("registered DailyHigh optimizer has no neutral engine")
            engine.state = state
        self._initialized = bool(payload.get("initialized", False))
        self._executed_future_contract = payload.get("executed_future_contract")
        saved_hedge = payload.get("last_hedge")
        if isinstance(saved_hedge, dict):
            self._last_hedge = DailyHighHedgeResult(**saved_hedge)

    def _persist_state(self, current_date: Any) -> None:
        if self._state_path is None:
            return
        if self._transition_snapshot is not None:
            state = DailyHighState.from_dict(
                self._transition_snapshot["dailyhigh_state"]
            )
            initialized = bool(self._transition_snapshot["initialized"])
            last_hedge = self._transition_snapshot["last_hedge"]
        else:
            state = getattr(self.rebalance_optimizer, "state", None)
            if state is None:
                state = getattr(self.initial_optimizer, "state", None)
            if not isinstance(state, DailyHighState):
                raise TypeError("registered DailyHigh optimizer exposes no DailyHighState")
            initialized = self._initialized
            last_hedge = self._last_hedge
        actual_futures = self._sync_executed_future_state()
        payload = {
            "date": pd.Timestamp(current_date).strftime("%Y-%m-%d"),
            "initialized": initialized,
            "transition_status": self._transition_status,
            "executed_future_contract": self._executed_future_contract,
            "executed_future_positions": actual_futures,
            "actual_stock_positions": self._actual_stock_positions(),
            "last_hedge": last_hedge.to_dict() if last_hedge else None,
            "dailyhigh_state": state.to_dict(),
        }
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._state_path.with_suffix(self._state_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self._state_path)

    def _today(self) -> pd.Timestamp:
        return pd.Timestamp(self.datas[0].datetime.date(0)).normalize()

    def _master_data_ready(self) -> bool:
        if not self.datas or len(self.datas[0]) <= 0:
            return False
        try:
            timestamp = float(self.datas[0].datetime[0])
        except (IndexError, TypeError, ValueError):
            return False
        return math.isfinite(timestamp) and timestamp > 0

    def _next_trade_date(self) -> pd.Timestamp | None:
        try:
            return pd.Timestamp(self.datas[0].datetime.date(1)).normalize()
        except Exception:
            return None

    def _allocation_margin_rate(self, next_trade_date: pd.Timestamp) -> float:
        family = str(self.initial_optimizer.engine.spec.future_family)
        provider = self.margin_rate_provider
        getter = getattr(provider, "get_allocation_margin_rate", None)
        if callable(getter):
            return float(getter(next_trade_date, family))
        if callable(provider):
            return float(provider(next_trade_date, family))
        raise TypeError("margin-rate provider must be callable or expose get_allocation_margin_rate")

    def _score_payload(self, today: pd.Timestamp) -> pd.DataFrame | list[pd.DataFrame]:
        frames: list[pd.DataFrame] = []
        for weights in self._weight_periods:
            row = weights.loc[today].dropna().sort_values(ascending=False)
            frames.append(
                pd.DataFrame(
                    {
                        "datetime": today.strftime("%Y-%m-%d"),
                        "instrument": row.index.astype(str),
                        "score": row.to_numpy(),
                    }
                )
            )
        return frames[0] if len(frames) == 1 else frames

    @staticmethod
    def _bond_data(today: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
        frame = pd.DataFrame(
            {
                "cre_time": [today.strftime("%Y-%m-%d")],
                "instrument": ["SZ000001"],
                "available": [10_000],
                "apply_rate": [0.1],
                "id": [int(today.strftime("%Y%m%d") + "0000010")],
            }
        )
        return frame.set_index("cre_time"), frame.set_index("id").drop(columns="cre_time")

    def _stock_position_frame(self, stock_value: float) -> pd.DataFrame:
        rows: list[dict[str, Any]] = []
        denominator = stock_value if stock_value > 0 else 1.0
        for data, position in self.broker.positions.items():
            name = str(getattr(data, "_name", ""))
            if not name or is_index_future(name) or position.size == 0:
                continue
            close = float(data.close[0])
            rows.append(
                {
                    "stockcode": name,
                    "volume": float(position.size),
                    "weight": float(position.size) * close / denominator,
                    "close": close,
                    "apply_rate": 0.0,
                }
            )
        return pd.DataFrame(
            rows,
            columns=["stockcode", "volume", "weight", "close", "apply_rate"],
        )

    @staticmethod
    def _typed_hedge(optimizer: Any) -> DailyHighHedgeResult:
        hedge = getattr(optimizer, "last_hedge_result", None)
        if not isinstance(hedge, DailyHighHedgeResult):
            raise TypeError("DailyHigh optimizer did not produce a structured hedge result")
        return hedge

    def _submit_stock_targets(
        self,
        todo: pd.DataFrame | None,
        hedge: DailyHighHedgeResult,
    ) -> None:
        if todo is None:
            return
        targets = stock_target_values(todo, hedge)
        held = {
            str(getattr(data, "_name", ""))
            for data, position in self.broker.positions.items()
            if position.size != 0 and not is_index_future(str(getattr(data, "_name", "")))
        }
        for instrument in sorted(held - set(targets)):
            order = self.order_target_value(data=self.getdatabyname(instrument), target=0.0)
            self.order_list.append(order)
            self._track_transition_order(order)
        for instrument, target in sorted(targets.items()):
            data = self.getdatabyname(instrument)
            if data is None:
                raise KeyError(f"stock feed not found: {instrument}")
            order = self.order_target_value(data=data, target=target)
            self.order_list.append(order)
            self._track_transition_order(order)

    def _submit_future_targets(self, hedge: DailyHighHedgeResult) -> None:
        targets = future_target_sizes_for_positions(self._actual_future_positions(), hedge)
        for instrument, target in targets.items():
            data = self.getdatabyname(instrument)
            if data is None:
                raise KeyError(f"future feed not found: {instrument}")
            order = self.order_target_size(data=data, target=target)
            self.order_list.append(order)
            self._track_transition_order(order)

    def _track_transition_order(self, order: Any) -> None:
        if order is not None:
            self._pending_transition_orders[int(order.ref)] = order

    def _actual_stock_positions(self) -> dict[str, float]:
        positions: dict[str, float] = {}
        for data, position in self.broker.positions.items():
            name = str(getattr(data, "_name", ""))
            if name and not is_index_future(name) and position.size != 0:
                positions[name] = float(position.size)
        return positions

    def _actual_future_positions(self) -> dict[str, float]:
        positions: dict[str, float] = {}
        for data, position in self.broker.positions.items():
            name = str(getattr(data, "_name", ""))
            if is_index_future(name) and position.size != 0:
                positions[name] = float(position.size)
        return positions

    def _sync_executed_future_state(self) -> dict[str, float]:
        positions = self._actual_future_positions()
        if not positions:
            self._executed_future_contract = None
        elif self._last_hedge is not None and self._last_hedge.contract in positions:
            self._executed_future_contract = self._last_hedge.contract
        else:
            self._executed_future_contract = sorted(positions)[0]
        return positions

    def _restore_optimizer_state(self, payload: dict[str, Any]) -> None:
        state = DailyHighState.from_dict(payload)
        for optimizer in (self.initial_optimizer, self.rebalance_optimizer):
            optimizer.engine.state = state

    def _begin_transition(self) -> None:
        if (
            self._transition_snapshot is not None
            or self._pending_transition_orders
            or self._compensation_orders
        ):
            raise RuntimeError("DailyHigh still has an unfinished order transition")
        state = getattr(self.initial_optimizer, "state", None)
        if not isinstance(state, DailyHighState):
            raise TypeError("registered DailyHigh optimizer exposes no DailyHighState")
        self._transition_snapshot = {
            "dailyhigh_state": state.to_dict(),
            "initialized": self._initialized,
            "last_hedge": self._last_hedge,
            "stock_positions": self._actual_stock_positions(),
            "future_positions": self._actual_future_positions(),
        }
        self._transition_status = "pending"

    def _restore_transition_state(self) -> None:
        if self._transition_snapshot is None:
            return
        self._restore_optimizer_state(self._transition_snapshot["dailyhigh_state"])
        self._initialized = bool(self._transition_snapshot["initialized"])
        self._last_hedge = self._transition_snapshot["last_hedge"]

    def _abort_transition_without_orders(self) -> None:
        self._restore_transition_state()
        self._transition_snapshot = None
        self._transition_status = None

    def _commit_transition_if_complete(self) -> None:
        if not self._pending_transition_orders:
            self._transition_snapshot = None
            self._transition_status = None

    @staticmethod
    def _positions_equal(
        actual: dict[str, float],
        expected: dict[str, float],
    ) -> bool:
        instruments = set(actual) | set(expected)
        return all(
            abs(float(actual.get(name, 0.0)) - float(expected.get(name, 0.0))) < 1e-9
            for name in instruments
        )

    def _positions_match_snapshot(self) -> bool:
        if self._transition_snapshot is None:
            return True
        return self._positions_equal(
            self._actual_stock_positions(),
            self._transition_snapshot["stock_positions"],
        ) and self._positions_equal(
            self._actual_future_positions(),
            self._transition_snapshot["future_positions"],
        )

    def _submit_compensation_orders(self) -> None:
        if self._transition_snapshot is None:
            return
        expected_stock = self._transition_snapshot["stock_positions"]
        expected_future = self._transition_snapshot["future_positions"]
        actual_stock = self._actual_stock_positions()
        actual_future = self._actual_future_positions()
        targets = [
            (instrument, float(expected_stock.get(instrument, 0.0)))
            for instrument in sorted(set(actual_stock) | set(expected_stock))
            if abs(
                float(actual_stock.get(instrument, 0.0))
                - float(expected_stock.get(instrument, 0.0))
            )
            >= 1e-9
        ]
        targets.extend(
            (instrument, float(expected_future.get(instrument, 0.0)))
            for instrument in sorted(set(actual_future) | set(expected_future))
            if abs(
                float(actual_future.get(instrument, 0.0))
                - float(expected_future.get(instrument, 0.0))
            )
            >= 1e-9
        )
        for instrument, target in targets:
            data = self.getdatabyname(instrument)
            if data is None:
                raise KeyError(f"compensation feed not found: {instrument}")
            order = self.order_target_size(data=data, target=target)
            self.order_list.append(order)
            if order is not None:
                self._compensation_orders[int(order.ref)] = order

    def _finish_recovery_if_restored(self) -> None:
        if self._compensation_orders or self._transition_snapshot is None:
            return
        if self._positions_match_snapshot():
            self._transition_snapshot = None
            self._transition_status = None
            return
        self._submit_compensation_orders()
        if not self._compensation_orders:
            self._transition_status = "recovery_failed"

    def _fail_transition(self) -> None:
        outstanding = list(self._pending_transition_orders.values())
        self._pending_transition_orders.clear()
        self._restore_transition_state()
        self._transition_status = "recovering"
        for order in outstanding:
            self.cancel(order)
        self._submit_compensation_orders()
        self._finish_recovery_if_restored()

    def next(self) -> None:
        if not self._master_data_ready():
            return
        today = self._today()
        if today not in self.trade_dates:
            return
        next_trade_date = self._next_trade_date()
        if next_trade_date is None:
            logger.warning("DailyHigh has no next trade date after %s; no orders submitted", today)
            return
        margin_rate = self._allocation_margin_rate(next_trade_date)
        score = self._score_payload(today)
        bond, bond_table = self._bond_data(today)
        total_value = float(self.broker.getvalue())
        if self._transition_snapshot is not None:
            logger.warning("DailyHigh transition still pending on %s; signal skipped", today)
            return
        self._begin_transition()

        if not self._initialized:
            optimizer = self.initial_optimizer
            todo = optimizer.optimize(
                pred=score,
                bond=bond,
                total_value=total_value,
                current_date=today,
                margin_rate=margin_rate,
            )
            if todo is None:
                self._abort_transition_without_orders()
                optimizer.last_hedge_result = None
                logger.error("DailyHigh initial stock optimization failed; no orders submitted")
                return
        else:
            optimizer = self.rebalance_optimizer
            previous_stock_value = (
                self._last_hedge.stock_value if self._last_hedge is not None else total_value
            )
            todo = optimizer.optimize(
                pred=score,
                bond=bond,
                total_value=total_value,
                position=self._stock_position_frame(previous_stock_value),
                bond_table=bond_table,
                current_date=today,
                margin_rate=margin_rate,
            )

        hedge = self._typed_hedge(optimizer)
        self._submit_stock_targets(todo, hedge)
        self._submit_future_targets(hedge)
        self._last_hedge = hedge
        self._initialized = True
        self._commit_transition_if_complete()
        self._persist_state(today)

    def prenext(self) -> None:
        if self._master_data_ready():
            self.next()

    def notify_order(self, order: Any) -> None:
        terminal = {
            bt.Order.Completed,
            bt.Order.Canceled,
            bt.Order.Margin,
            bt.Order.Rejected,
            bt.Order.Expired,
        }
        if order.status not in terminal:
            return
        reference = int(order.ref)
        if reference in self._pending_transition_orders:
            self._pending_transition_orders.pop(reference, None)
            if order.status == bt.Order.Completed:
                self._commit_transition_if_complete()
            else:
                self._fail_transition()
        elif reference in self._compensation_orders:
            self._compensation_orders.pop(reference, None)
            if order.status == bt.Order.Completed:
                self._finish_recovery_if_restored()
            else:
                remaining = list(self._compensation_orders.values())
                self._compensation_orders.clear()
                for outstanding in remaining:
                    self.cancel(outstanding)
                self._transition_status = "recovery_failed"
        self._sync_executed_future_state()
        self._persist_state(self._today())

    def stop(self) -> None:
        if self._state_path is not None and (
            self._initialized
            or self._transition_snapshot is not None
            or self._state_path.exists()
        ):
            self._persist_state(self._today())


__all__ = (
    "DailyHighNeutralStrategy",
    "future_target_sizes",
    "future_target_sizes_for_positions",
    "is_index_future",
    "stock_target_values",
)
