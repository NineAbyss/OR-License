
from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any

import pandas as pd

from quant_pro.adapters.backtrader.strategies.dailyhigh_neutral import (
    DailyHighNeutralStrategy,
    future_target_sizes_for_positions,
    is_index_future,
)

logger = logging.getLogger(__name__)

STOCK_EXECUTION_RESERVE_RATE = 0.05
SINGLE_NAME_MAX_WEIGHT = 0.015




def feed_has_execution_bar(
    data: Any,
    *,
    signal_date: Any,
    execution_date: Any,
) -> bool:

    try:
        current = pd.Timestamp(data.datetime.date(0)).normalize()
        following = pd.Timestamp(data.datetime.date(1)).normalize()
        current_close = float(data.close[0])
        following_open = float(data.open[1])
    except (IndexError, TypeError, ValueError, OverflowError):
        return False
    return bool(
        current == pd.Timestamp(signal_date).normalize()
        and following == pd.Timestamp(execution_date).normalize()
        and math.isfinite(current_close)
        and current_close > 0.0
        and math.isfinite(following_open)
        and following_open > 0.0
    )


class SingleSIFBeta0NextMonthStrategy(DailyHighNeutralStrategy):

    def __init__(self) -> None:
        super().__init__()
        self._transition_started_on: pd.Timestamp | None = None
        self._transition_execution_date: pd.Timestamp | None = None
        self._transition_compatibility_snapshot: dict[str, Any] | None = None
        self._legacy_stock_value = 0.0
        self._effective_stock_value = 0.0
        self._stock_allocation_shortfall = 0.0
        self._target_repair_metadata: dict[str, Any] = {}
        self._daily_nav_records: list[dict[str, float | str]] = []
        self._daily_nav_dates: set[str] = set()

    def _persist_performance(self) -> None:
        state_path = getattr(self, "_state_path", None)
        if state_path is None or not self._daily_nav_records:
            return
        path = Path(state_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        frame = pd.DataFrame(self._daily_nav_records)
        frame.to_csv(path.parent / "daily_nav_and_returns.csv", index=False)
        returns = pd.to_numeric(frame["daily_return"], errors="coerce").dropna()
        if len(returns) > 1:
            returns = returns.iloc[1:]
        nav = pd.to_numeric(frame["nav"], errors="coerce").dropna()
        initial_nav = float(nav.iloc[0]) if not nav.empty else None
        final_nav = float(nav.iloc[-1]) if not nav.empty else None
        cumulative_return = (
            final_nav / initial_nav - 1.0
            if initial_nav and final_nav is not None
            else None
        )
        annualized_sharpe = None
        if len(returns) > 1 and float(returns.std(ddof=1)) > 0.0:
            annualized_sharpe = float(
                returns.mean() / returns.std(ddof=1) * math.sqrt(252.0)
            )
        summary = {
            "start_date": str(frame["date"].iloc[0]),
            "end_date": str(frame["date"].iloc[-1]),
            "observation_count": int(len(frame)),
            "initial_nav": initial_nav,
            "final_nav": final_nav,
            "cumulative_return": cumulative_return,
            "annualized_sharpe": annualized_sharpe,
            "max_drawdown": float(frame["drawdown"].min()),
        }
        temporary = path.parent / "performance_summary.json.tmp"
        temporary.write_text(
            json.dumps(summary, ensure_ascii=False, allow_nan=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path.parent / "performance_summary.json")

    def _record_daily_nav(self, current_date: pd.Timestamp) -> None:
        date_text = current_date.strftime("%Y-%m-%d")
        if date_text in self._daily_nav_dates:
            return
        nav = float(self.broker.getvalue())
        if not math.isfinite(nav):
            raise RuntimeError(f"non-finite broker NAV on {date_text}: {nav}")
        previous = (
            float(self._daily_nav_records[-1]["nav"])
            if self._daily_nav_records
            else nav
        )
        daily_return = nav / previous - 1.0 if previous != 0.0 else 0.0
        prior_peak = max(
            [float(item["nav"]) for item in self._daily_nav_records] + [nav]
        )
        drawdown = nav / prior_peak - 1.0 if prior_peak != 0.0 else 0.0
        previous_cumulative = (
            float(self._daily_nav_records[-1]["cumulative_return"])
            if self._daily_nav_records
            else 0.0
        )
        self._daily_nav_records.append(
            {
                "date": date_text,
                "nav": nav,
                "daily_return": daily_return,
                "cumulative_return": (1.0 + previous_cumulative)
                * (1.0 + daily_return)
                - 1.0,
                "drawdown": drawdown,
            }
        )
        self._daily_nav_dates.add(date_text)
        self._persist_performance()

    def _begin_transition(self) -> None:
        super()._begin_transition()
        self._transition_started_on = self._today()
        self._transition_compatibility_snapshot = {
            "legacy_stock_value": self._legacy_stock_value,
            "effective_stock_value": self._effective_stock_value,
            "stock_allocation_shortfall": self._stock_allocation_shortfall,
            "target_repair": dict(self._target_repair_metadata),
        }

    def _commit_transition_if_complete(self) -> None:
        super()._commit_transition_if_complete()
        if self._transition_snapshot is None:
            self._transition_started_on = None
            self._transition_execution_date = None
            self._transition_compatibility_snapshot = None

    def _abort_transition_without_orders(self) -> None:
        super()._abort_transition_without_orders()
        if self._transition_compatibility_snapshot is not None:
            snapshot = self._transition_compatibility_snapshot
            self._legacy_stock_value = float(snapshot["legacy_stock_value"])
            self._effective_stock_value = float(snapshot["effective_stock_value"])
            self._stock_allocation_shortfall = float(
                snapshot["stock_allocation_shortfall"]
            )
            self._target_repair_metadata = dict(snapshot["target_repair"])
        self._transition_compatibility_snapshot = None
        self._transition_started_on = None
        self._transition_execution_date = None

    def _persist_state(self, current_date: Any) -> None:
        super()._persist_state(current_date)
        state_path = getattr(self, "_state_path", None)
        if state_path is None or not Path(state_path).exists():
            return
        path = Path(state_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["compatibility_execution"] = {
            "stock_execution_reserve_rate": (
                0.0 if getattr(self.initial_optimizer, "agent_controls_hedge", False)
                else STOCK_EXECUTION_RESERVE_RATE
            ),
            "legacy_stock_value": self._legacy_stock_value,
            "effective_stock_value": self._effective_stock_value,
            "stock_allocation_shortfall": self._stock_allocation_shortfall,
            "valuation_basis": "signal_close_no_execution_open_lookahead",
            "target_repair": self._target_repair_metadata,
        }
        temporary = path.with_suffix(path.suffix + ".compat.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)
        self._persist_performance()

    def _apply_stock_execution_reserve(
        self, hedge: Any, optimizer: Any, current_date: pd.Timestamp
    ) -> Any:
        self._effective_stock_value = float(hedge.stock_value)
        self._legacy_stock_value = self._effective_stock_value
        self._stock_allocation_shortfall = 0.0
        return hedge

    def _pending_order_details(self) -> list[dict[str, Any]]:
        return self._order_details(self._pending_transition_orders)

    def _order_details(self, orders: dict[int, Any]) -> list[dict[str, Any]]:
        details: list[dict[str, Any]] = []
        for reference, order in sorted(orders.items()):
            data = getattr(order, "data", None)
            status_name = getattr(order, "getstatusname", None)
            created = getattr(order, "created", None)
            details.append(
                {
                    "ref": reference,
                    "instrument": str(getattr(data, "_name", "")),
                    "status": (
                        str(status_name()) if callable(status_name) else "unknown"
                    ),
                    "requested_size": float(getattr(created, "size", 0.0)),
                    "current_position": float(self.getposition(data).size) if data is not None else 0.0,
                }
            )
        return details

    def _assert_no_stale_transition(self, today: pd.Timestamp) -> None:
        if self._transition_snapshot is None:
            return
        execution = self._transition_execution_date
        if execution is not None and today >= execution:
            pending = self._pending_order_details()
            compensation = sorted(self._compensation_orders)
            raise RuntimeError(
                "single_SIF_beta0_next_month transition did not reach a terminal "
                f"state by {execution.date()}; pending_order_refs={pending}, "
                "compensation_orders="
                f"{self._order_details(self._compensation_orders)}, "
                f"compensation_order_refs={compensation}, "
                f"status={self._transition_status!r}"
            )

    def notify_order(self, order: Any) -> None:
        reference = int(order.ref)
        status_name = str(order.getstatusname())
        if status_name == "Margin" and reference in self._pending_transition_orders:
            logger.warning(
                "next-month transition order not fully filled for lack of cash: %s "
                "broker_cash=%.2f broker_value=%.2f",
                self._order_details({reference: order})[0],
                float(self.broker.getcash()),
                float(self.broker.getvalue()),
            )
            self._pending_transition_orders.pop(reference, None)
            self._commit_transition_if_complete()
            self._sync_executed_future_state()
            self._persist_state(self._today())
            return
        failed = status_name in {"Canceled", "Margin", "Rejected", "Expired"}
        if failed and reference in self._pending_transition_orders:
            logger.error(
                "next-month transition order failed: %s broker_cash=%.2f broker_value=%.2f",
                self._order_details({reference: order})[0],
                float(self.broker.getcash()),
                float(self.broker.getvalue()),
            )
        elif failed and reference in self._compensation_orders:
            logger.error(
                "next-month compensation order failed: %s broker_cash=%.2f broker_value=%.2f",
                self._order_details({reference: order})[0],
                float(self.broker.getcash()),
                float(self.broker.getvalue()),
            )
        super().notify_order(order)

    def _plan_stock_targets(
        self,
        todo: pd.DataFrame | None,
        hedge: Any,
        *,
        signal_date: pd.Timestamp,
        execution_date: pd.Timestamp,
    ) -> tuple[dict[str, int], list[str], list[str]]:
        held = {
            str(getattr(data, "_name", "")): float(position.size)
            for data, position in self.broker.positions.items()
            if position.size != 0
            and not is_index_future(str(getattr(data, "_name", "")))
        }
        if todo is None:
            return {}, sorted(held), []
        raw_weights = (
            todo[["instrument", "weight"]]
            .assign(instrument=lambda frame: frame["instrument"].map(str))
            .groupby("instrument", sort=True)["weight"]
            .sum()
        )
        solver_metadata = dict(todo.attrs.get("legacy_gurobi", {}))
        executable_names: set[str] = set()
        frozen: list[str] = []
        skipped_new: list[str] = []
        for instrument in sorted(set(held) | set(raw_weights.index)):
            data = self.getdatabyname(instrument)
            if data is None:
                raise KeyError(f"stock feed not found: {instrument}")
            if feed_has_execution_bar(
                data,
                signal_date=signal_date,
                execution_date=execution_date,
            ):
                executable_names.add(instrument)
            elif instrument in held:
                frozen.append(instrument)
            else:
                skipped_new.append(instrument)

        frozen_value = 0.0
        for instrument in frozen:
            data = self.getdatabyname(instrument)
            frozen_value += float(held[instrument]) * float(data.close[0])
        stock_value = float(hedge.stock_value)
        available_value = stock_value - frozen_value
        if available_value <= 0.0:
            raise ValueError(
                "frozen stock holdings exhaust the signal-close stock budget"
            )
        candidate_weights = raw_weights.reindex(
            sorted(executable_names & set(raw_weights.index))
        ).dropna().clip(lower=0.0)
        candidate_weights = candidate_weights[candidate_weights > 0.0]
        if candidate_weights.empty:
            raise ValueError("legacy stock target has no executable positive weights")
        projected = candidate_weights

        prices: dict[str, float] = {}
        target_sizes: dict[str, int] = {
            instrument: 0
            for instrument in executable_names
            if instrument not in projected.index
        }
        for instrument, weight in projected.items():
            data = self.getdatabyname(instrument)
            price = float(data.close[0])
            if not math.isfinite(price) or price <= 0.0:
                raise ValueError(f"invalid signal-close stock price: {instrument}={price}")
            prices[instrument] = price
            ideal = float(weight) * stock_value
            target_sizes[instrument] = int(ideal / price)
        integer_value = sum(
            float(target_sizes[name]) * prices[name] for name in projected.index
        )
        remaining_value = available_value - integer_value
        self._target_repair_metadata = {
            "signal_date": signal_date.strftime("%Y-%m-%d"),
            "input_weight_sum": float(pd.to_numeric(raw_weights).sum()),
            "input_max_weight": float(pd.to_numeric(raw_weights).max()),
            "projected_weight_sum": float(projected.sum()),
            "projected_max_weight": float(projected.max()),
            "single_name_max_weight": SINGLE_NAME_MAX_WEIGHT,
            "integer_target_value": integer_value + frozen_value,
            "integer_target_weight": (integer_value + frozen_value) / stock_value,
            "integer_residual_cash": remaining_value,
            "target_position_count": sum(size > 0 for size in target_sizes.values())
            + len(frozen),
            "solver_selected_count": solver_metadata.get("selected_count"),
            "solver_status": solver_metadata.get("status"),
            "frozen_position_count": len(frozen),
            "skipped_new_count": len(skipped_new),
        }
        return target_sizes, frozen, skipped_new

    def _plan_future_targets(
        self,
        hedge: Any,
        *,
        signal_date: pd.Timestamp,
        execution_date: pd.Timestamp,
    ) -> dict[str, int]:
        targets = future_target_sizes_for_positions(
            self._actual_future_positions(), hedge
        )
        missing: list[str] = []
        for instrument in targets:
            data = self.getdatabyname(instrument)
            if data is None or not feed_has_execution_bar(
                data,
                signal_date=signal_date,
                execution_date=execution_date,
            ):
                missing.append(instrument)
        if missing:
            raise RuntimeError(
                "next-month futures transition has no required execution bar for "
                f"{sorted(missing)} on {execution_date.date()}"
            )
        return targets

    def next(self) -> None:
        if not self._master_data_ready():
            return
        today = self._today()
        self._record_daily_nav(today)
        self._assert_no_stale_transition(today)
        if today not in self.trade_dates:
            return
        next_trade_date = self._next_trade_date()
        if next_trade_date is None:
            logger.warning(
                "next-month strategy has no execution date after %s; signal not submitted",
                today,
            )
            return
        if self._transition_snapshot is not None:
            raise RuntimeError(
                "single_SIF_beta0_next_month received a new signal while the previous "
                f"transition is unfinished; signal_date={today.date()}, "
                f"pending_order_refs={sorted(self._pending_transition_orders)}"
            )

        margin_rate = self._allocation_margin_rate(next_trade_date)
        score = self._score_payload(today)
        bond, bond_table = self._bond_data(today)
        total_value = float(self.broker.getvalue())
        self._begin_transition()
        self._transition_execution_date = next_trade_date
        try:
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
                    optimizer.last_hedge_result = None
                    raise RuntimeError(
                        f"next-month initial optimization failed on {today.date()}"
                    )
            else:
                optimizer = self.rebalance_optimizer
                current_long_rate = 1.0 / (margin_rate * 1.05 + 0.1 * 1.05 + 1.0)
                current_stock_value = total_value * current_long_rate
                todo = optimizer.optimize(
                    pred=score,
                    bond=bond,
                    total_value=total_value,
                    position=self._stock_position_frame(current_stock_value),
                    bond_table=bond_table,
                    current_date=today,
                    margin_rate=margin_rate,
                )

            if todo is None and self._initialized and getattr(optimizer, "agent_controls_hedge", False):
                self._abort_transition_without_orders()
                self._persist_state(today)
                return
            hedge = self._apply_stock_execution_reserve(
                self._typed_hedge(optimizer), optimizer, today
            )
            stock_targets, frozen, skipped_new = self._plan_stock_targets(
                todo,
                hedge,
                signal_date=today,
                execution_date=next_trade_date,
            )
            future_targets = self._plan_future_targets(
                hedge,
                signal_date=today,
                execution_date=next_trade_date,
            )
        except Exception:
            self._abort_transition_without_orders()
            raise
        if frozen or skipped_new:
            logger.warning(
                "next-month execution-bar filter on %s -> %s: frozen_held=%s skipped_new=%s",
                today.date(),
                next_trade_date.date(),
                frozen,
                skipped_new,
            )

        stock_reductions: list[tuple[str, int]] = []
        stock_increases: list[tuple[str, int]] = []
        for instrument, target in stock_targets.items():
            data = self.getdatabyname(instrument)
            current_size = int(self.getposition(data).size)
            bucket = stock_reductions if target < current_size else stock_increases
            bucket.append((instrument, target))
        current_futures = self._actual_future_positions()
        future_reductions: list[tuple[str, int]] = []
        future_increases: list[tuple[str, int]] = []
        for instrument, target in future_targets.items():
            current = float(current_futures.get(instrument, 0.0))
            bucket = (
                future_reductions
                if abs(float(target)) < abs(current) or (current * float(target) < 0)
                else future_increases
            )
            bucket.append((instrument, target))

        for instrument, target in sorted(stock_reductions):
            order = self.order_target_size(
                data=self.getdatabyname(instrument), target=target
            )
            self.order_list.append(order)
            self._track_transition_order(order)
        for instrument, target in sorted(future_reductions):
            order = self.order_target_size(
                data=self.getdatabyname(instrument), target=target
            )
            self.order_list.append(order)
            self._track_transition_order(order)
        for instrument, target in sorted(future_increases):
            order = self.order_target_size(
                data=self.getdatabyname(instrument), target=target
            )
            self.order_list.append(order)
            self._track_transition_order(order)
        for instrument, target in sorted(stock_increases):
            order = self.order_target_size(
                data=self.getdatabyname(instrument), target=target
            )
            self.order_list.append(order)
            self._track_transition_order(order)

        self._last_hedge = hedge
        self._initialized = True
        self._commit_transition_if_complete()
        self._persist_state(today)


__all__ = (
    "STOCK_EXECUTION_RESERVE_RATE",
    "SINGLE_NAME_MAX_WEIGHT",
    "SingleSIFBeta0NextMonthStrategy",
    "feed_has_execution_bar",
)
