
from __future__ import annotations

import logging
import os
from typing import Any

import backtrader as bt
import numpy as np
import pandas as pd

from quant_pro.adapters.backtrader.helpers import (
    get_positions,
    get_today_from_bt,
)
from quant_pro.adapters.backtrader.logging import bt_log, bt_to_log
from quant_pro.adapters.backtrader.strategies.incremental import IncrementalStrategy
from quant_pro.application.backtest.incremental_state import IncrementalBacktestState
from quant_pro.application.services.optimizer_service import (
    get_optimizer as get_optimizer_service,
)
from quant_pro.domain.strategy.limitation import Limitation
from quant_pro.domain.strategy.longshort.pnl import (
    calculate_holding_daily_pnl,
    calculate_trade_sequence_daily_pnl,
    finalize_stock_summary,
)
from quant_pro.domain.strategy.longshort.rebalance import (
    calculate_target_positions,
    generate_order_list,
    should_rebalance,
)
from quant_pro.domain.strategy.longshort.score_utils import prepare_score_data
from quant_pro.domain.strategy.longshort.trade_analysis import analyze_trade_type
from quant_pro.domain.strategy.optimizer_protocol import LongShortOptimizerProtocol
from quant_pro.domain.strategy.order_plan import (
    BuyOrderPlan,
    SellOrderPlan,
    generate_buy_orders,
    generate_sell_orders,
)
from quant_pro.domain.strategy.price_utils import get_none_close
from quant_pro.domain.strategy.volume_utils import (
    refine_buy_vol,
    refine_sell_vol,
    refine_short_buy_vol,
    refine_short_sell_vol,
)

logger = logging.getLogger(__name__)
progress_logger = logging.getLogger("quant_pro.backtest.progress")
_NO_RUNTIME_DEFAULT = object()
_RUNTIME_ATTR_MISSING = object()
_POSITION_FLAT_EPS = 1e-10
_POSITION_TINY_AUDIT_EPS = 1e-8
_POSITION_DUST_MARKET_VALUE_EPS = 1.0
_POSITION_INTEGRITY_ISSUE_COLUMNS = [
    "date",
    "phase",
    "issue_type",
    "instrument",
    "position_side",
    "broker_size",
    "broker_market_value",
    "strategy_long_size",
    "strategy_short_size",
    "bond_id",
]
_POSITION_INTEGRITY_CLEANUP_COLUMNS = [
    "date",
    "reason",
    "instrument",
    "broker_size_before",
    "broker_position_price_before",
    "broker_market_value_before",
    "broker_cash_adjustment",
    "price",
]



def read_close_prices(strategy: Any, instruments: list[str]) -> dict[str, float]:
    prices: dict[str, float] = {}
    for idx in instruments:
        try:
            prices[idx] = strategy.getdatabyname(idx).close[0]
        except (KeyError, IndexError, AttributeError) as exc:
            logger.debug("Price read failed for %s: %s", idx, exc)
            prices[idx] = 0.0
    return prices


def read_position_sizes(strategy: Any) -> dict[str, int]:
    result: dict[str, int] = {}
    for d, p in strategy.getpositions().items():
        if p.size != 0:
            result[d._name] = int(p.size)
    return result




def _load_filter_pool_csv(
    csv_path: str | None,
) -> dict[pd.Timestamp, tuple[str, ...]] | None:
    if not isinstance(csv_path, str) or not csv_path:
        return None
    if not os.path.exists(csv_path):
        return None
    df = pd.read_csv(csv_path)
    if df.empty or "date" not in df.columns or "stock_code" not in df.columns:
        return {}
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df["stock_code"] = df["stock_code"].astype(str)
    result: dict[pd.Timestamp, tuple[str, ...]] = {}
    for date_ts, group in df.groupby("date", sort=False):
        result[pd.Timestamp(date_ts)] = tuple(group["stock_code"].tolist())
    return result




def execute_buy_plans(
    strategy: Any,
    plans: list[BuyOrderPlan],
    order_list: list[Any],
    log_func: Any = None,
    today: Any = None,
) -> None:
    for plan in plans:
        if plan.action == "buy":
            sr_info = {"vol": plan.refined_vol}
            order = strategy.buy(
                data=strategy.getdatabyname(plan.instrument),
                size=plan.bt_vol,
                sr=sr_info,
            )
            order_list.append(order)
            if log_func and today:
                log_func(
                    today,
                    f"计划买入: {plan.instrument} 量({plan.refined_vol}) "
                    f"价({plan.none_close}) 金额({plan.money})",
                )
        else:
            if log_func and today:
                log_func(
                    today,
                    f"计划买入失败: {plan.instrument} 金额({plan.money})",
                )


def execute_sell_plans(
    strategy: Any,
    plans: list[SellOrderPlan],
    order_list: list[Any],
    log_func: Any = None,
    today: Any = None,
) -> None:
    for plan in plans:
        if plan.action == "close":
            sr_info = {"vol": plan.refined_vol}
            order = strategy.close(data=strategy.getdatabyname(plan.instrument), sr=sr_info)
            order_list.append(order)
            if log_func and today:
                log_func(today, f"计划平仓: {plan.instrument} 量({plan.refined_vol})")
        elif plan.action == "sell":
            sr_info = {"vol": plan.refined_vol}
            order = strategy.sell(
                data=strategy.getdatabyname(plan.instrument),
                size=plan.bt_vol,
                sr=sr_info,
            )
            order_list.append(order)
            if log_func and today:
                log_func(
                    today,
                    f"计划卖出: {plan.instrument} 量({plan.refined_vol}) "
                    f"价({plan.none_close}) 金额({plan.money})",
                )
        else:
            if log_func and today:
                log_func(
                    today,
                    f"计划卖出失败: {plan.instrument} 金额({plan.money})",
                )




def _generate_short_sell_orders(
    short_targets: pd.DataFrame,
    close_prices: dict[str, float],
    total_value: float,
    bond_data: pd.DataFrame | None,
    none_close_prices: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    orders: list[dict[str, Any]] = []
    has_bond_id = "bond_id" in short_targets.columns
    for _, row in short_targets.iterrows():
        inst = str(row["instrument"])
        weight = float(row["weight"])
        bond_id = str(row["bond_id"]) if has_bond_id else inst
        adj_price = close_prices.get(inst, 0.0)
        if none_close_prices is not None:
            none_close = none_close_prices.get(inst, adj_price)
        else:
            none_close = adj_price
        if none_close <= 0:
            none_close = adj_price
        if none_close <= 0:
            continue

        target_money = total_value * abs(weight)
        target_vol = target_money / none_close

        avail_vol = int(target_vol * 2)
        if bond_data is not None and not bond_data.empty:
            _avail_found = False
            if has_bond_id and "available" in bond_data.columns:
                try:
                    bid_key = int(bond_id) if bond_id.isdigit() else bond_id
                    if bid_key in bond_data.index:
                        avail_vol = int(bond_data.loc[bid_key, "available"])
                        _avail_found = True
                except (KeyError, ValueError, TypeError):
                    pass
            if not _avail_found and "available" in bond_data.columns:
                if inst in bond_data.index:
                    try:
                        avail_vol = int(bond_data.loc[inst, "available"])
                    except (TypeError, ValueError):
                        pass
                else:
                    match = bond_data[bond_data.get("instrument", pd.Series()) == inst]
                    if not match.empty:
                        avail_vol = int(match.iloc[0]["available"])

        ok, refined_vol = refine_short_sell_vol(inst, target_vol, avail_vol)
        if not ok or refined_vol <= 0:
            continue

        real_money = refined_vol * none_close
        bt_vol = real_money / adj_price if adj_price > 0 else float(refined_vol)

        orders.append(
            {
                "instrument": inst,
                "bond_id": bond_id,
                "side": "sell",
                "target_weight": weight,
                "target_money": real_money,
                "close_price": none_close,
                "bt_vol": bt_vol,
                "refined_vol": refined_vol,
            }
        )
    return orders


def _generate_short_cover_orders(
    instruments_to_cover: list[str],
    close_prices: dict[str, float],
    current_positions: dict[str, int],
    target_weights: dict[str, float],
    total_value: float,
) -> list[dict[str, Any]]:
    orders: list[dict[str, Any]] = []
    for inst in instruments_to_cover:
        price = close_prices.get(inst, 0.0)
        if price <= 0:
            continue

        posi_vol = abs(current_positions.get(inst, 0))
        if posi_vol == 0:
            continue

        target_w = abs(target_weights.get(inst, 0.0))
        if target_w < 1e-10:
            cover_vol = posi_vol
        else:
            target_money = total_value * target_w
            cover_vol = target_money / price

        is_close, is_valid, refined_vol = refine_short_buy_vol(inst, cover_vol, posi_vol)
        if not is_valid or refined_vol <= 0:
            continue

        real_money = refined_vol * price
        action = "close" if is_close else "buy"

        orders.append(
            {
                "instrument": inst,
                "side": "buy",
                "action": action,
                "target_money": real_money,
                "close_price": price,
                "bt_vol": refined_vol,
                "refined_vol": refined_vol,
            }
        )
    return orders



_LS_INCREMENTAL_SCHEMA_VERSION = "longshort-v3-incremental-1"


from quant_pro.adapters.backtrader._log_path_helpers import (
    _derive_log_path,
)
from quant_pro.application.optimization.score_inputs import (
    expand_weight_pivots,
    infer_period_num_from_tuning_params,
    score_payload_is_empty,
)


class LongShortStrategy(IncrementalStrategy, bt.Strategy):

    params = (
        ("optimizer_id", ""),
        ("start_date", ""),
        ("end_date", ""),
        ("rebalance_dates", None),
        ("weight_data", None),
        ("weight", None),
        ("do_long", True),
        ("do_short", True),
        ("total_value", 10_000_000.0),
        ("log_path", ""),
        ("persist_path", ""),
        ("tuning_params_list", None),
        ("holding_num", 60),
        ("rolling_num", 7),
        ("initial_optimizer_instance_id", ""),
        ("rebalance_optimizer_instance_id", ""),
        ("ss_df", None),
        ("initial_position_file_path", None),
        ("enable_daily_stats", True),
        ("record_trade_position_log", True),
        ("incremental_state_path", None),
        ("state_manager", None),
        ("save_daily_state", False),
        ("daily_state_path", None),
        ("optimizer_initial", None),
        ("optimizer_rebalance", None),
        ("bond_data", None),
        ("temp_path", ""),
        ("long_filter_pool_csv", None),
        ("short_filter_pool_csv", None),
    )

    def __init__(self) -> None:
        self.order_list: list[Any] = []
        self._period_num = infer_period_num_from_tuning_params(self.p.tuning_params_list)
        self._weight_data_periods = self._resolve_weight_data_periods()
        self._weight_data = self._weight_data_periods[0] if self._weight_data_periods else None
        self._optimizer_initial = self._resolve_optimizer(
            self.p.optimizer_initial,
            self.p.initial_optimizer_instance_id,
        )
        self._optimizer_rebalance = self._resolve_optimizer(
            self.p.optimizer_rebalance,
            self.p.rebalance_optimizer_instance_id,
        )
        _bond_data_src = self.p.bond_data if self.p.bond_data is not None else self.p.ss_df
        self._bond_data = _bond_data_src.copy(deep=True) if _bond_data_src is not None else None
        self._bond_table = None
        if self._bond_data is not None and hasattr(self._bond_data, "columns"):
            if "id" in self._bond_data.columns:
                self._bond_table = self._bond_data.set_index("id", drop=False).copy()
        self._order_bond_source = self._bond_table
        self._instrument_to_bond_id: dict[str, str] = {}
        self._bond_id_to_instrument: dict[str, str] = {}
        if self._bond_table is not None:
            unique_instruments = self._bond_table.reset_index(drop=True).drop_duplicates(
                "instrument",
                keep="first",
            )
            self._instrument_to_bond_id = {
                str(row["instrument"]): str(row["id"]) for _, row in unique_instruments.iterrows()
            }
            self._bond_id_to_instrument = {
                str(row["id"]): str(row["instrument"])
                for _, row in self._bond_table.reset_index(drop=True).iterrows()
                if pd.notna(row.get("id")) and pd.notna(row.get("instrument"))
            }
        self._temp_path = self.p.temp_path or self.p.persist_path or "."

        self._long_filter_pool_by_date = _load_filter_pool_csv(self.p.long_filter_pool_csv)
        self._short_filter_pool_by_date = _load_filter_pool_csv(self.p.short_filter_pool_csv)

        self._limitation = Limitation()

        rebalance_dates = self.p.rebalance_dates
        if (
            rebalance_dates is None
            and self._weight_data is not None
            and not self._weight_data.empty
        ):
            rebalance_dates = self._weight_data.index.tolist()
        self._rebalance_dates: set[Any] = {
            pd.Timestamp(date).normalize() for date in (rebalance_dates or [])
        }
        self._progress_total: int = len(self._rebalance_dates)
        self._progress_seen: set[Any] = set()
        self._progress_starting_value: float | None = None
        self._is_need_init_position: bool = True

        self._prev_dt: Any = None
        self._closed_daily_interest: float = 0.0
        self._last_total_interest: float = (
            0.0
        )
        self._last_cash_interest: float = 0.0
        self._cash_consumed_this_cycle: bool = False
        self._long_positions: dict[str, int] = {}
        self._short_positions: dict[str, dict[str, float]] = {}
        self._short_bond_instrument: dict[str, set[str]] = {}

        self.enable_daily_stats: bool = bool(self.p.enable_daily_stats)
        self._persist_path: str = self.p.persist_path or self._temp_path
        self._log_path: str = _derive_log_path(self.p.persist_path)

        self.record_trade_position_log: bool = bool(self.p.record_trade_position_log)
        if self.record_trade_position_log:
            self._trade_events: list[dict] = []
            self._position_snapshots: list[dict] = []
            self._position_integrity_audits: list[dict] = []
            self._position_integrity_issues: list[dict] = []
            self._position_integrity_cleanups: list[dict] = []

        if self.enable_daily_stats:
            self.daily_position_stats: list[dict] = []
            self.daily_pnl_stats: list[dict] = []
            self.prev_positions: dict[str, dict] = {}
            self.daily_cost_stats: list[dict] = []
            self.prev_cash: float | None = None
            self.prev_real_value: float | None = None
            self.initial_cash: float | None = None
            self.prev_total_value: float = self.broker.getvalue()
            self.daily_trades: dict[str, list] = {}
            self.daily_trade_summary: dict[str, dict] = {}
            self.all_daily_trades: dict[str, dict] = {}
            self.all_daily_trade_summary: dict[str, dict] = {}
            self.decision_scores: dict = {}
            self.daily_long_stats: list[dict] = []
            self.daily_short_stats: list[dict] = []
            self.daily_stock_summary: list[dict] = []
            self.all_long_stats: list[dict] = []
            self.all_short_stats: list[dict] = []
            self.all_stock_summary: list[dict] = []
            self.position_record: list = []
        else:
            self.prev_positions: dict[str, dict] = {}
            self.prev_total_value: float = self.broker.getvalue()
            self.daily_trades: dict[str, list] = {}
            self.daily_trade_summary: dict[str, dict] = {}

        self.incremental_init(
            state_manager=self.p.state_manager,
            save_daily_state=self.p.save_daily_state,
            daily_state_path=self.p.daily_state_path,
        )

    def _resolve_weight_data(self) -> pd.DataFrame | None:
        weight = self.p.weight_data if self.p.weight_data is not None else self.p.weight
        if not isinstance(weight, pd.DataFrame):
            return None

        frame = weight.copy()
        frame.index = pd.to_datetime(frame.index).normalize()
        return frame.sort_index()

    def _resolve_weight_data_periods(self) -> list[pd.DataFrame]:
        weight = self.p.weight_data if self.p.weight_data is not None else self.p.weight
        return expand_weight_pivots(weight, self._period_num)

    def _resolve_optimizer(self, optimizer: Any, optimizer_id: Any) -> Any:
        if optimizer is not None:
            return optimizer
        if not isinstance(optimizer_id, str) or not optimizer_id:
            return None

        resolved = get_optimizer_service(optimizer_id)
        tuning_params_list = self.p.tuning_params_list
        if tuning_params_list is not None and hasattr(resolved, "set_tuning_params_list"):
            resolved.set_tuning_params_list(tuning_params_list)
        return resolved

    def _get_runtime_attr(self, name: str, default: Any = _NO_RUNTIME_DEFAULT) -> Any:
        try:
            return object.__getattribute__(self, name)
        except AttributeError:
            if default is _NO_RUNTIME_DEFAULT:
                raise
            return default

    def _ensure_runtime_state(self) -> None:
        if self._get_runtime_attr("order_list", _RUNTIME_ATTR_MISSING) is _RUNTIME_ATTR_MISSING:
            self.order_list = []

        if self._get_runtime_attr("_weight_data", _RUNTIME_ATTR_MISSING) is _RUNTIME_ATTR_MISSING:
            self._period_num = infer_period_num_from_tuning_params(
                getattr(self.p, "tuning_params_list", None)
            )
            self._weight_data_periods = self._resolve_weight_data_periods()
            self._weight_data = self._weight_data_periods[0] if self._weight_data_periods else None

        if (
            self._get_runtime_attr("_optimizer_initial", _RUNTIME_ATTR_MISSING)
            is _RUNTIME_ATTR_MISSING
        ):
            self._optimizer_initial = self._resolve_optimizer(
                getattr(self.p, "optimizer_initial", None),
                getattr(self.p, "initial_optimizer_instance_id", ""),
            )

        if (
            self._get_runtime_attr("_optimizer_rebalance", _RUNTIME_ATTR_MISSING)
            is _RUNTIME_ATTR_MISSING
        ):
            self._optimizer_rebalance = self._resolve_optimizer(
                getattr(self.p, "optimizer_rebalance", None),
                getattr(self.p, "rebalance_optimizer_instance_id", ""),
            )

        if self._get_runtime_attr("_bond_data", _RUNTIME_ATTR_MISSING) is _RUNTIME_ATTR_MISSING:
            bond_data = getattr(self.p, "bond_data", None)
            if not isinstance(bond_data, pd.DataFrame):
                bond_data = getattr(self.p, "ss_df", None)
            self._bond_data = bond_data if isinstance(bond_data, pd.DataFrame) else None

        if self._get_runtime_attr("_bond_table", _RUNTIME_ATTR_MISSING) is _RUNTIME_ATTR_MISSING:
            self._bond_table = None
            if self._bond_data is not None and "id" in self._bond_data.columns:
                self._bond_table = self._bond_data.set_index("id", drop=False).copy()

        if (
            self._get_runtime_attr("_order_bond_source", _RUNTIME_ATTR_MISSING)
            is _RUNTIME_ATTR_MISSING
        ):
            self._order_bond_source = self._bond_table

        if (
            self._get_runtime_attr("_instrument_to_bond_id", _RUNTIME_ATTR_MISSING)
            is _RUNTIME_ATTR_MISSING
        ):
            self._instrument_to_bond_id = {}
            self._bond_id_to_instrument = {}
            if self._bond_table is not None:
                unique_instruments = self._bond_table.reset_index(drop=True).drop_duplicates(
                    "instrument",
                    keep="first",
                )
                self._instrument_to_bond_id = {
                    str(row["instrument"]): str(row["id"])
                    for _, row in unique_instruments.iterrows()
                }
                self._bond_id_to_instrument = {
                    str(row["id"]): str(row["instrument"])
                    for _, row in self._bond_table.reset_index(drop=True).iterrows()
                    if pd.notna(row.get("id")) and pd.notna(row.get("instrument"))
                }

        if self._get_runtime_attr("_temp_path", _RUNTIME_ATTR_MISSING) is _RUNTIME_ATTR_MISSING:
            temp_path = getattr(self.p, "temp_path", "")
            persist_path = getattr(self.p, "persist_path", "")
            if not isinstance(temp_path, str) or not temp_path:
                temp_path = persist_path if isinstance(persist_path, str) and persist_path else "."
            self._temp_path = temp_path

        if (
            self._get_runtime_attr("_long_filter_pool_by_date", _RUNTIME_ATTR_MISSING)
            is _RUNTIME_ATTR_MISSING
        ):
            self._long_filter_pool_by_date = _load_filter_pool_csv(
                getattr(self.p, "long_filter_pool_csv", None)
            )
        if (
            self._get_runtime_attr("_short_filter_pool_by_date", _RUNTIME_ATTR_MISSING)
            is _RUNTIME_ATTR_MISSING
        ):
            self._short_filter_pool_by_date = _load_filter_pool_csv(
                getattr(self.p, "short_filter_pool_csv", None)
            )

        if self._get_runtime_attr("_limitation", _RUNTIME_ATTR_MISSING) is _RUNTIME_ATTR_MISSING:
            self._limitation = Limitation()

        if (
            self._get_runtime_attr("_rebalance_dates", _RUNTIME_ATTR_MISSING)
            is _RUNTIME_ATTR_MISSING
        ):
            rebalance_dates = getattr(self.p, "rebalance_dates", None)
            if (
                rebalance_dates is None
                and self._weight_data is not None
                and not self._weight_data.empty
            ):
                rebalance_dates = self._weight_data.index.tolist()
            self._rebalance_dates = {
                pd.Timestamp(date).normalize() for date in (rebalance_dates or [])
            }

        if self._get_runtime_attr("_progress_seen", _RUNTIME_ATTR_MISSING) is _RUNTIME_ATTR_MISSING:
            self._progress_total = len(self._rebalance_dates)
            self._progress_seen = set()
            self._progress_starting_value = None

        if (
            self._get_runtime_attr("_is_need_init_position", _RUNTIME_ATTR_MISSING)
            is _RUNTIME_ATTR_MISSING
        ):
            self._is_need_init_position = True

        if (
            self._get_runtime_attr("save_daily_state", _RUNTIME_ATTR_MISSING)
            is _RUNTIME_ATTR_MISSING
        ):
            self.save_daily_state = False
        if self._get_runtime_attr("is_incremental", _RUNTIME_ATTR_MISSING) is _RUNTIME_ATTR_MISSING:
            self.is_incremental = False
        if self._get_runtime_attr("state_manager", _RUNTIME_ATTR_MISSING) is _RUNTIME_ATTR_MISSING:
            self.state_manager = None
        if (
            self._get_runtime_attr("daily_state_path", _RUNTIME_ATTR_MISSING)
            is _RUNTIME_ATTR_MISSING
        ):
            self.daily_state_path = None
        if self._get_runtime_attr("daily_orders", _RUNTIME_ATTR_MISSING) is _RUNTIME_ATTR_MISSING:
            self.daily_orders = []

        if (
            self._get_runtime_attr("enable_daily_stats", _RUNTIME_ATTR_MISSING)
            is _RUNTIME_ATTR_MISSING
        ):
            _raw_eds = getattr(self.p, "enable_daily_stats", False)
            _candidate_eds = _raw_eds if isinstance(_raw_eds, bool) else False
            if _candidate_eds and not hasattr(self, "daily_trades"):
                _candidate_eds = False
            self.enable_daily_stats = _candidate_eds
        if self._get_runtime_attr("initial_cash", _RUNTIME_ATTR_MISSING) is _RUNTIME_ATTR_MISSING:
            self.initial_cash = None
        if (
            self._get_runtime_attr("_last_total_interest", _RUNTIME_ATTR_MISSING)
            is _RUNTIME_ATTR_MISSING
        ):
            self._last_total_interest = 0.0
        if (
            self._get_runtime_attr("_last_cash_interest", _RUNTIME_ATTR_MISSING)
            is _RUNTIME_ATTR_MISSING
        ):
            self._last_cash_interest = 0.0
        if (
            self._get_runtime_attr("_cash_consumed_this_cycle", _RUNTIME_ATTR_MISSING)
            is _RUNTIME_ATTR_MISSING
        ):
            self._cash_consumed_this_cycle = False
        if (
            self._get_runtime_attr("_closed_daily_interest", _RUNTIME_ATTR_MISSING)
            is _RUNTIME_ATTR_MISSING
        ):
            self._closed_daily_interest = 0.0
        if self._get_runtime_attr("_log_path", _RUNTIME_ATTR_MISSING) is _RUNTIME_ATTR_MISSING:
            self._log_path = ""


    def start(self) -> None:
        super().start()
        self.incremental_start()

        if self.is_incremental and self.state_manager is not None:
            strategy_state = self.state_manager.get_strategy_state()
            broker_positions = self.state_manager.get_broker_state().get("positions", {})
            if not strategy_state:
                self._restore_live_position_tracking_from_broker_state(broker_positions)
                return

            saved_version = strategy_state.get("_schema_version")
            if saved_version and saved_version != _LS_INCREMENTAL_SCHEMA_VERSION:
                logger.warning(
                    "State schema version mismatch: saved=%s, current=%s. "
                    "State may be incompatible.",
                    saved_version,
                    _LS_INCREMENTAL_SCHEMA_VERSION,
                )

            if strategy_state.get("prev_dt") is not None:
                self._prev_dt = getattr(self, "prev_dt", self._prev_dt)
            if "closed_daily_interest" in strategy_state:
                self._closed_daily_interest = strategy_state["closed_daily_interest"]

            (
                broker_long_positions,
                broker_short_positions,
                broker_short_bond_instrument,
            ) = self._position_tracking_from_broker_state(broker_positions)

            self._long_positions = strategy_state.get(
                "_long_positions",
                broker_long_positions,
            )
            short_raw = strategy_state.get("_short_positions", {})
            self._short_positions = (
                {str(k): dict(v) for k, v in short_raw.items()}
                if "_short_positions" in strategy_state
                else broker_short_positions
            )
            bond_inst_raw = strategy_state.get("_short_bond_instrument")
            self._short_bond_instrument = (
                {str(k): set(v) for k, v in bond_inst_raw.items()}
                if bond_inst_raw is not None
                else broker_short_bond_instrument
            )
            default_init_position = not self.state_manager.has_positions()
            self._is_need_init_position = strategy_state.get(
                "_is_need_init_position",
                strategy_state.get("init_position", default_init_position),
            )

    def _restore_live_position_tracking_from_broker_state(
        self,
        broker_positions: dict[str, Any],
    ) -> None:
        (
            long_positions,
            short_positions,
            short_bond_instrument,
        ) = self._position_tracking_from_broker_state(broker_positions)
        if long_positions or short_positions:
            self._long_positions = long_positions
            self._short_positions = short_positions
            self._short_bond_instrument = short_bond_instrument
            self._is_need_init_position = False

    def _position_tracking_from_broker_state(
        self,
        broker_positions: dict[str, Any],
    ) -> tuple[dict[str, int], dict[str, dict[str, float]], dict[str, set[str]]]:
        long_positions: dict[str, int] = {}
        short_positions: dict[str, dict[str, float]] = {}
        short_bond_instrument: dict[str, set[str]] = {}

        for position_key, position_data in broker_positions.items():
            if isinstance(position_data, dict):
                raw_size = position_data.get("size", 0)
                raw_price = position_data.get("open_price", position_data.get("price", 0.0))
                instrument = str(position_data.get("instrument", position_key))
            else:
                raw_size = position_data
                raw_price = 0.0
                instrument = str(position_key)

            try:
                size = float(raw_size)
            except (TypeError, ValueError):
                continue
            if abs(size) <= _POSITION_FLAT_EPS:
                continue

            if size > 0:
                long_positions[instrument] = int(round(size))
                continue

            bond_id = self._resolve_live_short_bond_id(
                instrument,
                str(position_key),
                position_data if isinstance(position_data, dict) else {},
            )
            if bond_id is None:
                logger.warning("Live LS short position skipped without bond id: %s", instrument)
                continue

            try:
                open_price = float(raw_price or 0.0)
            except (TypeError, ValueError):
                open_price = 0.0
            real_size = abs(int(round(size)))
            apply_rate = self._resolve_live_short_apply_rate(
                bond_id,
                position_data if isinstance(position_data, dict) else {},
            )
            money = (
                position_data.get("money")
                if isinstance(position_data, dict) and position_data.get("money") is not None
                else real_size * open_price
            )
            try:
                money_float = float(money or 0.0)
            except (TypeError, ValueError):
                money_float = 0.0

            short_positions[bond_id] = {
                "size": real_size,
                "money": money_float,
                "apply_rate": apply_rate,
                "open_price": open_price,
            }
            self._bond_id_to_instrument.setdefault(bond_id, instrument)
            short_bond_instrument.setdefault(instrument, set()).add(bond_id)

        return long_positions, short_positions, short_bond_instrument

    def _resolve_live_short_bond_id(
        self,
        instrument: str,
        position_key: str,
        position_data: dict[str, Any],
    ) -> str | None:
        explicit = position_data.get("bond_id", position_data.get("id"))
        if explicit is not None:
            return str(explicit)
        if position_key in self._bond_id_to_instrument:
            return position_key
        mapped = self._instrument_to_bond_id.get(instrument)
        if mapped is not None:
            return str(mapped)
        return None

    def _resolve_live_short_apply_rate(
        self,
        bond_id: str,
        position_data: dict[str, Any],
    ) -> float:
        explicit = position_data.get("apply_rate")
        if explicit is not None:
            try:
                return float(explicit)
            except (TypeError, ValueError):
                return 0.0
        if self._bond_table is None:
            return 0.0
        row: Any
        if bond_id in self._bond_table.index:
            row = self._bond_table.loc[bond_id]
        elif "id" in self._bond_table.columns:
            matched = self._bond_table[self._bond_table["id"].astype(str) == bond_id]
            if matched.empty:
                return 0.0
            row = matched.iloc[0]
        else:
            return 0.0
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
        try:
            return float(row.get("apply_rate", 0.0))
        except (TypeError, ValueError):
            return 0.0


    def _get_weight_series(self, today: Any, period_idx: int = 0) -> pd.Series:
        weight_periods = getattr(self, "_weight_data_periods", None)
        if weight_periods:
            weight = weight_periods[min(period_idx, len(weight_periods) - 1)]
        else:
            weight = self._weight_data
        if weight is None or weight.empty:
            return pd.Series(dtype=float)

        if not hasattr(weight.index, "normalize"):
            weight = weight.copy()
            weight.index = pd.to_datetime(weight.index)

        today_ts = pd.Timestamp(today).normalize()
        if today_ts not in weight.index:
            return pd.Series(dtype=float)

        row = weight.loc[today_ts]
        return row.dropna().sort_values(ascending=False)


    def _has_optimizer(self) -> bool:
        return self._optimizer_initial is not None

    def _attach_filter_pools(self, optimizer: Any, today: Any) -> None:
        for attr_name in ("long_filter_pool_today", "short_filter_pool_today"):
            if hasattr(optimizer, attr_name):
                try:
                    delattr(optimizer, attr_name)
                except AttributeError:
                    setattr(optimizer, attr_name, None)

        if self._long_filter_pool_by_date is None and self._short_filter_pool_by_date is None:
            return
        rebalance_date = pd.Timestamp(today).normalize()
        if self._long_filter_pool_by_date is not None:
            long_pool = self._long_filter_pool_by_date.get(rebalance_date, ())
            setattr(optimizer, "long_filter_pool_today", long_pool)
        if self._short_filter_pool_by_date is not None:
            short_pool = self._short_filter_pool_by_date.get(rebalance_date, ())
            setattr(optimizer, "short_filter_pool_today", short_pool)

    def _prepare_score_df(self, today: Any) -> pd.DataFrame:
        weight_today = self._get_weight_series(today)
        if weight_today.empty:
            return pd.DataFrame(columns=["datetime", "instrument", "score"])

        return pd.DataFrame(
            {
                "datetime": today,
                "instrument": weight_today.index,
                "score": weight_today.values,
            }
        )

    def _prepare_score_payload(self, today: Any) -> pd.DataFrame | list[pd.DataFrame]:
        weight_periods = getattr(self, "_weight_data_periods", None)
        period_num = max(getattr(self, "_period_num", 1), 1)
        if period_num <= 1 and not weight_periods:
            return self._prepare_score_df(today)

        frames: list[pd.DataFrame] = []
        for period_idx in range(period_num):
            weight_today = self._get_weight_series(today, period_idx)
            frames.append(
                pd.DataFrame(
                    {
                        "datetime": today,
                        "instrument": weight_today.index,
                        "score": weight_today.values,
                    }
                )
            )
        return frames if len(frames) > 1 else frames[0]

    def _get_position_df(
        self,
        today: Any = None,
        dt_next: Any = None,
        dt_next_next: Any = None,
    ) -> pd.DataFrame | None:
        empty_cols = ["stockcode", "volume", "close", "hold_days", "apply_rate"]

        long_records: list[dict[str, Any]] = []
        for inst, vol in self._long_positions.items():
            if vol <= 0:
                continue
            if today is not None:
                close = get_none_close(today, inst)
            else:
                close = self.getdatabyname(inst).close[0]
            if pd.isna(close) or close is None:
                close = 0.0
            long_records.append(
                {
                    "stockcode": str(inst),
                    "volume": int(vol),
                    "close": float(close),
                    "hold_days": 0,
                    "apply_rate": 0.0,
                }
            )

        short_records: list[dict[str, Any]] = []
        if dt_next is not None and dt_next_next is not None:
            max((pd.Timestamp(dt_next_next) - pd.Timestamp(dt_next)).days, 1)

        for bid, pos in self._short_positions.items():
            size = int(pos.get("size", 0))
            if size <= 0:
                continue
            inst = self._bond_id_to_instrument.get(str(bid), str(bid))
            if today is not None:
                close = get_none_close(today, inst)
            else:
                close = self.getdatabyname(inst).close[0] if inst else 0.0
            rate = pos.get("apply_rate", 0.0)
            open_price = pos.get("open_price", 0.0)
            _days = (
                max((pd.Timestamp(dt_next_next) - pd.Timestamp(dt_next)).days, 0)
                if dt_next and dt_next_next
                else 0
            )
            if close > 0:
                apply_rate = rate * open_price * _days / close
            else:
                apply_rate = rate * open_price * _days

            short_records.append(
                {
                    "stockcode": str(bid),
                    "volume": size,
                    "close": float(close) if close is not None else 0.0,
                    "hold_days": 0,
                    "apply_rate": apply_rate,
                }
            )

        all_records = long_records + short_records
        import logging as _logging

        _logger = _logging.getLogger(__name__)
        _logger.warning(
            "[DEBUG _get_position_df] today=%s long=%d short=%d _long_positions_size=%d _short_positions_size=%d",
            today,
            len(long_records),
            len(short_records),
            len(self._long_positions),
            len(self._short_positions),
        )
        if long_records:
            _total_val = sum(r["volume"] * r["close"] for r in long_records)
            _logger.warning("[DEBUG _get_position_df] long value sum=%.0f", _total_val)
        if short_records:
            _short_val = sum(r["volume"] * r["close"] for r in short_records)
            _logger.warning("[DEBUG _get_position_df] short value sum=%.0f", _short_val)
        if not all_records:
            return pd.DataFrame(columns=empty_cols)
        return pd.DataFrame(all_records)

    def _compute_short_whole_weight(
        self,
        today: Any,
    ) -> float:
        bond = self._bond_data
        if bond is None:
            return 0.0
        if hasattr(bond, "empty") and bond.empty:
            return 0.0
        return 1.0

    def _compute_rebalance_value(self, today: Any) -> float:
        prev_dt = self._prev_dt
        if prev_dt is None:
            self._last_total_interest = 0.0
            self._last_cash_interest = 0.0
            return float(self.broker.cash) + float(
                getattr(self.broker, "get_unrealized", lambda: 0)()
            )


        day_diff = (pd.Timestamp(today) - pd.Timestamp(prev_dt)).days
        if day_diff <= 0:
            day_diff = 1

        unrealized = float(getattr(self.broker, "get_unrealized", lambda: 0)())
        pos_value = sum(
            p.size * self.getdatabyname(d._name).close[0]
            for d, p in self.getpositions().items()
            if p.size > 1e-9
        )

        total_interest = 0.0
        for _bid, pos in self._short_positions.items():
            total_interest += (
                pos.get("apply_rate", 0.0)
                * pos.get("open_price", 0.0)
                * abs(pos.get("size", 0))
                * day_diff
            )

        cash_after_interest_deduction = (
            self.broker.cash - total_interest - self._closed_daily_interest
        )
        if unrealized > 0:
            cash_interest = cash_after_interest_deduction * (0.043 / 365) * day_diff
        else:
            cash_interest = (cash_after_interest_deduction + unrealized) * (0.043 / 365) * day_diff
        long_finance_cost = pos_value * (0.05 + 0.01) / 365 * day_diff

        self.broker.cash -= total_interest
        self.broker.cash -= self._closed_daily_interest
        self.broker.cash += cash_interest
        self.broker.cash -= long_finance_cost
        self._last_total_interest = total_interest
        self._last_cash_interest = cash_interest
        self._cash_consumed_this_cycle = True
        if hasattr(self.broker, "_value"):
            self.broker._value = self.broker.cash + unrealized

        real_value = float(self.broker.cash) + unrealized

        import os as _os

        if _os.environ.get("CHECKPOINT_DEBUG"):
            import logging as _log

            _log.getLogger(__name__).warning(
                "[DEBUG rebalance_value] today=%s prev_dt=%s day_diff=%d "
                "cash_before_adj=%.2f total_interest=%.6f closed_daily_interest=%.6f "
                "cash_interest=%.6f pos_value=%.2f long_finance_cost=%.6f "
                "unrealized=%.2f real_value=%.2f n_short_pos=%d",
                today,
                prev_dt,
                day_diff,
                self.broker.cash
                + long_finance_cost
                - cash_interest
                + total_interest
                + self._closed_daily_interest,
                total_interest,
                self._closed_daily_interest,
                cash_interest,
                pos_value,
                long_finance_cost,
                unrealized,
                real_value,
                len(self._short_positions),
            )

        return real_value


    def _to_log(self, dt: Any, txt: str, log_path: str | None = None) -> None:
        date_str = pd.Timestamp(dt).strftime("%Y-%m-%d")
        target = log_path or self._log_path
        if not target:
            return
        try:
            with open(target, "a") as f:
                f.write(f"[{date_str}] {txt}\n")
        except OSError:
            pass


    def _get_cached_account_info(self, dt: Any) -> dict:
        current_total_value = self.broker.get_real_value()
        current_cash = self.broker.cash
        current_unrealized = self.broker.get_unrealized()

        if (
            hasattr(self, "prev_total_value")
            and self.prev_total_value is not None
            and self.prev_total_value != 0
        ):
            account_daily_return = (
                current_total_value - self.prev_total_value
            ) / self.prev_total_value
            net_value_change = current_total_value - self.prev_total_value
        else:
            account_daily_return = 0.0
            net_value_change = 0.0

        self._to_log(
            dt,
            f"账户净值: {current_total_value:,.0f}, 现金: {current_cash:,.0f}, "
            f"未实现盈亏: {current_unrealized:,.0f}",
        )
        if hasattr(self, "prev_total_value") and self.prev_total_value is not None:
            self._to_log(
                dt,
                f"前日净值: {self.prev_total_value:,.0f}, 净值变化: {net_value_change:,.0f}, "
                f"日收益率: {account_daily_return:.4f}",
            )

        return {
            "total_value": current_total_value,
            "cash": current_cash,
            "unrealized": current_unrealized,
            "daily_return": account_daily_return,
            "net_value_change": net_value_change,
        }


    def _get_daily_realized_pnl(self, date_str: str) -> dict:
        daily_realized_results: dict = {}

        for stock_code, trades in self.daily_trades.items():
            prev_position = self.prev_positions.get(stock_code, {})
            prev_size = prev_position.get("position_size", 0)
            prev_avg_price = prev_position.get("avg_price", 0)
            prev_close_price = prev_position.get("prev_close", prev_avg_price)

            if prev_size == 0:
                continue

            stock_trades = [t for t in trades if t.get("datetime") == date_str]
            if not stock_trades:
                continue

            total_realized_pnl = 0.0
            total_realized_pnl_today = 0.0
            remaining_size = prev_size
            remaining_avg_price = prev_avg_price

            for trade in stock_trades:
                trade_size = trade["size"]
                trade_price = trade["price"]
                action = trade["action"]

                if remaining_size > 0:
                    if action == "sell":
                        trade_amount = abs(trade_size)
                        closed_size = min(trade_amount, remaining_size)
                        realized_pnl = (trade_price - remaining_avg_price) * closed_size
                        total_realized_pnl += realized_pnl
                        realized_pnl_today = (trade_price - prev_close_price) * closed_size
                        total_realized_pnl_today += realized_pnl_today
                        remaining_size -= closed_size
                    elif action == "buy":
                        trade_amount = trade_size
                        total_cost = (
                            remaining_size * remaining_avg_price + trade_amount * trade_price
                        )
                        remaining_size += trade_amount
                        remaining_avg_price = (
                            total_cost / remaining_size if remaining_size > 0 else 0
                        )
                elif remaining_size < 0:
                    if action == "buy":
                        trade_amount = trade_size
                        closed_size = min(trade_amount, abs(remaining_size))
                        realized_pnl = (remaining_avg_price - trade_price) * closed_size
                        total_realized_pnl += realized_pnl
                        realized_pnl_today = (prev_close_price - trade_price) * closed_size
                        total_realized_pnl_today += realized_pnl_today
                        remaining_size += closed_size
                    elif action == "sell":
                        trade_amount = abs(trade_size)
                        current_short_size = abs(remaining_size)
                        total_cost = (
                            current_short_size * remaining_avg_price + trade_amount * trade_price
                        )
                        remaining_size -= trade_amount
                        remaining_avg_price = (
                            total_cost / abs(remaining_size) if remaining_size != 0 else 0
                        )
                elif remaining_size == 0:
                    if action == "buy":
                        remaining_size = trade_size
                        remaining_avg_price = trade_price
                    elif action == "sell":
                        trade_amount = abs(trade_size)
                        remaining_size = -trade_amount
                        remaining_avg_price = trade_price

            if total_realized_pnl != 0 or total_realized_pnl_today != 0:
                daily_realized_results[stock_code] = {
                    "realized_pnl": total_realized_pnl,
                    "realized_pnl_today": total_realized_pnl_today,
                }

        return daily_realized_results


    def _get_daily_commission(self, date_str: str) -> dict:
        daily_commission: dict = {}

        for stock_code, trades in self.daily_trades.items():
            closing_commission = 0.0
            opening_commission = 0.0

            prev_size = 0
            if stock_code in self.prev_positions:
                prev_size = self.prev_positions[stock_code]["position_size"]

            stock_trades = [t for t in trades if t.get("datetime") == date_str]
            if not stock_trades:
                continue

            stock_trades.sort(key=lambda x: x.get("timestamp", 0))
            current_size = prev_size

            for trade in stock_trades:
                commission = trade.get("commission", 0.0)
                action = trade.get("action")
                trade_size = trade.get("size", 0)

                if current_size > 0:
                    if action == "sell":
                        closing_commission += commission
                        current_size -= abs(trade_size)
                    elif action == "buy":
                        opening_commission += commission
                        current_size += trade_size
                elif current_size < 0:
                    if action == "buy":
                        closing_commission += commission
                        current_size += trade_size
                    elif action == "sell":
                        opening_commission += commission
                        current_size -= abs(trade_size)
                else:
                    opening_commission += commission
                    if action == "buy":
                        current_size += trade_size
                    elif action == "sell":
                        current_size -= abs(trade_size)

            daily_commission[stock_code] = {
                "closing": closing_commission,
                "opening": opening_commission,
            }

        return daily_commission


    def _get_daily_score_info(self, dt: Any) -> dict:
        try:
            if self._prev_dt is not None:
                prev_date = self._prev_dt
                if prev_date in self.decision_scores:
                    daily_scores = pd.Series(self.decision_scores[prev_date])
                    score_percentiles = daily_scores.rank(pct=True) * 100
                    self._to_log(
                        dt,
                        f"📊 使用前一交易日({pd.Timestamp(prev_date).strftime('%Y-%m-%d')})的打分数据",
                    )
                    return {
                        "scores": daily_scores,
                        "percentiles": score_percentiles,
                        "decision_date": prev_date,
                    }
                else:
                    self._to_log(
                        dt,
                        f"⚠️ 前一交易日({pd.Timestamp(prev_date).strftime('%Y-%m-%d')})无打分数据",
                    )
            else:
                self._to_log(dt, "⚠️ 这是第一个交易日，无前一日数据")

            return {
                "scores": pd.Series(dtype=float),
                "percentiles": pd.Series(dtype=float),
                "decision_date": None,
            }
        except Exception as e:
            self._to_log(dt, f"❌ 获取打分数据失败: {str(e)}")
            return {
                "scores": pd.Series(dtype=float),
                "percentiles": pd.Series(dtype=float),
                "decision_date": None,
            }


    def _calculate_daily_trade_summary(self) -> None:
        self.daily_trade_summary = {}

        for stock_code, trades in self.daily_trades.items():
            current_position = self.broker.getposition(self.getdatabyname(stock_code))
            current_size = current_position.size

            prev_size = 0
            if stock_code in self.prev_positions:
                prev_size = self.prev_positions[stock_code]["position_size"]

            net_buy_size = 0
            net_buy_value = 0
            net_sell_size = 0
            net_sell_value = 0

            for trade in trades:
                if trade["action"] == "buy":
                    net_buy_size += trade["size"]
                    net_buy_value += trade["value"]
                else:
                    net_sell_size += abs(trade["size"])
                    net_sell_value += abs(trade["value"])

            position_change = current_size - prev_size

            trade_analysis = analyze_trade_type(
                prev_size, current_size, net_buy_size, net_sell_size
            )

            self.daily_trade_summary[stock_code] = {
                "prev_position": prev_size,
                "current_position": current_size,
                "position_change": position_change,
                "net_buy_size": net_buy_size,
                "net_sell_size": net_sell_size,
                "net_buy_value": net_buy_value,
                "net_sell_value": net_sell_value,
                "trade_type": trade_analysis["trade_type"],
                "closed_size": trade_analysis["closed_size"],
                "opened_size": trade_analysis["opened_size"],
                "closed_direction": trade_analysis["closed_direction"],
                "opened_direction": trade_analysis["opened_direction"],
            }


    def _collect_all_involved_stocks(self, daily_realized_results: dict) -> set:
        all_stocks: set[str] = set()
        for data in self.datas:
            position = self.broker.getposition(data)
            if position.size != 0:
                all_stocks.add(data._name)
        all_stocks.update(daily_realized_results.keys())
        if hasattr(self, "prev_positions"):
            all_stocks.update(self.prev_positions.keys())
        return all_stocks


    def _init_stock_summary(
        self,
        stock_code: str,
        date_str: str,
        daily_realized_results: dict,
        account_info: dict,
        score_info: dict,
    ) -> dict:
        prev_position_size = 0
        if hasattr(self, "prev_positions") and stock_code in self.prev_positions:
            prev_position_size = self.prev_positions[stock_code]["position_size"]

        summary = {
            "date": date_str,
            "stock_code": stock_code,
            "long_position_size": 0,
            "short_position_size": 0,
            "net_position_size": 0,
            "long_position_change": 0,
            "short_position_change": 0,
            "net_position_change": 0,
            "prev_position_size": prev_position_size,
            "long_market_value": 0.0,
            "short_market_value": 0.0,
            "net_market_value": 0.0,
            "long_daily_pnl": 0.0,
            "short_daily_pnl": 0.0,
            "total_daily_pnl": 0.0,
            "realized_pnl_today": 0.0,
            "total_daily_return": 0.0,
            "account_daily_return": account_info["daily_return"],
            "account_total_value": account_info["total_value"],
            "account_cash": account_info["cash"],
            "account_unrealized": account_info["unrealized"],
        }
        if stock_code in score_info["scores"].index:
            summary["score"] = score_info["scores"][stock_code]
            summary["score_percentile"] = score_info["percentiles"][stock_code]
            summary["score_decile"] = min(int(score_info["percentiles"][stock_code] // 10), 9)
        else:
            summary["score"] = None
            summary["score_percentile"] = None
            summary["score_decile"] = None
        return summary


    def _calculate_holding_daily_pnl(
        self,
        stock_code: str,
        position: Any,
        current_price: float,
        trade_type: str,
    ) -> tuple[float, float]:
        prev_size = 0
        prev_close = None
        if stock_code in self.prev_positions:
            prev_info = self.prev_positions[stock_code]
            prev_size = prev_info["position_size"]
            prev_close = prev_info["prev_close"]
        return calculate_holding_daily_pnl(
            position_size=position.size,
            position_price=position.price,
            current_price=current_price,
            trade_type=trade_type,
            prev_size=prev_size,
            prev_close=prev_close,
            trade_summary=self.daily_trade_summary.get(stock_code),
        )


    def _get_close_price_from_daily_trades(self, stock_code: str, prev_size: int) -> float | None:
        trades = self.daily_trades.get(stock_code, [])
        if not trades or prev_size == 0 or prev_size is None:
            return None
        target_action = "sell" if prev_size > 0 else "buy"
        tv, tq = 0.0, 0.0
        for tr in trades:
            if tr["action"] == target_action:
                qty = abs(tr["size"])
                tv += qty * tr["price"]
                tq += qty
        return tv / tq if tq else None


    def _calculate_total_daily_return(self, stock_code: str, summary: dict) -> float:
        total_base_value = 0.0

        if stock_code in self.prev_positions:
            prev_info = self.prev_positions[stock_code]
            prev_size = prev_info["position_size"]
            prev_close = prev_info["prev_close"]
            total_base_value += abs(prev_size * prev_close)

        if stock_code in self.daily_trade_summary:
            trade_info = self.daily_trade_summary[stock_code]
            opened_size = trade_info.get("opened_size", 0)
            trade_type = trade_info.get("trade_type", "NONE")
            if opened_size > 0:
                if trade_type in ["PURE_OPEN_LONG", "ADD_LONG"]:
                    net_buy_value = trade_info.get("net_buy_value", 0)
                    net_buy_size = trade_info.get("net_buy_size", 1)
                    if net_buy_size > 0:
                        avg_open_price = net_buy_value / net_buy_size
                        total_base_value += abs(opened_size * avg_open_price)
                elif trade_type in ["PURE_OPEN_SHORT", "ADD_SHORT"]:
                    net_sell_value = trade_info.get("net_sell_value", 0)
                    net_sell_size = trade_info.get("net_sell_size", 1)
                    if net_sell_size > 0:
                        avg_open_price = net_sell_value / net_sell_size
                        total_base_value += abs(opened_size * avg_open_price)
                elif trade_type in ["REVERSE_LONG_TO_SHORT", "REVERSE_SHORT_TO_LONG"]:
                    current_position = self.broker.getposition(self.getdatabyname(stock_code))
                    if current_position.price > 0:
                        total_base_value += abs(opened_size * current_position.price)

        if total_base_value == 0.0:
            long_mv = abs(summary.get("long_market_value", 0))
            short_mv = abs(summary.get("short_market_value", 0))
            current_mv = long_mv + short_mv
            if current_mv > 0:
                total_base_value = current_mv

        if total_base_value > 0:
            return summary["total_daily_pnl"] / total_base_value
        return 0.0


    def _calculate_total_daily_return_for_position_record(
        self,
        stock_code: str,
        daily_pnl: float,
        new_position_return: float,
    ) -> float:
        temp_summary = {"total_daily_pnl": daily_pnl}
        calculated_return = self._calculate_total_daily_return(stock_code, temp_summary)
        if calculated_return == 0.0 and new_position_return != 0.0:
            return new_position_return
        return calculated_return


    def _create_position_record(
        self,
        stock_code: str,
        position: Any,
        current_price: float,
        dt: Any,
        trade_type: str,
        daily_pnl: float,
        continuing_pnl: float,
        new_position_pnl: float,
        realized_pnl_today: float,
        realized_pnl_full: float,
        commission_today: float,
        account_info: dict,
        score_info: dict,
    ) -> dict:
        prev_close = None
        if stock_code in self.prev_positions:
            prev_close = self.prev_positions[stock_code]["prev_close"]

        prev_size = 0
        if stock_code in self.prev_positions:
            prev_size = self.prev_positions[stock_code]["position_size"]

        position_change = position.size - prev_size

        if position.price > 0:
            if position.size > 0:
                current_position_return = (current_price - position.price) / position.price
            else:
                current_position_return = (position.price - current_price) / position.price
        else:
            current_position_return = 0.0

        if prev_size != 0 and prev_close is not None and prev_close > 0:
            if trade_type in ["REVERSE_LONG_TO_SHORT", "REVERSE_SHORT_TO_LONG"]:
                continuing_return = 0.0
            else:
                continuing_return = (current_price - prev_close) / prev_close
                if position.size < 0:
                    continuing_return = -continuing_return
        else:
            continuing_return = 0.0

        new_position_return = 0.0
        if stock_code in self.daily_trade_summary:
            trade_info = self.daily_trade_summary[stock_code]
            opened_size = trade_info.get("opened_size", 0)
            ti_trade_type = trade_info.get("trade_type", "NONE")
            if opened_size > 0 and new_position_pnl != 0:
                new_position_cost = 0.0
                if ti_trade_type in ["PURE_OPEN_LONG", "ADD_LONG"]:
                    nbv = trade_info.get("net_buy_value", 0)
                    nbs = trade_info.get("net_buy_size", 1)
                    if nbs > 0:
                        new_position_cost = opened_size * (nbv / nbs)
                elif ti_trade_type in ["PURE_OPEN_SHORT", "ADD_SHORT"]:
                    nsv = trade_info.get("net_sell_value", 0)
                    nss = trade_info.get("net_sell_size", 1)
                    if nss > 0:
                        new_position_cost = opened_size * (nsv / nss)
                elif ti_trade_type in ["REVERSE_LONG_TO_SHORT", "REVERSE_SHORT_TO_LONG"]:
                    new_position_cost = opened_size * position.price
                if new_position_cost > 0:
                    new_position_return = new_position_pnl / new_position_cost

        record = {
            "date": pd.Timestamp(dt).strftime("%Y-%m-%d"),
            "stock_code": stock_code,
            "trade_type": trade_type,
            "position_size": position.size,
            "position_change": position_change,
            "avg_price": position.price,
            "current_price": current_price,
            "prev_close": prev_close,
            "weight": (
                abs(position.size * current_price) / account_info["total_value"]
                if account_info["total_value"] > 0
                else 0
            ),
            "market_value": position.size * current_price,
            "cost_value": position.size * position.price,
            "unrealized_pnl": (current_price - position.price) * position.size,
            "realized_pnl": realized_pnl_full,
            "realized_pnl_today": realized_pnl_today,
            "commission_today": commission_today,
            "daily_pnl": daily_pnl,
            "continuing_pnl": continuing_pnl,
            "new_position_pnl": new_position_pnl,
            "current_position_return": current_position_return,
            "continuing_return": continuing_return,
            "new_position_return": new_position_return,
            "total_daily_return": self._calculate_total_daily_return_for_position_record(
                stock_code, daily_pnl, new_position_return
            ),
            "account_daily_return": account_info["daily_return"],
            "account_total_value": account_info["total_value"],
            "account_cash": account_info["cash"],
            "account_unrealized": account_info["unrealized"],
        }
        if stock_code in score_info["scores"].index:
            record["score"] = score_info["scores"][stock_code]
            record["score_percentile"] = score_info["percentiles"][stock_code]
            record["score_decile"] = min(int(score_info["percentiles"][stock_code] // 10), 9)
        else:
            record["score"] = None
            record["score_percentile"] = None
            record["score_decile"] = None
        return record


    def _create_closed_record(
        self,
        stock_code: str,
        prev_info: dict,
        realized_pnl_today: float,
        realized_pnl: float,
        commission_today: float,
        dt: Any,
        account_info: dict,
        score_info: dict,
    ) -> dict:
        prev_size = prev_info["position_size"]
        prev_avg_price = prev_info["avg_price"]
        prev_close = prev_info["prev_close"]

        close_price = self._get_close_price_from_daily_trades(stock_code, prev_size)
        if close_price is None:
            close_price = prev_close if prev_close else prev_avg_price

        record = {
            "date": pd.Timestamp(dt).strftime("%Y-%m-%d"),
            "stock_code": stock_code,
            "trade_type": "CLOSE_LONG" if prev_size > 0 else "CLOSE_SHORT",
            "position_size": prev_size,
            "position_change": -prev_size,
            "avg_price": prev_avg_price,
            "current_price": close_price,
            "prev_close": prev_close,
            "weight": 0,
            "market_value": 0,
            "cost_value": abs(prev_size * prev_avg_price),
            "unrealized_pnl": 0,
            "realized_pnl": realized_pnl,
            "realized_pnl_today": realized_pnl_today,
            "commission_today": commission_today,
            "daily_pnl": realized_pnl_today,
            "continuing_pnl": 0,
            "new_position_pnl": 0,
            "current_position_return": 0,
            "continuing_return": 0,
            "new_position_return": 0,
            "total_daily_return": (
                realized_pnl_today / abs(prev_size * prev_close)
                if (prev_size != 0 and prev_close and prev_close > 0)
                else 0
            ),
            "account_daily_return": account_info["daily_return"],
            "account_total_value": account_info["total_value"],
            "account_cash": account_info["cash"],
            "account_unrealized": account_info["unrealized"],
        }
        if stock_code in score_info["scores"].index:
            record["score"] = score_info["scores"][stock_code]
            record["score_percentile"] = score_info["percentiles"][stock_code]
            record["score_decile"] = min(int(score_info["percentiles"][stock_code] // 10), 9)
        else:
            record["score"] = None
            record["score_percentile"] = None
            record["score_decile"] = None
        return record


    def _update_stock_summary_for_long(
        self, summary: dict, position: Any, record: dict, trade_type: str
    ) -> None:
        summary["long_position_size"] = position.size
        summary["long_market_value"] = record["market_value"]
        summary["long_daily_pnl"] = record["daily_pnl"]

    def _update_stock_summary_for_short(
        self, summary: dict, position: Any, record: dict, trade_type: str
    ) -> None:
        summary["short_position_size"] = position.size
        summary["short_market_value"] = record["market_value"]
        summary["short_daily_pnl"] = record["daily_pnl"]


    def _finalize_stock_summary(self, stock_summary: dict) -> None:
        for stock_code, summary in stock_summary.items():
            summary["net_position_size"] = (
                summary["long_position_size"] + summary["short_position_size"]
            )
            summary["net_market_value"] = (
                summary["long_market_value"] + summary["short_market_value"]
            )
            prev_position_size = summary.get("prev_position_size", 0)
            summary["long_position_change"] = summary["long_position_size"] - (
                prev_position_size if prev_position_size > 0 else 0
            )
            summary["short_position_change"] = summary["short_position_size"] - (
                prev_position_size if prev_position_size < 0 else 0
            )
            summary["net_position_change"] = summary["net_position_size"] - prev_position_size
            summary["total_daily_pnl"] = summary["long_daily_pnl"] + summary["short_daily_pnl"]
            summary["total_daily_return"] = self._calculate_total_daily_return(stock_code, summary)


    def _process_current_holdings(
        self,
        dt: Any,
        long_stats: list,
        short_stats: list,
        stock_summary: dict,
        account_info: dict,
        score_info: dict,
        daily_realized_results: dict,
        daily_commission: dict,
    ) -> set:
        current_positions: set[str] = set()

        for data in self.datas:
            position = self.broker.getposition(data)
            if position.size == 0:
                continue

            stock_code = data._name
            current_positions.add(stock_code)
            current_price = data.close[0]

            trade_summary = self.daily_trade_summary.get(stock_code, {})
            trade_type = trade_summary.get("trade_type", "NONE")
            commission_info = daily_commission.get(stock_code, {})
            prev_info_for_pnl = self.prev_positions.get(stock_code, {})
            stock_trades = [
                trade
                for trade in self.daily_trades.get(stock_code, [])
                if trade.get("datetime") == pd.Timestamp(dt).strftime("%Y-%m-%d")
            ]
            daily_trade_commission_total = sum(
                float(trade.get("commission", 0.0) or 0.0) for trade in stock_trades
            )
            sequence_pnl = calculate_trade_sequence_daily_pnl(
                prev_size=float(prev_info_for_pnl.get("position_size", 0.0)),
                prev_avg_price=float(prev_info_for_pnl.get("avg_price", 0.0)),
                prev_close=prev_info_for_pnl.get("prev_close"),
                current_size=float(position.size),
                current_avg_price=float(position.price),
                current_price=float(current_price),
                trades=stock_trades,
            )
            realized_pnl_today = sequence_pnl["realized_pnl_today"]
            realized_pnl_full = sequence_pnl["realized_pnl"]
            if stock_code in stock_summary:
                stock_summary[stock_code]["realized_pnl_today"] += realized_pnl_today

            if trade_type in ["REVERSE_LONG_TO_SHORT", "REVERSE_SHORT_TO_LONG"]:
                prev_info = self.prev_positions[stock_code]
                prev_size = prev_info["position_size"]
                closing_commission = commission_info.get("closing", 0.0)
                closed_record = self._create_closed_record(
                    stock_code,
                    prev_info,
                    realized_pnl_today,
                    realized_pnl_full,
                    closing_commission,
                    dt,
                    account_info,
                    score_info,
                )
                if prev_size > 0:
                    closed_record["direction"] = "LONG_CLOSED"
                    long_stats.append(closed_record)
                    if stock_code in stock_summary:
                        stock_summary[stock_code]["long_daily_pnl"] = realized_pnl_today
                else:
                    closed_record["direction"] = "SHORT_CLOSED"
                    short_stats.append(closed_record)
                    if stock_code in stock_summary:
                        stock_summary[stock_code]["short_daily_pnl"] = realized_pnl_today

                opening_commission = commission_info.get("opening", 0.0)
                new_position_pnl = sequence_pnl["new_position_pnl"]
                daily_pnl = new_position_pnl
                position_record = self._create_position_record(
                    stock_code,
                    position,
                    current_price,
                    dt,
                    trade_type,
                    daily_pnl,
                    0.0,
                    new_position_pnl,
                    0.0,
                    0.0,
                    opening_commission,
                    account_info,
                    score_info,
                )
                position_record["position_change"] = position.size
                position_record["prev_close"] = prev_info["prev_close"]
                position_record["unrealized_pnl"] = new_position_pnl
                position_record["total_daily_return"] = (
                    daily_pnl / abs(position.size * position.price)
                    if (position.size != 0 and position.price > 0)
                    else 0
                )

                if position.size > 0:
                    position_record["direction"] = "LONG"
                    long_stats.append(position_record)
                    if stock_code in stock_summary:
                        stock_summary[stock_code]["long_position_size"] = position.size
                        stock_summary[stock_code]["long_market_value"] = (
                            position.size * current_price
                        )
                        stock_summary[stock_code]["long_daily_pnl"] += new_position_pnl
                else:
                    position_record["direction"] = "SHORT"
                    short_stats.append(position_record)
                    if stock_code in stock_summary:
                        stock_summary[stock_code]["short_position_size"] = position.size
                        stock_summary[stock_code]["short_market_value"] = (
                            position.size * current_price
                        )
                        stock_summary[stock_code]["short_daily_pnl"] += new_position_pnl
            else:
                commission_today = daily_trade_commission_total

                continuing_pnl = sequence_pnl["continuing_pnl"]
                new_position_pnl = sequence_pnl["new_position_pnl"]
                daily_pnl = sequence_pnl["daily_pnl"]

                position_record = self._create_position_record(
                    stock_code,
                    position,
                    current_price,
                    dt,
                    trade_type,
                    daily_pnl,
                    continuing_pnl,
                    new_position_pnl,
                    realized_pnl_today,
                    realized_pnl_full,
                    commission_today,
                    account_info,
                    score_info,
                )

                if position.size > 0:
                    position_record["direction"] = "LONG"
                    long_stats.append(position_record)
                    if stock_code in stock_summary:
                        self._update_stock_summary_for_long(
                            stock_summary[stock_code], position, position_record, trade_type
                        )
                else:
                    position_record["direction"] = "SHORT"
                    short_stats.append(position_record)
                    if stock_code in stock_summary:
                        self._update_stock_summary_for_short(
                            stock_summary[stock_code], position, position_record, trade_type
                        )

        return current_positions


    def _process_closed_holdings(
        self,
        dt: Any,
        long_stats: list,
        short_stats: list,
        stock_summary: dict,
        daily_realized_results: dict,
        current_positions: set,
        account_info: dict,
        score_info: dict,
        daily_commission: dict,
    ) -> None:
        for stock_code, realized_data in daily_realized_results.items():
            if stock_code in current_positions:
                continue

            realized_pnl_today = realized_data.get("realized_pnl_today", None)
            realized_pnl = realized_data.get("realized_pnl", None)
            if realized_pnl_today is None:
                continue

            if stock_code not in self.prev_positions:
                continue

            prev_info = self.prev_positions[stock_code]
            prev_size = prev_info["position_size"]

            commission_info = daily_commission.get(stock_code, {})
            commission_today = commission_info.get("closing", 0.0)

            closed_record = self._create_closed_record(
                stock_code,
                prev_info,
                realized_pnl_today,
                realized_pnl,
                commission_today,
                dt,
                account_info,
                score_info,
            )

            if prev_size > 0:
                closed_record["direction"] = "LONG_CLOSED"
                long_stats.append(closed_record)
                if stock_code in stock_summary:
                    stock_summary[stock_code]["long_daily_pnl"] = realized_pnl_today
            else:
                closed_record["direction"] = "SHORT_CLOSED"
                short_stats.append(closed_record)
                if stock_code in stock_summary:
                    stock_summary[stock_code]["short_daily_pnl"] = realized_pnl_today

            if stock_code in stock_summary:
                stock_summary[stock_code]["realized_pnl_today"] += realized_pnl_today


    def calculate_daily_position_stats(self, dt: Any) -> list[dict]:
        date_str = pd.Timestamp(dt).strftime("%Y-%m-%d")
        self._calculate_daily_trade_summary()

        account_info = self._get_cached_account_info(dt)
        daily_realized_results = self._get_daily_realized_pnl(date_str)
        daily_commission = self._get_daily_commission(date_str)
        score_info = self._get_daily_score_info(dt)

        all_stocks = self._collect_all_involved_stocks(daily_realized_results)
        stock_summary: dict[str, dict] = {}
        for stock_code in all_stocks:
            stock_summary[stock_code] = self._init_stock_summary(
                stock_code,
                date_str,
                daily_realized_results,
                account_info,
                score_info,
            )

        long_stats: list[dict] = []
        short_stats: list[dict] = []

        current_positions = self._process_current_holdings(
            dt,
            long_stats,
            short_stats,
            stock_summary,
            account_info,
            score_info,
            daily_realized_results,
            daily_commission,
        )
        self._process_closed_holdings(
            dt,
            long_stats,
            short_stats,
            stock_summary,
            daily_realized_results,
            current_positions,
            account_info,
            score_info,
            daily_commission,
        )
        self._finalize_stock_summary(stock_summary)

        self.daily_long_stats = long_stats
        self.daily_short_stats = short_stats
        self.daily_stock_summary = list(stock_summary.values())

        self._to_log(
            dt,
            f"📊 每日统计完成 - 多头: {len(long_stats)}只, 空头: {len(short_stats)}只, 股票总数: {len(stock_summary)}只",
        )

        daily_stats = long_stats + short_stats
        return daily_stats


    def save_daily_stats(self, dt: Any) -> None:
        if not self.enable_daily_stats:
            return

        daily_stats = self.calculate_daily_position_stats(dt)
        long_stats = self.daily_long_stats
        short_stats = self.daily_short_stats
        stock_summary = self.daily_stock_summary

        persist = self._persist_path
        os.makedirs(persist, exist_ok=True)

        self._to_log(dt, "=== 三层数据结构统计 ===")
        self._to_log(dt, f"多头持仓/平仓数量: {len(long_stats)}")
        self._to_log(dt, f"空头持仓/平仓数量: {len(short_stats)}")
        self._to_log(dt, f"股票总数: {len(stock_summary)}")

        long_total_daily_pnl = 0.0
        long_commission = 0.0
        if long_stats:
            long_df = pd.DataFrame(long_stats)
            long_holdings = long_df[long_df["direction"] == "LONG"]
            long_closed = long_df[long_df["direction"] == "LONG_CLOSED"]

            long_total_value = long_holdings["market_value"].sum() if not long_holdings.empty else 0
            long_holding_pnl = long_holdings["daily_pnl"].sum() if not long_holdings.empty else 0
            long_closed_pnl = long_closed["daily_pnl"].sum() if not long_closed.empty else 0
            long_total_daily_pnl = long_holding_pnl + long_closed_pnl
            long_unrealized_pnl = (
                long_holdings["unrealized_pnl"].sum() if not long_holdings.empty else 0
            )
            long_commission = (
                long_df["commission_today"].sum() if "commission_today" in long_df.columns else 0.0
            )

            self._to_log(dt, "--- 多头详细统计 ---")
            self._to_log(
                dt,
                f"多头持仓数量: {len(long_holdings)}, 多头平仓数量: {len(long_closed)}",
            )
            self._to_log(dt, f"多头总市值: {long_total_value:.2f}")
            self._to_log(
                dt,
                f"多头当日盈亏: {long_total_daily_pnl:.2f} (持仓: {long_holding_pnl:.2f}, 平仓: {long_closed_pnl:.2f})",
            )
            self._to_log(dt, f"多头未实现盈亏: {long_unrealized_pnl:.2f}")
            self._to_log(dt, f"多头当日佣金: {long_commission:.2f}")

            if "position_change" in long_df.columns:
                long_position_increase = long_df[long_df["position_change"] > 0][
                    "position_change"
                ].sum()
                long_position_decrease = long_df[long_df["position_change"] < 0][
                    "position_change"
                ].sum()
                long_net_change = long_df["position_change"].sum()
                self._to_log(
                    dt,
                    f"多头持仓变化: 净变化={long_net_change:.0f} (增加={long_position_increase:.0f}, 减少={long_position_decrease:.0f})",
                )

            long_df.to_csv(
                os.path.join(
                    persist, f"daily_long_stats_{pd.Timestamp(dt).strftime('%Y%m%d')}.csv"
                ),
                index=False,
            )

        short_total_daily_pnl = 0.0
        short_commission = 0.0
        if short_stats:
            short_df = pd.DataFrame(short_stats)
            short_holdings = short_df[short_df["direction"] == "SHORT"]
            short_closed = short_df[short_df["direction"] == "SHORT_CLOSED"]

            short_total_value = (
                short_holdings["market_value"].sum() if not short_holdings.empty else 0
            )
            short_holding_pnl = short_holdings["daily_pnl"].sum() if not short_holdings.empty else 0
            short_closed_pnl = short_closed["daily_pnl"].sum() if not short_closed.empty else 0
            short_total_daily_pnl = short_holding_pnl + short_closed_pnl
            short_unrealized_pnl = (
                short_holdings["unrealized_pnl"].sum() if not short_holdings.empty else 0
            )
            short_commission = (
                short_df["commission_today"].sum()
                if "commission_today" in short_df.columns
                else 0.0
            )

            self._to_log(dt, "--- 空头详细统计 ---")
            self._to_log(
                dt,
                f"空头持仓数量: {len(short_holdings)}, 空头平仓数量: {len(short_closed)}",
            )
            self._to_log(dt, f"空头总市值: {short_total_value:.2f}")
            self._to_log(
                dt,
                f"空头当日盈亏: {short_total_daily_pnl:.2f} (持仓: {short_holding_pnl:.2f}, 平仓: {short_closed_pnl:.2f})",
            )
            self._to_log(dt, f"空头未实现盈亏: {short_unrealized_pnl:.2f}")
            self._to_log(dt, f"空头当日佣金: {short_commission:.2f}")

            if "position_change" in short_df.columns:
                short_position_increase = short_df[short_df["position_change"] < 0][
                    "position_change"
                ].sum()
                short_position_decrease = short_df[short_df["position_change"] > 0][
                    "position_change"
                ].sum()
                short_net_change = short_df["position_change"].sum()
                self._to_log(
                    dt,
                    f"空头持仓变化: 净变化={short_net_change:.0f} (增加={short_position_increase:.0f}, 减少={short_position_decrease:.0f})",
                )

            short_df.to_csv(
                os.path.join(
                    persist, f"daily_short_stats_{pd.Timestamp(dt).strftime('%Y%m%d')}.csv"
                ),
                index=False,
            )

        if stock_summary:
            summary_df = pd.DataFrame(stock_summary)

            total_stocks = len(summary_df)
            stocks_with_long = (
                len(summary_df[summary_df["long_position_size"] >= 1e-5])
                if "long_position_size" in summary_df.columns
                else 0
            )
            stocks_with_short = (
                len(summary_df[summary_df["short_position_size"] <= -1e-5])
                if "short_position_size" in summary_df.columns
                else 0
            )
            stocks_with_both = (
                len(
                    summary_df[
                        (summary_df["long_position_size"] >= 1e-5)
                        & (summary_df["short_position_size"] <= -1e-5)
                    ]
                )
                if "long_position_size" in summary_df.columns
                and "short_position_size" in summary_df.columns
                else 0
            )

            total_long_pnl = (
                summary_df["long_daily_pnl"].sum()
                if "long_daily_pnl" in summary_df.columns
                else 0.0
            )
            total_short_pnl = (
                summary_df["short_daily_pnl"].sum()
                if "short_daily_pnl" in summary_df.columns
                else 0.0
            )
            total_realized_pnl = (
                summary_df["realized_pnl_today"].sum()
                if "realized_pnl_today" in summary_df.columns
                else 0.0
            )
            total_combined_pnl = (
                summary_df["total_daily_pnl"].sum()
                if "total_daily_pnl" in summary_df.columns
                else 0.0
            )

            self._to_log(dt, "--- 股票综合统计 ---")
            self._to_log(dt, f"总股票数: {total_stocks}")
            self._to_log(dt, f"有多头持仓的股票: {stocks_with_long}")
            self._to_log(dt, f"有空头持仓的股票: {stocks_with_short}")
            self._to_log(dt, f"同时有多空持仓的股票: {stocks_with_both}")
            self._to_log(dt, "综合盈亏汇总:")
            self._to_log(dt, f"  总多头盈亏: {total_long_pnl:.2f}")
            self._to_log(dt, f"  总空头盈亏: {total_short_pnl:.2f}")
            self._to_log(dt, f"  总当日已实现盈亏: {total_realized_pnl:.2f}")
            self._to_log(dt, f"  总综合盈亏: {total_combined_pnl:.2f}")

            if "total_daily_pnl" in summary_df.columns:
                top_gainers = summary_df.nlargest(3, "total_daily_pnl")
                top_losers = summary_df.nsmallest(3, "total_daily_pnl")

                if not top_gainers.empty:
                    self._to_log(dt, "今日盈利最大的3只股票:")
                    for _, row in top_gainers.iterrows():
                        _rate = row["total_daily_return"] if "total_daily_return" in row else 0.0
                        self._to_log(
                            dt,
                            f"  {row['stock_code']}: 盈亏 {row['total_daily_pnl']:.2f}, 收益率 {_rate:.4f}",
                        )

                if not top_losers.empty:
                    self._to_log(dt, "今日亏损最大的3只股票:")
                    for _, row in top_losers.iterrows():
                        _rate = row["total_daily_return"] if "total_daily_return" in row else 0.0
                        self._to_log(
                            dt,
                            f"  {row['stock_code']}: 盈亏 {row['total_daily_pnl']:.2f}, 收益率 {_rate:.4f}",
                        )

            summary_df.to_csv(
                os.path.join(
                    persist, f"daily_stock_summary_{pd.Timestamp(dt).strftime('%Y%m%d')}.csv"
                ),
                index=False,
            )

        if long_stats and short_stats:
            total_daily_pnl = long_total_daily_pnl + short_total_daily_pnl
            self._to_log(dt, f"=== 当日总盈亏: {total_daily_pnl:.2f} ===")
            self._to_log(dt, f"  多头总盈亏: {long_total_daily_pnl:.2f}")
            self._to_log(dt, f"  空头总盈亏: {short_total_daily_pnl:.2f}")

        prev_value = self.prev_total_value if self.prev_total_value else self.broker.startingcash
        actual_value = 0.0
        if long_stats or short_stats:
            account_info = self._get_cached_account_info(dt)
            date_str = pd.Timestamp(dt).strftime("%Y-%m-%d")
            actual_value = account_info["total_value"]

            nav_path = os.path.join(persist, "daily_nav_and_returns.csv")
            if not os.path.exists(nav_path):
                first_line_df = pd.DataFrame(
                    [
                        {
                            "date": self._get_previous_trade_day_safe(dt),
                            "daily_return": 0,
                            "leverage": 2.0,
                        }
                    ]
                )
                first_line_df.to_csv(nav_path, index=False)

            nav_df = pd.read_csv(nav_path)
            if "date" in nav_df.columns:
                nav_df = nav_df[nav_df["date"].notna()].copy()
                if nav_df.empty:
                    nav_df = pd.DataFrame(
                        [
                            {
                                "date": self._get_previous_trade_day_safe(dt),
                                "daily_return": 0,
                                "leverage": 2.0,
                            }
                        ]
                    )
            daily_return = (actual_value / prev_value) - 1 if prev_value else 0.0
            if date_str in nav_df["date"].values:
                nav_df.loc[nav_df["date"] == date_str, "daily_return"] = daily_return
            else:
                new_row = pd.DataFrame([{"date": date_str, "daily_return": daily_return}])
                nav_df = pd.concat([nav_df, new_row], ignore_index=True)
            nav_df.to_csv(nav_path, index=False)

        if long_stats or short_stats:
            total_commission = long_commission + short_commission

            cost_impact_today = 0.0
            short_interest_cost_today = 0.0
            long_financing_cost_today = 0.0
            cash_interest_income_today = 0.0
            annualized_short_interest_rate = 0.0
            _date_str = pd.Timestamp(dt).strftime("%Y-%m-%d")

            today_cost_record = None
            if self.daily_cost_stats:
                today_cost_record = next(
                    (
                        item
                        for item in reversed(self.daily_cost_stats)
                        if item.get("date") == _date_str
                    ),
                    None,
                )

            if today_cost_record:
                cost_impact_today = today_cost_record.get("total_cost_impact", 0.0)
                short_interest_cost_today = today_cost_record.get("total_short_cost", 0.0)
                long_financing_cost_today = today_cost_record.get("long_financing_cost", 0.0)
                cash_interest_income_today = today_cost_record.get("cash_interest_income", 0.0)
                short_market_value = today_cost_record.get("short_market_value", 0.0)
                days = today_cost_record.get("days", 1)
                if short_market_value < 0 and days > 0:
                    annualized_short_interest_rate = (
                        short_interest_cost_today / short_market_value
                    ) * (365 / days)

            total_cost = (
                total_commission
                + short_interest_cost_today
                + long_financing_cost_today
                - cash_interest_income_today
            )
            total_daily_pnl_check = long_total_daily_pnl + short_total_daily_pnl
            theoretical_value = prev_value + total_daily_pnl_check - total_cost
            diff = actual_value - theoretical_value

            self._to_log(dt, "--- 资产核对 ---")
            self._to_log(dt, f"前日总资产: {prev_value:,.2f}")
            self._to_log(dt, f"当日总盈亏: {total_daily_pnl_check:,.2f}")
            self._to_log(
                dt,
                f"当日总成本: {total_cost:,.2f} (佣金: {total_commission:,.2f}, 其它成本影响: {-cost_impact_today:,.2f})",
            )
            self._to_log(dt, f"空头券息成本: {short_interest_cost_today:,.2f}")
            self._to_log(dt, f"多头融资成本: {long_financing_cost_today:,.2f}")
            self._to_log(dt, f"现金利息收入: {cash_interest_income_today:,.2f}")
            if annualized_short_interest_rate < 0:
                self._to_log(dt, f"年化券息率: {annualized_short_interest_rate:.2%}")
            self._to_log(dt, f"理论今日总资产: {theoretical_value:,.2f}")
            self._to_log(dt, f"实际今日总资产: {actual_value:,.2f}")
            self._to_log(dt, f"差异 (实际 - 理论): {diff:,.2f}")
            self._to_log(
                dt,
                f"完整分解: gross_pnl={total_daily_pnl_check:,.2f} "
                f"- commission={total_commission:,.2f} "
                f"- short_borrow={short_interest_cost_today:,.2f} "
                f"- long_financing={long_financing_cost_today:,.2f} "
                f"+ cash_interest={cash_interest_income_today:,.2f} "
                f"= theoretical={theoretical_value:,.2f} "
                f"vs actual={actual_value:,.2f} "
                f"(residual={diff:,.2f})",
            )
            if abs(diff) > 1:
                self._to_log(dt, "⚠️ 警告: 资产核对差异过大! 请检查计算逻辑。")

        if long_stats:
            self.all_long_stats.extend(long_stats)
        if short_stats:
            self.all_short_stats.extend(short_stats)
        if stock_summary:
            self.all_stock_summary.extend(stock_summary)
        if daily_stats:
            legacy_df = pd.DataFrame(daily_stats)
            legacy_df.to_csv(
                os.path.join(
                    persist, f"daily_position_stats_{pd.Timestamp(dt).strftime('%Y%m%d')}.csv"
                ),
                index=False,
            )
            self.daily_position_stats.extend(daily_stats)
        else:
            self._to_log(dt, f"📊 当日持仓统计: {len(daily_stats)} 条记录")

        self.update_prev_positions(dt)

    def _get_previous_trade_day_safe(self, dt: Any) -> str:
        try:
            from factor_client import get_previous_trade_day

            prev = get_previous_trade_day(pd.Timestamp(dt).strftime("%Y-%m-%d"), 1)
            return pd.Timestamp(prev).strftime("%Y-%m-%d")
        except Exception:
            return (pd.Timestamp(dt) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")


    def update_prev_positions(self, dt: Any) -> None:
        if not self.enable_daily_stats:
            self.prev_total_value = self.broker.get_real_value()
            return

        self.prev_positions = {}
        for data in self.datas:
            position = self.broker.getposition(data)
            if position.size != 0:
                stock_code = data._name
                prev_close_price = data.close[0]
                self.prev_positions[stock_code] = {
                    "prev_close": prev_close_price,
                    "position_size": position.size,
                    "avg_price": position.price,
                }
                self._to_log(
                    dt,
                    f"更新持仓记录 {stock_code}: 前日收盘价={prev_close_price:.3f}, "
                    f"仓位={position.size}, 成本价={position.price:.3f}",
                )

        self.prev_total_value = self.broker.get_real_value()

        date_str = pd.Timestamp(dt).strftime("%Y-%m-%d")
        if self.daily_trades:
            self.all_daily_trades[date_str] = self.daily_trades.copy()
        if self.daily_trade_summary:
            self.all_daily_trade_summary[date_str] = self.daily_trade_summary.copy()
        self.daily_trades = {}
        self.daily_trade_summary = {}


    def calculate_daily_costs(
        self,
        dt: Any,
        pos_posi: Any,
        neg_posi: Any,
        total_interest: float,
        closed_daily_interest: float,
        cash_interest: float | None = None,
    ) -> dict | None:
        if self._prev_dt is None:
            return None
        days = (pd.Timestamp(dt) - pd.Timestamp(self._prev_dt)).days
        if days <= 0:
            return None

        current_cash = self.broker.cash
        unrealized_pnl = self.broker.get_unrealized()
        real_value = self.broker.get_real_value()

        cost_breakdown = {
            "date": pd.Timestamp(dt).strftime("%Y-%m-%d"),
            "days": days,
            "cash": current_cash,
            "unrealized_pnl": unrealized_pnl,
            "real_value": real_value,
            "long_market_value": pos_posi.sum() if pos_posi is not None else 0,
            "short_market_value": neg_posi.sum() if neg_posi is not None else 0,
            "short_interest": total_interest,
            "closed_interest": closed_daily_interest,
            "total_short_cost": total_interest + closed_daily_interest,
            "long_financing_cost": (
                pos_posi.sum() * 0.06 / 365 * days if pos_posi is not None else 0
            ),
            "cash_interest_income": 0,
            "prev_real_value": self.prev_real_value if self.prev_real_value else real_value,
            "real_value_change": real_value
            - (self.prev_real_value if self.prev_real_value else real_value),
        }

        if cash_interest is not None:
            cost_breakdown["cash_interest_income"] = cash_interest
        elif unrealized_pnl > 0:
            cost_breakdown["cash_interest_income"] = current_cash * 0.043 / 365 * days
        else:
            cost_breakdown["cash_interest_income"] = (
                (current_cash + unrealized_pnl) * 0.043 / 365 * days
            )

        total_cost_impact = (
            -cost_breakdown["total_short_cost"]
            - cost_breakdown["long_financing_cost"]
            + cost_breakdown["cash_interest_income"]
        )
        cost_breakdown["total_cost_impact"] = total_cost_impact

        self.prev_cash = current_cash
        self.prev_real_value = real_value
        return cost_breakdown


    def save_daily_costs(
        self,
        dt: Any,
        pos_posi: Any,
        neg_posi: Any,
        total_interest: float,
        closed_daily_interest: float,
    ) -> None:
        cost_data = self.calculate_daily_costs(
            dt,
            pos_posi,
            neg_posi,
            total_interest,
            closed_daily_interest,
            cash_interest=self._last_cash_interest,
        )
        if cost_data is not None:
            self.daily_cost_stats.append(cost_data)
            persist = self._persist_path
            os.makedirs(persist, exist_ok=True)
            pd.DataFrame([cost_data]).to_csv(
                os.path.join(
                    persist, f"daily_cost_breakdown_{pd.Timestamp(dt).strftime('%Y%m%d')}.csv"
                ),
                index=False,
            )

            self._to_log(dt, "=== 每日费用明细 ===")
            self._to_log(dt, f"空头券息: {cost_data.get('total_short_cost', 0.0):,.2f}")
            self._to_log(
                dt,
                f"多头融资成本: {cost_data.get('long_financing_cost', 0.0):,.2f}",
            )
            self._to_log(
                dt,
                f"现金利息收入: {cost_data.get('cash_interest_income', 0.0):,.2f}",
            )
            self._to_log(
                dt,
                f"净费用影响: {cost_data.get('total_cost_impact', 0.0):,.2f}",
            )
            self._to_log(
                dt,
                f"净资产变化: {cost_data.get('real_value_change', 0.0):,.2f}",
            )


    def _save_daily_state(self, current_date: Any) -> None:
        assert self.daily_state_path is not None

        try:
            date_str = pd.to_datetime(current_date).strftime("%Y%m%d")
            date_hyphen = pd.to_datetime(current_date).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            logger.debug("Date parse fallback for current_date=%s", current_date)
            date_str = str(current_date).replace("-", "")[:8]
            date_hyphen = str(current_date)[:10]

        state_file = os.path.join(self.daily_state_path, f"state_{date_str}.pkl")

        sm = IncrementalBacktestState(state_file_path=state_file)

        if hasattr(self, "broker"):
            broker = self.broker
            positions: dict[str, dict[str, Any]] = {}
            if hasattr(broker, "positions"):
                for data, pos in broker.positions.items():
                    if pos.size != 0 and hasattr(data, "_name"):
                        positions[data._name] = {
                            "size": pos.size,
                            "price": pos.price,
                            "adjbase": getattr(pos, "adjbase", None),
                        }
            sm.save_broker_state(
                cash=broker.cash,
                value=broker.getvalue() if hasattr(broker, "getvalue") else 0.0,
                positions=positions,
                fundshares=getattr(broker, "_fundshares", 1.0),
                fundval=getattr(broker, "_fundval", 100.0),
            )

        ls_extra: dict[str, Any] = {
            "_schema_version": _LS_INCREMENTAL_SCHEMA_VERSION,
            "_strategy_name": "LongShortStrategy",
            "_long_positions": dict(self._long_positions),
            "_short_positions": {k: dict(v) for k, v in self._short_positions.items()},
            "_short_bond_instrument": {k: list(v) for k, v in self._short_bond_instrument.items()},
            "_is_need_init_position": self._is_need_init_position,
        }
        sm.save_strategy_state(
            prev_dt=str(self._prev_dt) if self._prev_dt else None,
            init_position=self._is_need_init_position,
            max_lever_rate=getattr(self, "max_lever_rate", 0.0),
            closed_daily_interest=self._closed_daily_interest,
            loss_total=getattr(self, "loss_total", 0),
            gain_total=getattr(self, "gain_total", 0),
            prev_total_value=getattr(self, "prev_total_value", None),
            prev_real_value=getattr(self, "prev_real_value", None),
            initial_cash=getattr(self, "initial_cash", None),
            prev_positions=getattr(self, "prev_positions", None),
            extra=ls_extra,
        )


        sm.state["last_date"] = date_hyphen
        os.makedirs(self.daily_state_path, exist_ok=True)
        sm.save_to_file()
        logger.info("Daily state saved (LS): %s", state_file)


    def stop(self) -> None:
        final_value = float(self.broker.getvalue())
        start_value = getattr(self, "_progress_starting_value", None)
        if start_value is None:
            start = getattr(self.broker, "startingcash", None)
            start_value = float(start) if start else final_value
        final_nav = final_value / start_value if start_value else 1.0
        progress_logger.info(
            "回测完成: 共 %d 个调仓日 | 最终净值 %.4f | 输出 %s",
            len(getattr(self, "_progress_seen", ()) or ()),
            final_nav,
            getattr(self, "_persist_path", "") or "(无)",
        )

        if getattr(self, "record_trade_position_log", False):
            self._save_lightweight_reports()

        if not self.enable_daily_stats:
            logger.info("回测结束 (快速模式)")
            return

        logger.info("回测结束，共统计了 %d 条持仓记录", len(self.daily_position_stats))
        persist = self._persist_path
        os.makedirs(persist, exist_ok=True)

        if len(self.position_record) > 0:
            position = pd.concat(self.position_record).set_index("datetime").sort_index()
            position.to_csv(os.path.join(persist, "position_record.csv"))

        if self.daily_position_stats:
            try:
                daily_stats_df = pd.DataFrame(self.daily_position_stats)
                path = os.path.join(persist, "daily_position_stats_summary.csv")
                daily_stats_df.to_csv(path, index=False)
                logger.info("持仓统计汇总已保存: %s", path)
            except Exception as e:
                logger.warning("保存持仓统计时出错: %s", e)

        if hasattr(self, "daily_cost_stats") and self.daily_cost_stats:
            try:
                cost_df = pd.DataFrame(self.daily_cost_stats)
                path = os.path.join(persist, "daily_cost_stats_summary.csv")
                cost_df.to_csv(path, index=False)
                logger.info("费用统计汇总已保存: %s", path)
            except Exception as e:
                logger.warning("保存费用统计时出错: %s", e)

        if hasattr(self, "all_daily_trades") and self.all_daily_trades:
            try:
                trade_records = []
                for date_str, date_trades in self.all_daily_trades.items():
                    for stock_code, trades in date_trades.items():
                        for trade in trades:
                            trade_records.append(
                                {
                                    "date": trade.get("datetime", date_str),
                                    "stock_code": stock_code,
                                    "action": trade.get("action"),
                                    "size": trade.get("size"),
                                    "price": trade.get("price"),
                                    "value": trade.get("value"),
                                    "commission": trade.get("commission", 0.0),
                                }
                            )
                if trade_records:
                    pd.DataFrame(trade_records).to_csv(
                        os.path.join(persist, "daily_trade_summary.csv"),
                        index=False,
                    )
            except Exception as e:
                logger.warning("保存交易记录时出错: %s", e)

        if hasattr(self, "all_daily_trade_summary") and self.all_daily_trade_summary:
            try:
                summary_records = []
                for date_str, date_summary in self.all_daily_trade_summary.items():
                    for stock_code, summary in date_summary.items():
                        summary_record = {
                            "date": date_str,
                            "stock_code": stock_code,
                            "net_opened": summary.get("net_opened", 0),
                            "avg_open_price": summary.get("avg_open_price", 0.0),
                            "total_volume": summary.get("total_volume", 0),
                            "total_value": summary.get("total_value", 0.0),
                        }
                        summary_records.append(summary_record)

                if summary_records:
                    summary_df = pd.DataFrame(summary_records)
                    summary_path = os.path.join(persist, "daily_trade_summary_agg.csv")
                    summary_df.to_csv(summary_path, index=False)
                    logger.info("历史交易汇总已保存: %s", summary_path)
            except Exception as e:
                logger.warning("保存历史交易汇总时出错: %s", e)

        self.export_three_layer_data_to_csv()


    def export_three_layer_data_to_csv(self, output_dir: str | None = None) -> dict:
        output_dir = output_dir or self._persist_path
        os.makedirs(output_dir, exist_ok=True)

        long_file = short_file = summary_file = None
        if hasattr(self, "all_long_stats") and self.all_long_stats:
            long_file = os.path.join(output_dir, "historical_long_stats.csv")
            pd.DataFrame(self.all_long_stats).to_csv(long_file, index=False)
            logger.info("多头统计已导出到: %s", long_file)

        if hasattr(self, "all_short_stats") and self.all_short_stats:
            short_file = os.path.join(output_dir, "historical_short_stats.csv")
            pd.DataFrame(self.all_short_stats).to_csv(short_file, index=False)
            logger.info("空头统计已导出到: %s", short_file)

        if hasattr(self, "all_stock_summary") and self.all_stock_summary:
            summary_file = os.path.join(output_dir, "historical_stock_summary.csv")
            pd.DataFrame(self.all_stock_summary).to_csv(summary_file, index=False)
            logger.info("股票综合统计已导出到: %s", summary_file)

        return {
            "long_stats_file": long_file,
            "short_stats_file": short_file,
            "stock_summary_file": summary_file,
        }


    def _save_lightweight_reports(self) -> None:
        persist = self._persist_path
        os.makedirs(persist, exist_ok=True)

        if self._trade_events:
            pd.DataFrame(self._trade_events).to_csv(
                os.path.join(persist, "trade_events.csv"), index=False
            )

        if self._position_snapshots:
            pd.DataFrame(self._position_snapshots).to_csv(
                os.path.join(persist, "position_snapshot_log.csv"), index=False
            )

        if self._position_snapshots:
            changes = self._compute_position_changes()
            if not changes.empty:
                changes.to_csv(os.path.join(persist, "position_change_log.csv"), index=False)

        audits = getattr(self, "_position_integrity_audits", [])
        if audits:
            pd.DataFrame(audits).to_csv(
                os.path.join(persist, "position_integrity_audit.csv"), index=False
            )
            issues = getattr(self, "_position_integrity_issues", [])
            pd.DataFrame(issues, columns=_POSITION_INTEGRITY_ISSUE_COLUMNS).to_csv(
                os.path.join(persist, "position_integrity_issues.csv"), index=False
            )
            cleanups = getattr(self, "_position_integrity_cleanups", [])
            pd.DataFrame(cleanups, columns=_POSITION_INTEGRITY_CLEANUP_COLUMNS).to_csv(
                os.path.join(persist, "position_integrity_cleanups.csv"), index=False
            )

    def _compute_position_changes(self) -> pd.DataFrame:
        if not self._position_snapshots:
            return pd.DataFrame()

        snap_df = pd.DataFrame(self._position_snapshots)
        dates = sorted(snap_df["date"].unique())
        if len(dates) < 2:
            return pd.DataFrame()

        all_changes: list[dict] = []
        key_cols = ["instrument", "position_side"]

        for i in range(1, len(dates)):
            prev_date = dates[i - 1]
            curr_date = dates[i]
            prev_snap = snap_df[snap_df["date"] == prev_date]
            curr_snap = snap_df[snap_df["date"] == curr_date]

            prev_idx = prev_snap.set_index(key_cols)[["size"]].rename(columns={"size": "prev_size"})
            curr_idx = curr_snap.set_index(key_cols)[["size"]].rename(
                columns={"size": "current_size"}
            )
            merged = prev_idx.join(curr_idx, how="outer").fillna(0)
            merged["delta_size"] = merged["current_size"] - merged["prev_size"]
            merged["date"] = curr_date

            for (inst, pos_side), row in merged.iterrows():
                prev_sz = row["prev_size"]
                curr_sz = row["current_size"]
                if prev_sz == 0 and curr_sz != 0:
                    ctype = "open"
                elif prev_sz != 0 and curr_sz == 0:
                    ctype = "close"
                elif row["delta_size"] != 0:
                    ctype = "change"
                else:
                    ctype = "hold"
                all_changes.append(
                    {
                        "date": curr_date,
                        "instrument": inst,
                        "position_side": pos_side,
                        "prev_size": prev_sz,
                        "current_size": curr_sz,
                        "delta_size": row["delta_size"],
                        "change_type": ctype,
                    }
                )

        return pd.DataFrame(all_changes) if all_changes else pd.DataFrame()

    def _record_position_snapshot(self, dt: Any) -> None:
        if not getattr(self, "record_trade_position_log", False):
            return
        date_str = pd.Timestamp(dt).strftime("%Y-%m-%d")
        for data in self.datas:
            if data._name == "exchange_calendar":
                continue
            position = self.broker.getposition(data)
            if position.size != 0:
                inst = data._name
                side = "long" if position.size > 0 else "short"
                self._position_snapshots.append(
                    {
                        "date": date_str,
                        "instrument": inst,
                        "position_side": side,
                        "size": abs(position.size),
                        "price": data.close[0],
                        "market_value": abs(position.size) * data.close[0],
                    }
                )

    def _record_position_integrity_audit(self, dt: Any, phase: str) -> None:
        if not getattr(self, "record_trade_position_log", False):
            return

        date_str = pd.Timestamp(dt).strftime("%Y-%m-%d")
        if not hasattr(self, "_position_integrity_audits"):
            self._position_integrity_audits = []
        if not hasattr(self, "_position_integrity_issues"):
            self._position_integrity_issues = []
        issues: list[dict[str, Any]] = []
        broker_nonzero_count = 0
        broker_long_count = 0
        broker_short_count = 0
        broker_tiny_le_1e8_count = 0
        broker_tiny_le_1e10_count = 0
        broker_tiny_market_value_le_1_count = 0
        broker_min_abs_size: float | None = None
        broker_max_abs_size: float | None = None

        for data in getattr(self, "datas", []):
            inst = getattr(data, "_name", "")
            if inst == "exchange_calendar":
                continue
            try:
                position = self.broker.getposition(data)
                size = float(getattr(position, "size", 0.0) or 0.0)
            except Exception:
                continue
            if size == 0.0:
                continue
            abs_size = abs(size)
            broker_nonzero_count += 1
            if size > 0:
                broker_long_count += 1
                side = "long"
            else:
                broker_short_count += 1
                side = "short"
            broker_min_abs_size = (
                abs_size if broker_min_abs_size is None else min(broker_min_abs_size, abs_size)
            )
            broker_max_abs_size = (
                abs_size if broker_max_abs_size is None else max(broker_max_abs_size, abs_size)
            )
            try:
                price = float(data.close[0])
            except Exception:
                price = float("nan")
            market_value = abs_size * price if np.isfinite(price) else float("nan")
            if abs_size <= _POSITION_TINY_AUDIT_EPS:
                broker_tiny_le_1e8_count += 1
                issues.append(
                    {
                        "date": date_str,
                        "phase": phase,
                        "issue_type": "broker_tiny_position_le_1e8",
                        "instrument": inst,
                        "position_side": side,
                        "broker_size": size,
                        "broker_market_value": market_value,
                        "strategy_long_size": None,
                        "strategy_short_size": None,
                        "bond_id": None,
                    }
                )
            if abs_size <= _POSITION_FLAT_EPS:
                broker_tiny_le_1e10_count += 1
            if np.isfinite(market_value) and market_value <= _POSITION_DUST_MARKET_VALUE_EPS:
                broker_tiny_market_value_le_1_count += 1
                issues.append(
                    {
                        "date": date_str,
                        "phase": phase,
                        "issue_type": "broker_tiny_market_value_le_1",
                        "instrument": inst,
                        "position_side": side,
                        "broker_size": size,
                        "broker_market_value": market_value,
                        "strategy_long_size": None,
                        "strategy_short_size": None,
                        "bond_id": None,
                    }
                )

        long_positions = getattr(self, "_long_positions", {})
        short_positions = getattr(self, "_short_positions", {})
        bond_to_instrument = getattr(self, "_bond_id_to_instrument", {})

        active_longs: dict[str, float] = {}
        long_tiny_count = 0
        long_min_abs_size: float | None = None
        for inst, raw_size in long_positions.items():
            try:
                size = abs(float(raw_size or 0.0))
            except (TypeError, ValueError):
                continue
            if size == 0.0:
                continue
            long_min_abs_size = size if long_min_abs_size is None else min(long_min_abs_size, size)
            if size <= _POSITION_TINY_AUDIT_EPS:
                long_tiny_count += 1
                issues.append(
                    {
                        "date": date_str,
                        "phase": phase,
                        "issue_type": "strategy_tiny_long_size_le_1e8",
                        "instrument": str(inst),
                        "position_side": "long",
                        "broker_size": None,
                        "broker_market_value": None,
                        "strategy_long_size": size,
                        "strategy_short_size": None,
                        "bond_id": None,
                    }
                )
            if size > _POSITION_FLAT_EPS:
                active_longs[str(inst)] = size

        active_shorts: dict[str, float] = {}
        active_short_bonds = 0
        short_tiny_count = 0
        short_min_abs_size: float | None = None
        for raw_bid, pos in short_positions.items():
            bid = str(raw_bid)
            try:
                size = abs(float(pos.get("size", 0.0) or 0.0))
            except (AttributeError, TypeError, ValueError):
                continue
            if size == 0.0:
                continue
            short_min_abs_size = (
                size if short_min_abs_size is None else min(short_min_abs_size, size)
            )
            inst = str(bond_to_instrument.get(bid, bid))
            if size <= _POSITION_TINY_AUDIT_EPS:
                short_tiny_count += 1
                issues.append(
                    {
                        "date": date_str,
                        "phase": phase,
                        "issue_type": "strategy_tiny_short_size_le_1e8",
                        "instrument": inst,
                        "position_side": "short",
                        "broker_size": None,
                        "broker_market_value": None,
                        "strategy_long_size": None,
                        "strategy_short_size": size,
                        "bond_id": bid,
                    }
                )
            if size > _POSITION_FLAT_EPS:
                active_short_bonds += 1
                active_shorts[inst] = active_shorts.get(inst, 0.0) + size

        overlap_instruments = sorted(set(active_longs) & set(active_shorts))
        for inst in overlap_instruments:
            issues.append(
                {
                    "date": date_str,
                    "phase": phase,
                    "issue_type": "strategy_same_instrument_long_short",
                    "instrument": inst,
                    "position_side": "both",
                    "broker_size": None,
                    "broker_market_value": None,
                    "strategy_long_size": active_longs[inst],
                    "strategy_short_size": active_shorts[inst],
                    "bond_id": None,
                }
            )

        self._position_integrity_issues.extend(issues)
        self._position_integrity_audits.append(
            {
                "date": date_str,
                "phase": phase,
                "broker_nonzero_count": broker_nonzero_count,
                "broker_long_count": broker_long_count,
                "broker_short_count": broker_short_count,
                "broker_tiny_le_1e8_count": broker_tiny_le_1e8_count,
                "broker_tiny_le_1e10_count": broker_tiny_le_1e10_count,
                "broker_tiny_market_value_le_1_count": broker_tiny_market_value_le_1_count,
                "broker_min_abs_size": broker_min_abs_size,
                "broker_max_abs_size": broker_max_abs_size,
                "strategy_long_count": len(active_longs),
                "strategy_short_bond_count": active_short_bonds,
                "strategy_short_instrument_count": len(active_shorts),
                "strategy_long_tiny_le_1e8_count": long_tiny_count,
                "strategy_short_tiny_le_1e8_count": short_tiny_count,
                "strategy_min_abs_long_size": long_min_abs_size,
                "strategy_min_abs_short_size": short_min_abs_size,
                "strategy_same_instrument_long_short_count": len(overlap_instruments),
                "strategy_same_instrument_long_short": ";".join(overlap_instruments),
                "issue_count": len(issues),
            }
        )

    def _strategy_has_active_position_for_instrument(self, inst: str) -> bool:
        try:
            long_size = abs(float(getattr(self, "_long_positions", {}).get(inst, 0.0) or 0.0))
        except (TypeError, ValueError):
            long_size = 0.0
        if long_size > _POSITION_FLAT_EPS:
            return True

        short_positions = getattr(self, "_short_positions", {})
        bond_ids = set(getattr(self, "_short_bond_instrument", {}).get(inst, set()))
        if not bond_ids:
            bond_to_instrument = getattr(self, "_bond_id_to_instrument", {})
            bond_ids = {
                str(bid)
                for bid in short_positions
                if str(bond_to_instrument.get(str(bid), bid)) == inst
            }
        for bid in bond_ids:
            try:
                short_size = abs(float(short_positions.get(bid, {}).get("size", 0.0) or 0.0))
            except (AttributeError, TypeError, ValueError):
                continue
            if short_size > _POSITION_FLAT_EPS:
                return True
        return False

    def _cleanup_flat_broker_dust(
        self,
        data: Any,
        inst: str,
        reason: str,
        dt: Any | None = None,
        execution_price: float | None = None,
    ) -> bool:
        if self._strategy_has_active_position_for_instrument(inst):
            return False
        try:
            position = self.broker.getposition(data)
            size = float(getattr(position, "size", 0.0) or 0.0)
        except Exception:
            return False
        if size == 0.0:
            return False
        if execution_price is None:
            try:
                price = float(data.close[0])
            except Exception:
                price = float("nan")
        else:
            try:
                price = float(execution_price)
            except (TypeError, ValueError):
                price = float("nan")
        market_value = abs(size) * price if np.isfinite(price) else float("nan")
        if not np.isfinite(market_value) or market_value > _POSITION_DUST_MARKET_VALUE_EPS:
            return False

        position_price = float(getattr(position, "price", 0.0) or 0.0)
        cash_adjustment = 0.0

        if hasattr(position, "fix"):
            position.fix(0, 0.0)
        else:
            position.size = 0
            if hasattr(position, "price"):
                position.price = 0.0

        if getattr(self, "record_trade_position_log", False):
            if not hasattr(self, "_position_integrity_cleanups"):
                self._position_integrity_cleanups = []
            if dt is None:
                try:
                    dt = get_today_from_bt(self.datas)
                except Exception:
                    dt = None
            date_str = "" if dt is None else pd.Timestamp(dt).strftime("%Y-%m-%d")
            self._position_integrity_cleanups.append(
                {
                    "date": date_str,
                    "reason": reason,
                    "instrument": inst,
                    "broker_size_before": size,
                    "broker_position_price_before": position_price,
                    "broker_market_value_before": market_value,
                    "broker_cash_adjustment": cash_adjustment,
                    "price": price,
                }
            )
        return True

    def notify_order(self, order: Any) -> None:
        try:
            status_name = order.getstatusname()
        except Exception:
            status_name = str(order.status)

        if order.status not in (order.Completed, order.Partial):
            if status_name not in {"Completed", "Partial", "Submitted", "Accepted", "Created"}:
                try:
                    _today_fail = get_today_from_bt(self.datas)
                    self._to_log(
                        _today_fail,
                        f"{order.data._name} 交易失败 Status: {status_name}",
                    )
                except Exception:
                    pass
            return

        if self.enable_daily_stats:
            stock_code = order.data._name
            today = get_today_from_bt(self.datas)
            trade_record = {
                "action": "sell" if order.issell() else "buy",
                "size": order.executed.size,
                "price": order.executed.price,
                "value": order.executed.value,
                "commission": order.executed.comm,
                "datetime": pd.Timestamp(today).strftime("%Y-%m-%d"),
            }
            if stock_code not in self.daily_trades:
                self.daily_trades[stock_code] = []
            self.daily_trades[stock_code].append(trade_record)

        if getattr(self, "record_trade_position_log", False):
            inst = order.data._name
            today_te = get_today_from_bt(self.datas)
            date_str = pd.Timestamp(today_te).strftime("%Y-%m-%d")
            action = "sell" if order.issell() else "buy"
            if inst in self._long_positions:
                position_side = "long"
            elif inst in self._short_bond_instrument:
                position_side = "short"
            else:
                position_side = "long" if order.isbuy() else "short"
            self._trade_events.append(
                {
                    "date": date_str,
                    "instrument": inst,
                    "side": position_side,
                    "action": action,
                    "size": order.executed.size,
                    "price": order.executed.price,
                    "value": order.executed.value,
                    "commission": order.executed.comm,
                    "order_ref": order.ref,
                    "status": order.getstatusname(),
                    "position_side": position_side,
                }
            )

        try:
            sr_info = order.info["sr"]
        except (KeyError, TypeError):
            sr_info = None
        if not sr_info:
            return

        short_flag = sr_info.get("short", False)

        if not short_flag:
            inst = order.data._name
            real_vol = int(sr_info.get("real_vol", 0))
            today_long = get_today_from_bt(self.datas)
            if order.isbuy() and real_vol > 0:
                self._long_positions[inst] = self._long_positions.get(inst, 0) + real_vol
                none_close = sr_info.get("none_close", "")
                self._to_log(
                    today_long,
                    f"Long: BUY {inst}, Money({order.executed.value:.2f}) "
                    f"order.executed.size({order.executed.size}) "
                    f"order.executed.price({order.executed.price}) "
                    f"real vol {real_vol} none_close {none_close} "
                    f"ref({order.ref}) ",
                )
            elif order.issell():
                self._to_log(
                    today_long,
                    f"Long: SELL {inst}, Money({order.executed.value:.2f}) "
                    f"order.executed.size({order.executed.size}) "
                    f"order.executed.price({order.executed.price}) "
                    f"real vol {real_vol} ref({order.ref})",
                )
                if sr_info.get("close_all", False):
                    self._long_positions.pop(inst, None)
                elif real_vol > 0:
                    cur = self._long_positions.get(inst, 0)
                    new_vol = max(cur - real_vol, 0)
                    if new_vol <= _POSITION_FLAT_EPS:
                        self._long_positions.pop(inst, None)
                    else:
                        self._long_positions[inst] = new_vol
            self._cleanup_flat_broker_dust(
                order.data,
                inst,
                "long_order_fill",
                today_long,
                order.executed.price,
            )
            if status_name == "Partial":
                self._to_log(today_long, "special case >> Partial")
                self._to_log(today_long, f"order ref : {order.ref}")
                self._to_log(today_long, f"stock : {order.data._name}")
                self._to_log(
                    today_long,
                    f"price({order.executed.price}) size({order.executed.size}) "
                    f"value({order.executed.value})",
                )
            return

        bid = str(sr_info.get("id", ""))
        if not bid:
            return

        inst = self._bond_id_to_instrument.get(bid, "")
        log_stockcode = inst or order.data._name
        real_vol = sr_info.get("real_vol", abs(order.executed.size))
        actual_money = abs(order.executed.price * order.executed.size)
        today_short = get_today_from_bt(self.datas)

        if order.issell():
            self._to_log(
                today_short,
                f"Short: SELL {log_stockcode}(id:{bid}), "
                f"Money({order.executed.value:.2f}) real_vol({real_vol}) "
                f"order.executed.size({order.executed.size}) "
                f"order.executed.price({order.executed.price})  "
                f"ref({order.ref})",
            )
            if bid in self._short_positions:
                pos = self._short_positions[bid]
                pos["size"] += real_vol
                pos["money"] += actual_money
                pos["open_price"] = pos["money"] / pos["size"] if pos["size"] else 0
            else:
                self._short_positions[bid] = {
                    "size": real_vol,
                    "money": actual_money,
                    "apply_rate": sr_info.get("apply_rate", 0.0),
                    "open_price": sr_info.get("none_close", order.executed.price),
                }
            if inst:
                if inst not in self._short_bond_instrument:
                    self._short_bond_instrument[inst] = set()
                self._short_bond_instrument[inst].add(bid)
        else:
            interest_for_log: float = 0.0
            if bid in self._short_positions:
                pos = self._short_positions[bid]
                today = get_today_from_bt(self.datas)
                if self._prev_dt is not None:
                    day_diff = (pd.Timestamp(today) - pd.Timestamp(self._prev_dt)).days
                    interest = (
                        pos.get("apply_rate", 0.0)
                        * pos.get("open_price", 0.0)
                        * real_vol
                        * max(day_diff, 0)
                    )
                    self._closed_daily_interest += interest
                    interest_for_log = float(interest)

                remaining_size = float(pos.get("size", 0.0)) - float(real_vol)
                if remaining_size <= _POSITION_FLAT_EPS:
                    del self._short_positions[bid]
                    if inst and inst in self._short_bond_instrument:
                        self._short_bond_instrument[inst].discard(bid)
                        if not self._short_bond_instrument[inst]:
                            del self._short_bond_instrument[inst]
                else:
                    pos["size"] = remaining_size
                    pos["money"] = pos["size"] * pos["open_price"]
            self._to_log(
                today_short,
                f"Short: BUY {log_stockcode}(id:{bid}) "
                f"Money({order.executed.value:.2f}) "
                f"order.executed.size({order.executed.size}) "
                f"INTEREST:({interest_for_log}) real_vol({real_vol}) "
                f"order.executed.price({order.executed.price}) "
                f"ref({order.ref})",
            )

        self._cleanup_flat_broker_dust(
            order.data,
            log_stockcode,
            "short_order_fill",
            today_short,
            order.executed.price,
        )

        if status_name == "Partial":
            self._to_log(today_short, "special case >> Partial")
            self._to_log(today_short, f"order ref : {order.ref}")
            self._to_log(today_short, f"stock : {order.data._name}")
            self._to_log(
                today_short,
                f"price({order.executed.price}) size({order.executed.size}) "
                f"value({order.executed.value})",
            )

        from quant_pro.application.testing.checkpoint_recorder import (
            CheckpointRecorder as _CR_s2c,
        )

        _rec_s2c = _CR_s2c.get()
        if _rec_s2c:
            _today_s2c = get_today_from_bt(self.datas)
            _today_s2c_str = (
                _today_s2c.strftime("%Y-%m-%d")
                if hasattr(_today_s2c, "strftime")
                else str(_today_s2c)
            )
            _instrument_s2c = order.data._name
            _side_s2c = "sell" if order.issell() else "buy"
            _is_short_s2c = short_flag
            _real_vol_s2c = sr_info.get("real_vol", abs(order.executed.size))
            _rec_s2c.record(
                _today_s2c_str,
                "S2C_order_executed",
                instrument=_instrument_s2c,
                side=_side_s2c,
                real_vol=_real_vol_s2c,
                is_short=_is_short_s2c,
                exec_price=float(order.executed.price),
                commission=float(order.executed.comm),
                bt_size=float(order.executed.size),
                long_position_count=len(self._long_positions),
                short_position_count=len(self._short_positions),
            )

    def notify_trade(self, trade: Any) -> None:
        if trade.pnl != 0:
            if not hasattr(self, "loss_total"):
                self.loss_total = 0.0
                self.gain_total = 0.0
            if trade.pnl < 0:
                self.loss_total += abs(trade.pnl)
            else:
                self.gain_total += trade.pnl

            if self.enable_daily_stats:
                today = get_today_from_bt(self.datas)
                trade_type_desc = "完全平仓" if trade.isclosed else "部分平仓"
                self._to_log(
                    today,
                    f"[{trade.data._name}]{trade_type_desc} - 累积盈亏: {trade.pnl:.2f}, "
                    f"累积净盈亏: {trade.pnlcomm:.2f}, "
                    f"仓位: {'LONG' if trade.size > 0 else 'SHORT'}",
                )

    def _remove_delist_stocks(self, dt: Any, dt_next: Any, weight_today: pd.Series) -> None:
        from quant_pro.domain.strategy.price_utils import get_none_close

        delisted_long = []
        for d, p in self.getpositions().items():
            if p.size > 1e-9:
                stock = d._name
                try:
                    next_close = get_none_close(dt_next, stock)
                    if pd.isna(next_close) and (stock.startswith("SH") or stock.startswith("SZ")):
                        delisted_long.append(stock)
                except Exception:
                    pass

        delisted_short = []
        removed_bondid = []
        for bid, _pos in list(self._short_positions.items()):
            try:
                instrument = self._bond_table.loc[int(bid), "instrument"]
            except Exception:
                continue
            try:
                next_close = get_none_close(dt_next, instrument)
                if pd.isna(next_close) and (
                    instrument.startswith("SH") or instrument.startswith("SZ")
                ):
                    delisted_short.append(instrument)
                    removed_bondid.append(bid)
            except Exception:
                pass

        for bid in removed_bondid:
            if bid in self._short_positions:
                del self._short_positions[bid]
                self._to_log(dt, f"空头券 {bid} 退市，已从 _short_positions 移除")

        for stock_name in delisted_long:
            if stock_name in self._long_positions:
                del self._long_positions[stock_name]
                self._to_log(dt, f"多头股票 {stock_name} 退市，已从 _long_positions 移除")

        all_delisted = list(set(delisted_long + delisted_short))
        for stock_name in all_delisted:
            try:
                data = self.getdatabyname(stock_name)
            except Exception:
                continue
            if data is not None and data in self.broker.positions:
                position = self.broker.positions[data]
                if position.size != 0:
                    self._to_log(
                        dt,
                        f"股票 {stock_name} 已退市，强制平仓。"
                        f"仓位: {position.size}, 价格: {position.price}",
                    )
                    position.size = 0

        for stock_name in all_delisted:
            if stock_name in weight_today.index:
                weight_today.drop(stock_name, inplace=True)
                self._to_log(dt, f"已从优化器输入数据中移除退市股票 {stock_name}")

    def _get_short_available_by_id(self, bond_id: Any) -> int:
        if self._bond_table is None:
            return 0
        bid_key = int(bond_id) if str(bond_id).isdigit() else bond_id
        if bid_key in self._bond_table.index:
            return int(self._bond_table.loc[bid_key, "available"])
        return 0

    def _lock_bond_availability(
        self,
        today: Any,
        round1_result: pd.DataFrame,
        total_value: float,
        close_prices: dict[str, float],
    ) -> None:
        bond = self._bond_data
        if bond is None:
            return

        today_str = pd.Timestamp(today).strftime("%Y-%m-%d")

        if today_str in bond.index:
            bond.loc[today_str, "available"] = 0

        short_rows = round1_result[round1_result["weight"] < -1e-10]
        if short_rows.empty:
            return

        for _, row in short_rows.iterrows():
            bond_id = row["instrument"]
            bond_id_int = int(bond_id) if str(bond_id).isdigit() else bond_id

            inst = self._bond_id_to_instrument.get(str(bond_id), str(bond_id))
            adj_price = close_prices.get(inst, 0.0)
            none_close = get_none_close(today_str, inst)
            if none_close is None or pd.isna(none_close) or none_close <= 0:
                none_close = adj_price
            if none_close <= 0:
                continue

            wei = abs(float(row["weight"]))
            target_money = total_value * wei
            target_vol = target_money / none_close

            avail = 0
            if self._bond_table is not None and bond_id_int in self._bond_table.index:
                avail = int(self._bond_table.loc[bond_id_int, "available"])

            _, real_vol = refine_short_sell_vol(inst, target_vol, avail)

            id_mask = bond["id"] == bond_id_int
            if not id_mask.any():
                continue

            est_fail_prob = float(bond.loc[id_mask, "est_fail_prob"].values[0])
            est_available_pct = min(
                float(bond.loc[id_mask, "est_available_percentage"].values[0]), 1.0
            )

            bond.loc[id_mask, "est_fail_prob"] = 0

            random_value = np.random.rand()
            if random_value >= est_fail_prob:
                bond.loc[id_mask, "available"] = real_vol * est_available_pct
            else:
                bond.loc[id_mask, "available"] = 0

            bond.loc[id_mask, "est_available_percentage"] = 1

        self._bond_data = bond[bond["available"] != 0]

    def _run_optimizer_flow(self, today: Any) -> bool:
        self._record_position_snapshot(today)
        self._record_position_integrity_audit(today, "before_rebalance")

        pred = self._prepare_score_payload(today)
        if score_payload_is_empty(pred):
            return False

        from quant_pro.infrastructure.calendar.factor_client_adapter import (
            get_next_trade_day as _get_next_td,
        )

        _is_last_day = (
            self._weight_data is not None
            and not self._weight_data.empty
            and today == pd.to_datetime(self._weight_data.index[-1])
        )
        dt_next = pd.to_datetime(_get_next_td(today.strftime("%Y-%m-%d"), 1))
        try:
            dt_next_next = pd.to_datetime(_get_next_td(dt_next.strftime("%Y-%m-%d"), 1))
        except Exception:
            dt_next_next = dt_next + pd.Timedelta(days=1)
        if not _is_last_day:
            weight_series = self._get_weight_series(today)
            if not weight_series.empty:
                self._remove_delist_stocks(today, dt_next, weight_series)

        position_df = self._get_position_df(today, dt_next, dt_next_next)

        from quant_pro.application.testing.checkpoint_recorder import (
            CheckpointRecorder as _CR_s3b,
        )

        _rec_s3b = _CR_s3b.get()
        if _rec_s3b:
            _today_s3b = today.strftime("%Y-%m-%d") if hasattr(today, "strftime") else str(today)
            _long_count_s3b = len([v for v in self._long_positions.values() if v > 0])
            _short_count_s3b = len(self._short_positions)
            _short_total_size_s3b = sum(p.get("size", 0) for p in self._short_positions.values())
            _rec_s3b.record(
                _today_s3b,
                "S3B_position_for_optimizer",
                position_df=position_df if position_df is not None else pd.DataFrame(),
                long_count=_long_count_s3b,
                short_count=_short_count_s3b,
                short_total_size=_short_total_size_s3b,
                dt_next=str(dt_next) if dt_next is not None else "",
                dt_next_next=str(dt_next_next) if dt_next_next is not None else "",
            )

        short_whole_weight = self._compute_short_whole_weight(today)

        bond = self._bond_data
        if dt_next is not None and dt_next_next is not None and bond is not None and not bond.empty:
            _day_difference = (dt_next_next - dt_next).days + 1
            _today_str = today.strftime("%Y-%m-%d") if hasattr(today, "strftime") else str(today)
            if _today_str in bond.index:
                bond = bond.copy()
                bond.loc[_today_str, "apply_rate"] *= _day_difference
        temp_path = self._temp_path

        if self._is_need_init_position:
            total_value = self.broker.cash
            optimizer = self._optimizer_initial
            if optimizer is None:
                return False

            result = None
            _init_path = getattr(self.p, "initial_position_file_path", None)
            if _init_path and os.path.exists(_init_path):
                result = pd.read_csv(_init_path)
                result["instrument"] = result["instrument"].astype(str)
                import logging as _lg

                _lg.getLogger(__name__).warning(
                    "Read initial position from file: %s (%d rows)", _init_path, len(result)
                )
            else:
                self._attach_filter_pools(optimizer, today)
                result = optimizer.optimize(
                    pred=pred,
                    bond=bond,
                    total_value=total_value,
                    short_whole_weight=short_whole_weight,
                    temp_path=temp_path,
                )

                if result is not None and not result.empty:
                    instruments = [d._name for d in self.datas if d._name != "exchange_calendar"]
                    lock_close_prices = read_close_prices(self, instruments)
                    result["instrument"] = result["instrument"].astype(str)
                    self._lock_bond_availability(today, result, total_value, lock_close_prices)

                    if short_whole_weight != 1.0:
                        self._attach_filter_pools(optimizer, today)
                        result = optimizer.optimize(
                            pred=pred,
                            bond=self._bond_data,
                            total_value=total_value,
                            short_whole_weight=1.0,
                            temp_path=temp_path,
                        )
                        if self._bond_data is not None and "id" in self._bond_data.columns:
                            self._order_bond_source = self._bond_data.set_index(
                                "id", drop=False
                            ).copy()
                        else:
                            self._order_bond_source = self._bond_table
                    else:
                        self._order_bond_source = self._bond_table

                    if _init_path and result is not None and not result.empty:
                        result.to_csv(_init_path, index=False)
        else:
            import os as _os_s0b

            if _os_s0b.environ.get("CHECKPOINT_DEBUG") == "1":
                from quant_pro.application.testing.checkpoint_recorder import (
                    CheckpointRecorder as _CR_s0b,
                )

                _rec_s0b = _CR_s0b.get()
                if _rec_s0b:
                    _today_s0b = (
                        today.strftime("%Y-%m-%d") if hasattr(today, "strftime") else str(today)
                    )
                    _broker_cash_s0b = float(self.broker.cash)
                    _positions_s0b = {}
                    for _d_s0b, _p_s0b in self.getpositions().items():
                        if abs(_p_s0b.size) > 1e-12:
                            _positions_s0b[_d_s0b._name] = {
                                "size": float(_p_s0b.size),
                                "price": float(_p_s0b.price),
                                "close": float(self.getdatabyname(_d_s0b._name).close[0]),
                            }
                    _rec_s0b.record(
                        _today_s0b,
                        "S0B_broker_state",
                        broker_cash=_broker_cash_s0b,
                        positions=_positions_s0b,
                        n_positions=len(_positions_s0b),
                    )

            total_value = self._compute_rebalance_value(today)

            if self.enable_daily_stats:
                _pos_posi = pd.Series(
                    {
                        d._name: p.size * d.close[0]
                        for d, p in self.getpositions().items()
                        if p.size > 1e-9
                    },
                    dtype=float,
                )
                _neg_posi = pd.Series(
                    {
                        d._name: p.size * d.close[0]
                        for d, p in self.getpositions().items()
                        if p.size < -1e-9
                    },
                    dtype=float,
                )
                self.save_daily_costs(
                    today,
                    _pos_posi if not _pos_posi.empty else None,
                    _neg_posi if not _neg_posi.empty else None,
                    self._last_total_interest,
                    self._closed_daily_interest,
                )

            optimizer = self._optimizer_rebalance or self._optimizer_initial
            if optimizer is None:
                return True

            if position_df is not None and not position_df.empty:
                _pos_size = pd.Series(
                    {
                        d._name: p.size * d.close[0]
                        for d, p in self.getpositions().items()
                        if p.size > 1e-9
                    },
                    dtype=float,
                )
                _neg_size = pd.Series(
                    {
                        d._name: p.size * d.close[0]
                        for d, p in self.getpositions().items()
                        if p.size < -1e-9
                    },
                    dtype=float,
                )
                if not _pos_size.empty or not _neg_size.empty:
                    _all_size = pd.concat([_pos_size, _neg_size])
                    for _stockcode, _broker_real_value in _all_size.items():
                        _stock_close = get_none_close(today, _stockcode)
                        if pd.isna(_stock_close) or _stock_close <= 0:
                            continue
                        if _broker_real_value > 0:
                            _real_volume = round(_broker_real_value / (_stock_close * 10)) * 10
                            position_df.loc[position_df["stockcode"] == _stockcode, "volume"] = int(
                                _real_volume
                            )
                            if _real_volume >= 100:
                                self._long_positions[_stockcode] = int(_real_volume)
                        elif _broker_real_value < 0:
                            _id_li = [
                                bid
                                for bid, pos in self._short_positions.items()
                                if self._bond_id_to_instrument.get(str(bid), str(bid)) == _stockcode
                            ]
                            _real_volume = round(_broker_real_value / (_stock_close * 10)) * 10
                            _old_volume = position_df.loc[
                                position_df["stockcode"].isin(_id_li), "volume"
                            ].sum()
                            _volume_rate = int(
                                abs(_real_volume / _old_volume if _old_volume != 0 else 0)
                            )
                            for _bond_id in _id_li:
                                _mask = position_df["stockcode"] == _bond_id
                                position_df.loc[_mask, "volume"] = (
                                    position_df.loc[_mask, "volume"] * _volume_rate
                                )
                                _new_vol = (
                                    position_df.loc[_mask, "volume"].values[0] if _mask.any() else 0
                                )
                                if _new_vol >= 100 and _bond_id in self._short_positions:
                                    self._short_positions[_bond_id]["size"] = int(
                                        self._short_positions[_bond_id].get("size", 0)
                                        * _volume_rate
                                    )

            from quant_pro.application.testing.checkpoint_recorder import CheckpointRecorder as _CR

            _rec = _CR.get()
            if _rec and position_df is not None:
                _today_str = (
                    today.strftime("%Y-%m-%d") if hasattr(today, "strftime") else str(today)
                )
                _is_long = position_df["stockcode"].str.startswith(("SZ", "SH"))
                _rec.record(
                    _today_str,
                    "S0_strategy_position",
                    n_long=int(_is_long.sum()),
                    n_short=int((~_is_long).sum()),
                    long_stocks=sorted(position_df.loc[_is_long, "stockcode"].tolist()),
                    short_stock_ids=sorted(position_df.loc[~_is_long, "stockcode"].tolist()),
                    total_value=float(total_value),
                    position_df=position_df,
                )

            self._attach_filter_pools(optimizer, today)
            result = optimizer.optimize(
                pred=pred,
                bond=bond,
                total_value=total_value,
                position=position_df,
                bond_table=self._bond_table,
                short_whole_weight=short_whole_weight,
                temp_path=temp_path,
            )

            if result is not None and not result.empty:
                result["instrument"] = result["instrument"].astype(str)
                instruments = [d._name for d in self.datas if d._name != "exchange_calendar"]
                lock_close_prices = read_close_prices(self, instruments)
                self._lock_bond_availability(today, result, total_value, lock_close_prices)

                if short_whole_weight != 1.0:
                    self._attach_filter_pools(optimizer, today)
                    result = optimizer.optimize(
                        pred=pred,
                        bond=self._bond_data,
                        total_value=total_value,
                        position=position_df,
                        bond_table=self._bond_table,
                        short_whole_weight=1.0,
                        temp_path=temp_path,
                    )

        if result is None or result.empty:
            return not self._is_need_init_position

        result["instrument"] = result["instrument"].astype(str)

        is_rebalance = not self._is_need_init_position
        if is_rebalance and "yester_weight" in result.columns:
            result["update"] = result["weight"] - result["yester_weight"].fillna(0)
            result["update_money"] = result["update"] * total_value
            result = result[(result["update"] <= -1e-9) | (result["update"] >= 1e-9)]
            if result.empty:
                self._is_need_init_position = False
                return True

            is_stock = result["instrument"].str.startswith(("SZ", "SH"))
            is_bond = ~is_stock

            stock_reduce = result[is_stock & (result["update"] < -1e-9)]
            stock_increase = result[is_stock & (result["update"] > 1e-9)]
            bond_reduce = result[is_bond & (result["update"] > 1e-9)]
            bond_increase = result[is_bond & (result["update"] < -1e-9)]
        else:
            long_result = result[result["weight"] > 1e-10].copy()
            short_result = result[result["weight"] < -1e-10].copy()
            stock_reduce = pd.DataFrame()
            stock_increase = long_result
            bond_reduce = pd.DataFrame()
            bond_increase = short_result
            is_rebalance = False

        from quant_pro.application.testing.checkpoint_recorder import (
            CheckpointRecorder as _CR_s2a,
        )

        _rec_s2a = _CR_s2a.get()
        if _rec_s2a:
            _today_s2a = today.strftime("%Y-%m-%d") if hasattr(today, "strftime") else str(today)
            _rec_s2a.record(
                _today_s2a,
                "S2A_order_plan",
                is_rebalance=is_rebalance,
                stock_reduce_count=len(stock_reduce),
                stock_increase_count=len(stock_increase),
                bond_reduce_count=len(bond_reduce),
                bond_increase_count=len(bond_increase),
                stock_reduce_instruments=sorted(stock_reduce["instrument"].tolist())
                if not stock_reduce.empty
                else [],
                stock_increase_instruments=sorted(stock_increase["instrument"].tolist())
                if not stock_increase.empty
                else [],
                bond_reduce_instruments=sorted(bond_reduce["instrument"].tolist())
                if not bond_reduce.empty
                else [],
                bond_increase_instruments=sorted(bond_increase["instrument"].tolist())
                if not bond_increase.empty
                else [],
            )

        for df in [bond_reduce, bond_increase]:
            if not df.empty and self._bond_id_to_instrument:
                df = df.copy()
                df["bond_id"] = df["instrument"].copy()
                df["instrument"] = df["instrument"].map(
                    lambda x: self._bond_id_to_instrument.get(x, x)
                )

        instruments = [d._name for d in self.datas if d._name != "exchange_calendar"]
        close_prices = read_close_prices(self, instruments)
        current_positions = read_position_sizes(self)




        if is_rebalance and not stock_reduce.empty:
            _dont_sell_stock = self._limitation.get_sell_limit(today)
            if not _dont_sell_stock.empty:
                stock_reduce = stock_reduce[
                    stock_reduce["instrument"].isin(_dont_sell_stock[~_dont_sell_stock].index)
                ]
        if not stock_increase.empty:
            _dont_buy_stock = self._limitation.get_buy_limit(today)
            if not _dont_buy_stock.empty:
                stock_increase = stock_increase[
                    stock_increase["instrument"].isin(_dont_buy_stock[~_dont_buy_stock].index)
                ]

        if self.p.do_long and not stock_reduce.empty:
            _net_sell_count = 0.0
            for _, row in stock_reduce.iterrows():
                inst = str(row["instrument"])
                none_close = get_none_close(today, inst)
                if pd.isna(none_close) or none_close <= 0:
                    none_close = close_prices.get(inst, 0.0)
                if none_close <= 0:
                    continue

                if is_rebalance:
                    target_money = abs(float(row["update_money"]))
                else:
                    target_money = total_value * abs(float(row.get("weight", 0)))
                target_vol = target_money / none_close

                cur_pos = self._long_positions.get(inst, 0)
                if cur_pos > 0:
                    is_close, ok, refined_vol = refine_sell_vol(inst, target_vol, int(cur_pos))
                    if not ok or refined_vol <= 0:
                        self._to_log(
                            today,
                            f"[多]计划卖出失败: {inst} vol({refined_vol}) traget({target_vol})",
                        )
                        continue
                    real_money = refined_vol * none_close
                    data_obj = self.getdatabyname(inst)
                    _bt_price = (
                        data_obj.close[0]
                        if data_obj is not None and hasattr(data_obj, "close")
                        else 0.0
                    )
                    if is_close:
                        sr_info = {"real_vol": refined_vol, "close_all": True}
                        order = self.close(data=data_obj, sr=sr_info)
                        self.record_order_if_preparing(order, "sell", data=data_obj, sr=sr_info)
                        if order is not None:
                            _sr_size = self._long_positions.get(inst, 0)
                            self._to_log(
                                today,
                                f"[多]计划close: {inst} vol({refined_vol}) "
                                f"bt_price({_bt_price}) close price({none_close}) "
                                f"money({real_money}) ref({order.ref}) sr({_sr_size})",
                            )
                        else:
                            self._to_log(
                                today,
                                f"[多]计划close失败: {inst} 没有生成订单, data = {data_obj}",
                            )
                    else:
                        sr_info = {"real_vol": refined_vol}
                        bt_vol = real_money / _bt_price if _bt_price > 0 else refined_vol
                        order = self.sell(data=data_obj, size=bt_vol, sr=sr_info)
                        self.record_order_if_preparing(
                            order, "sell", data=data_obj, size=bt_vol, sr=sr_info
                        )
                        if order is not None:
                            _sr_size = self._long_positions.get(inst, 0)
                            self._to_log(
                                today,
                                f"[多]计划卖出: {inst} vol({refined_vol}) "
                                f"target({target_vol}) bt_price({_bt_price}) "
                                f"bt_vol ({bt_vol}) none_close({none_close}) "
                                f"money({real_money}) ref({order.ref}) "
                                f"sr({_sr_size})",
                            )
                        else:
                            self._to_log(
                                today,
                                f"[多]计划卖出失败: {inst} vol({refined_vol}) traget({target_vol})",
                            )
                    if order is not None:
                        self.order_list.append(order)
                        _net_sell_count += real_money
            self._to_log(today, f"[多]计划净卖出: {_net_sell_count}")

        from quant_pro.application.testing.checkpoint_recorder import CheckpointRecorder as _CR

        _rec = _CR.get()
        if _rec:
            _today_str = today.strftime("%Y-%m-%d") if hasattr(today, "strftime") else str(today)
            _rec.record(
                _today_str,
                "S7_order_execution",
                is_rebalance=is_rebalance,
                n_stock_increase=len(stock_increase),
                n_stock_reduce=len(stock_reduce),
                n_bond_increase=len(bond_increase),
                n_bond_reduce=len(bond_reduce),
                total_value=float(total_value),
                has_yester_weight="yester_weight" in result.columns
                if hasattr(result, "columns")
                else False,
                stock_increase_instruments=sorted(stock_increase["instrument"].tolist())
                if not stock_increase.empty
                else [],
                n_long_positions=len(self._long_positions),
                n_short_positions=len(self._short_positions),
            )

        if self.p.do_long and not stock_increase.empty:
            _net_buy_count = 0.0
            for _, row in stock_increase.iterrows():
                inst = str(row["instrument"])
                none_close = get_none_close(today, inst)
                if pd.isna(none_close) or none_close <= 0:
                    none_close = close_prices.get(inst, 0.0)
                if none_close <= 0:
                    continue

                if is_rebalance:
                    target_money = abs(float(row["update_money"]))
                else:
                    wei = float(row["weight"])
                    target_money = total_value * wei
                target_vol = target_money / none_close
                ok, refined_vol = refine_buy_vol(inst, target_vol)
                if not ok or refined_vol <= 0:
                    self._to_log(
                        today,
                        f"[多]计划买入失败: {inst} vol({refined_vol}) traget({target_vol})",
                    )
                    continue

                real_money = refined_vol * none_close
                sr_info = {
                    "real_vol": refined_vol,
                    "real_money": real_money,
                    "none_close": none_close,
                }
                data_obj = self.getdatabyname(inst)
                _bt_price = (
                    data_obj.close[0]
                    if data_obj is not None and hasattr(data_obj, "close")
                    else 0.0
                )
                bt_vol = real_money / _bt_price if _bt_price > 0 else refined_vol
                order = self.buy(data=data_obj, size=bt_vol, sr=sr_info)
                self.order_list.append(order)
                self.record_order_if_preparing(order, "buy", data=data_obj, size=bt_vol, sr=sr_info)

                if order is not None:
                    self._to_log(
                        today,
                        f"[多]计划买入: {inst} vol({refined_vol}) "
                        f"bt_vol ({bt_vol}) bt_price({_bt_price}) "
                        f"target({target_vol}) none_close({none_close}) "
                        f"money({real_money}) ref({order.ref})",
                    )
                else:
                    self._to_log(
                        today,
                        f"[多]计划买入失败: {inst} vol({refined_vol}) traget({target_vol})",
                    )
                if order is not None:
                    _net_buy_count += real_money
            self._to_log(today, f"[多]计划净买入: {_net_buy_count}")

        if _rec:
            _buy_orders = len(
                [
                    o
                    for o in self.order_list
                    if o is not None and o.isbuy() and o.data._name.startswith(("SZ", "SH"))
                ]
            )
            _sell_orders = len(
                [
                    o
                    for o in self.order_list
                    if o is not None and not o.isbuy() and o.data._name.startswith(("SZ", "SH"))
                ]
            )
            _short_sell_orders = len(
                [
                    o
                    for o in self.order_list
                    if o is not None and not o.isbuy() and not o.data._name.startswith(("SZ", "SH"))
                ]
            )
            _rec.record(
                _today_str,
                "S8_orders_placed",
                n_buy_orders=_buy_orders,
                n_sell_orders=_sell_orders,
                n_short_sell_orders=_short_sell_orders,
                total_orders=len(self.order_list),
                n_none_orders=len([o for o in self.order_list if o is None]),
                n_long_positions_after=len(self._long_positions),
            )

        if self.p.do_short and not bond_reduce.empty:
            _net_redeem_count = 0.0
            _bond_reduce = bond_reduce.copy()
            if self._bond_id_to_instrument and "bond_id" not in _bond_reduce.columns:
                _bond_reduce["bond_id"] = _bond_reduce["instrument"].copy()
                _bond_reduce["instrument"] = _bond_reduce["instrument"].map(
                    lambda x: self._bond_id_to_instrument.get(x, x)
                )

            if is_rebalance:
                _dont_buy_bond = self._limitation.get_short_buy_limit(today)
                if not _dont_buy_bond.empty:
                    _buy_excluded = _bond_reduce[
                        _bond_reduce["instrument"].isin(_dont_buy_bond[_dont_buy_bond].index)
                    ]
                    _bond_reduce = _bond_reduce[
                        _bond_reduce["instrument"].isin(_dont_buy_bond[~_dont_buy_bond].index)
                    ]
                    dt_next = pd.Timestamp(today).strftime("%Y-%m-%d")
                    if not _buy_excluded.empty:
                        self._to_log(
                            today,
                            f"[bond]计划在[{dt_next}]买入排除: "
                            f"{_buy_excluded['instrument'].tolist()}, "
                            f"少买入金额({float(_buy_excluded.get('update_money', pd.Series(dtype=float)).sum())})",
                        )
                    else:
                        self._to_log(
                            today,
                            f"[bond]计划在[{dt_next}]买入无排除",
                        )

            _bond_reduce["stockcode"] = _bond_reduce["instrument"]

            for stockcode, group in _bond_reduce.groupby("stockcode"):
                stockcode = str(stockcode)
                bonds_being_reduced = (
                    group["bond_id"].tolist()
                    if "bond_id" in group.columns
                    else group["instrument"].tolist()
                )
                bonds_held = [
                    bid
                    for bid, pos in self._short_positions.items()
                    if self._bond_id_to_instrument.get(str(bid), str(bid)) == stockcode
                    and pos.get("size", 0) >= 1
                ]

                none_close = get_none_close(today, stockcode)
                if pd.isna(none_close) or none_close <= 0:
                    none_close = close_prices.get(stockcode, 0.0)
                if none_close <= 0:
                    continue

                group_rows = list(group.itertuples(index=False))
                num_bonds = len(group_rows)
                reduced_bt_vol = 0.0
                is_fully_closed = []

                for idx, row in enumerate(group_rows):
                    bond_id = str(getattr(row, "bond_id", getattr(row, "instrument", "")))

                    if is_rebalance and hasattr(row, "update_money"):
                        target_money = abs(float(row.update_money))
                    else:
                        target_money = total_value * abs(float(getattr(row, "weight", 0)))
                    target_vol = target_money / none_close

                    real_short_size = int(self._short_positions.get(bond_id, {}).get("size", 0))
                    cur_pos = current_positions.get(stockcode, 0)
                    if cur_pos >= 0 and real_short_size <= 0:
                        continue
                    posi_vol = real_short_size if real_short_size > 0 else abs(cur_pos)
                    is_close, ok, refined_vol = refine_short_buy_vol(
                        stockcode, target_vol, posi_vol
                    )
                    is_fully_closed.append(is_close)
                    if not ok or refined_vol <= 0:
                        continue

                    real_money = refined_vol * none_close
                    sr_info = {
                        "short": True,
                        "id": bond_id,
                        "real_vol": refined_vol,
                        "real_money": real_money,
                    }
                    data_obj = self.getdatabyname(stockcode)

                    yester_wt_sum = (
                        float(group["yester_weight"].sum())
                        if "yester_weight" in group.columns
                        else 0.0
                    )
                    _left = self._short_positions.get(bond_id, {}).get("size", 0) - refined_vol
                    bt_vol = (
                        real_money / data_obj.close[0] if data_obj.close[0] > 0 else refined_vol
                    )
                    if (
                        all(is_fully_closed)
                        and idx == num_bonds - 1
                        and {str(b) for b in bonds_being_reduced} == {str(b) for b in bonds_held}
                        and yester_wt_sum < -1e-9
                    ):
                        order = self.buy(data=data_obj, size=bt_vol, sr=sr_info)
                        self.record_order_if_preparing(
                            order, "buy", data=data_obj, size=bt_vol, sr=sr_info
                        )
                        if order is not None:
                            self._to_log(
                                today,
                                f"[空]计划close: {stockcode}(id:{bond_id}) "
                                f"vol({refined_vol}) left({_left}) ref({order.ref})",
                            )
                            _net_redeem_count += real_money
                        else:
                            self._to_log(
                                today,
                                f"[空]计划close失败: {stockcode}(id:{bond_id}) 没有生成订单",
                            )
                    else:
                        reduced_bt_vol += bt_vol
                        order = self.buy(data=data_obj, size=bt_vol, sr=sr_info)
                        self.record_order_if_preparing(
                            order, "buy", data=data_obj, size=bt_vol, sr=sr_info
                        )
                        if order is not None:
                            self._to_log(
                                today,
                                f"[空]计划赎回: {stockcode}(id:{bond_id}) "
                                f"vol({refined_vol}) target({target_vol}) "
                                f"left({_left}) ref({order.ref})",
                            )
                            _net_redeem_count += real_money
                        else:
                            self._to_log(
                                today,
                                f"[空]计划赎回失败: {stockcode}(id:{bond_id}) "
                                f"vol({refined_vol}) target({target_vol})",
                            )

                    if order is not None:
                        self.order_list.append(order)

            self._to_log(today, f"[空]计划净赎回: {_net_redeem_count}")

            if self.broker.getcash() < 0:
                self._to_log(today, f"现金不足: {self.broker.getcash()}")

        if self.p.do_short and not bond_increase.empty:
            _bond_increase = bond_increase.copy()
            if self._bond_id_to_instrument and "bond_id" not in _bond_increase.columns:
                _bond_increase["bond_id"] = _bond_increase["instrument"].copy()
                _bond_increase["instrument"] = _bond_increase["instrument"].map(
                    lambda x: self._bond_id_to_instrument.get(x, x)
                )

            dont_sell = self._limitation.get_short_sell_limit(today)
            if not dont_sell.empty:
                _excluded = _bond_increase[
                    ~_bond_increase["instrument"].isin(dont_sell[~dont_sell].index)
                ]
                _bond_increase = _bond_increase[
                    _bond_increase["instrument"].isin(dont_sell[~dont_sell].index)
                ]
                dt_next = pd.Timestamp(today).strftime("%Y-%m-%d")
                if not _excluded.empty:
                    _update_money_col = (
                        _excluded["update_money"]
                        if "update_money" in _excluded.columns
                        else pd.Series(dtype=float)
                    )
                    self._to_log(
                        today,
                        f"[bond]计划在[{dt_next}]卖出排除: "
                        f"{_excluded['instrument'].tolist()}, "
                        f"少卖出金额({float(_update_money_col.sum())})",
                    )
                else:
                    self._to_log(
                        today,
                        f"[bond]计划在[{dt_next}]卖出无排除",
                    )

            if is_rebalance and "update_money" in _bond_increase.columns:
                _net_ss_count = 0.0
                for _, row in _bond_increase.iterrows():
                    inst = str(row["instrument"])
                    bond_id = str(row.get("bond_id", inst))
                    none_close = get_none_close(today, inst)
                    if pd.isna(none_close) or none_close <= 0:
                        none_close = close_prices.get(inst, 0.0)
                    if none_close <= 0:
                        continue

                    target_money = abs(float(row["update_money"]))
                    target_vol = target_money / none_close

                    avail_vol = int(target_vol * 2)
                    if (
                        self._order_bond_source is not None
                        and not self._order_bond_source.empty
                        and "available" in self._order_bond_source.columns
                    ):
                        try:
                            bid_key = int(bond_id) if bond_id.isdigit() else bond_id
                            if bid_key in self._order_bond_source.index:
                                avail_vol = int(self._order_bond_source.loc[bid_key, "available"])
                        except (KeyError, ValueError):
                            pass

                    ok, refined_vol = refine_short_sell_vol(inst, target_vol, avail_vol)
                    if not ok or refined_vol <= 0:
                        self._to_log(
                            today,
                            f"[空]计划卖出失败: {inst}(id:{bond_id}) "
                            f"vol({refined_vol}) traget({target_vol})",
                        )
                        continue

                    real_money = refined_vol * none_close
                    sr_info = {
                        "vol": refined_vol,
                        "short": True,
                        "id": bond_id,
                        "real_vol": refined_vol,
                        "real_money": real_money,
                        "apply_rate": 0.0,
                        "none_close": none_close,
                    }
                    if self._order_bond_source is not None:
                        bond_key = int(bond_id) if str(bond_id).isdigit() else bond_id
                        if bond_key in self._order_bond_source.index:
                            sr_info["apply_rate"] = float(
                                self._order_bond_source.loc[bond_key, "apply_rate"]
                            )

                    data_obj = self.getdatabyname(inst)
                    bt_vol = real_money / data_obj.close[0]
                    order = self.sell(data=data_obj, size=bt_vol, sr=sr_info)
                    self.order_list.append(order)
                    self.record_order_if_preparing(
                        order, "sell", data=data_obj, size=bt_vol, sr=sr_info
                    )

                    if order is not None:
                        self._to_log(
                            today,
                            f"[空]计划卖出: {inst}(id:{bond_id}) "
                            f"vol({refined_vol}) target({target_vol}) "
                            f"close price({none_close}) money({real_money}) "
                            f"ref({order.ref})",
                        )
                    else:
                        self._to_log(
                            today,
                            f"[空]计划卖出失败: {inst}(id:{bond_id}) "
                            f"vol({refined_vol}) traget({target_vol})",
                        )
                    if order is not None:
                        _net_ss_count += real_money
                self._to_log(today, f"[空]计划净卖出: {_net_ss_count}")
            else:
                _short_insts = (
                    _bond_increase["instrument"].astype(str).tolist()
                    if "instrument" in _bond_increase.columns
                    else []
                )
                _none_close_prices = {
                    _inst: _nc
                    for _inst in _short_insts
                    if (_nc := get_none_close(today, _inst)) is not None
                    and not pd.isna(_nc)
                    and _nc > 0
                }
                short_orders = _generate_short_sell_orders(
                    short_targets=_bond_increase,
                    close_prices=close_prices,
                    total_value=total_value,
                    bond_data=self._order_bond_source,
                    none_close_prices=_none_close_prices,
                )
                _net_ss_count_init = 0.0
                for desc in short_orders:
                    inst = desc["instrument"]
                    bond_id = desc.get("bond_id", self._instrument_to_bond_id.get(inst, inst))
                    data = self.getdatabyname(inst)
                    sr_info = {
                        "vol": desc["refined_vol"],
                        "short": True,
                        "id": bond_id,
                        "real_vol": desc["refined_vol"],
                        "real_money": desc["target_money"],
                        "apply_rate": 0.0,
                        "none_close": desc["close_price"],
                    }
                    if self._order_bond_source is not None:
                        bond_key = int(bond_id) if str(bond_id).isdigit() else bond_id
                        if bond_key in self._order_bond_source.index:
                            sr_info["apply_rate"] = float(
                                self._order_bond_source.loc[bond_key, "apply_rate"]
                            )
                    order = self.sell(data=data, size=desc["bt_vol"], sr=sr_info)
                    self.order_list.append(order)
                    self.record_order_if_preparing(
                        order, "sell", data=data, size=desc["bt_vol"], sr=sr_info
                    )
                    if order is not None:
                        self._to_log(
                            today,
                            f"[空]计划卖出: {inst}(id:{bond_id}) "
                            f"vol({desc['refined_vol']}) target({desc['refined_vol']}) "
                            f"close price({desc['close_price']}) "
                            f"money({desc['target_money']}) ref({order.ref})",
                        )
                    else:
                        self._to_log(
                            today,
                            f"[空]计划卖出失败: {inst}(id:{bond_id}) "
                            f"vol({desc['refined_vol']}) traget({desc['refined_vol']})",
                        )
                    if order is not None:
                        _net_ss_count_init += desc["target_money"]
                self._to_log(today, f"[空]计划净卖出: {_net_ss_count_init}")


        import os as _os8

        if _os8.environ.get("CHECKPOINT_DEBUG"):
            import logging as _log8

            _log8.getLogger(__name__).warning(
                "[DEBUG orders] today=%s is_rebalance=%s total_orders=%d "
                "stock_reduce=%d stock_increase=%d bond_reduce=%d bond_increase=%d",
                today,
                is_rebalance,
                len(self.order_list),
                len(stock_reduce),
                len(stock_increase),
                len(bond_reduce),
                len(bond_increase),
            )

        was_init = self._is_need_init_position
        self._is_need_init_position = False

        if was_init:
            self._cash_consumed_this_cycle = True

        from quant_pro.application.testing.checkpoint_recorder import (
            CheckpointRecorder as _CR_s3c,
        )

        _rec_s3c = _CR_s3c.get()
        if _rec_s3c:
            _today_s3c = today.strftime("%Y-%m-%d") if hasattr(today, "strftime") else str(today)
            _rec_s3c.record(
                _today_s3c,
                "S3C_eod_state",
                nav=float(self.broker.getvalue()),
                cash=float(self.broker.getcash()),
                long_position_count=len(self._long_positions),
                short_position_count=len(self._short_positions),
                short_total_size=sum(p.get("size", 0) for p in self._short_positions.values()),
                total_orders_placed=len(self.order_list),
                closed_daily_interest=float(getattr(self, "_closed_daily_interest", 0)),
            )

        return True


    def _progress_side_counts(self) -> tuple[int, int]:
        n_long = 0
        n_short = 0
        for _, p in self.getpositions().items():
            if p.size > 0:
                n_long += 1
            elif p.size < 0:
                n_short += 1
        return n_long, n_short

    def _emit_progress(self, today: Any) -> None:
        today_ts = pd.Timestamp(today).normalize()
        if today_ts in self._progress_seen:
            return
        self._progress_seen.add(today_ts)
        seen = len(self._progress_seen)

        nav_value = float(self.broker.getvalue())
        if self._progress_starting_value is None:
            start = getattr(self.broker, "startingcash", None)
            self._progress_starting_value = float(start) if start else nav_value
        start_value = self._progress_starting_value
        nav = nav_value / start_value if start_value else 1.0

        n_long, n_short = self._progress_side_counts()
        date_str = today_ts.strftime("%Y-%m-%d") if not pd.isna(today_ts) else str(today)

        progress_logger.info(
            "回测进度: %s (%d/%d) | 净值 %.4f | 多 %d 空 %d",
            date_str,
            seen,
            self._progress_total,
            nav,
            n_long,
            n_short,
        )


    def next(self) -> None:
        self._ensure_runtime_state()

        today = get_today_from_bt(self.datas)


        if self.enable_daily_stats and self.initial_cash is None:
            self.initial_cash = self.broker.cash
            self.prev_real_value = self.broker.get_real_value()
            self._to_log(today, f"🏦 记录初始现金: {self.initial_cash:,.2f}")

        self._cash_consumed_this_cycle = False
        try:
            if should_rebalance(today, self._rebalance_dates):
                self._emit_progress(today)
                if self._has_optimizer():
                    _ = bool(self._run_optimizer_flow(today))
                else:
                    self._run_weight_data_fallback(today)

            if self.enable_daily_stats:
                has_any_position = any(
                    self.broker.getposition(d).size != 0
                    for d in self.datas
                    if d._name != "exchange_calendar"
                )
                _today_str = pd.Timestamp(today).strftime("%Y-%m-%d")
                if has_any_position:
                    self._to_log(today, f"📊 交易日结束，统计当日({_today_str})持仓数据")
                else:
                    self._to_log(
                        today,
                        f"⏭️ 交易日结束，当日({_today_str})无当前持仓, 仍写入平仓统计",
                    )
                self.save_daily_stats(today)
            self._record_position_integrity_audit(today, "after_bar")
        finally:
            if getattr(self, "_cash_consumed_this_cycle", False):
                self._prev_dt = today
                self._closed_daily_interest = 0.0
                self._cash_consumed_this_cycle = False

        self.incremental_next(today)

    def _run_weight_data_fallback(self, today: Any) -> None:
        instruments = [d._name for d in self.datas if d._name != "exchange_calendar"]
        close_prices = read_close_prices(self, instruments)
        current_positions = read_position_sizes(self)

        weight_today = self._get_weight_series(today)
        if weight_today.empty:
            return

        long_targets, short_targets = calculate_target_positions(
            weight_today,
            do_long=self.p.do_long,
            do_short=self.p.do_short,
        )

        total_value = self.p.total_value
        order_descriptors = generate_order_list(
            long_targets,
            short_targets,
            current_positions,
            close_prices,
            total_value,
        )

        for desc in order_descriptors:
            inst = desc["instrument"]
            price = desc["close_price"]
            money = desc["target_money"]
            target_weight = desc.get("target_weight", 0.0)

            if price <= 0:
                continue

            is_stranded_close = abs(float(target_weight)) <= 1e-12 and abs(float(money)) <= 1e-12

            if is_stranded_close:
                data = self.getdatabyname(inst)
                held = current_positions.get(inst, 0)
                abs_size = abs(int(held))
                if abs_size == 0:
                    continue
                sr_info = {"vol": abs_size, "close_all": True}
                order = self.close(data=data, sr=sr_info)
                self.order_list.append(order)
                self.record_order_if_preparing(order, desc["side"], data=data, sr=sr_info)
                self._to_log(
                    today,
                    f"计划平仓(脱离权重池): {inst} 量({abs_size})",
                )
                continue

            bt_vol = money / price
            if desc["side"] == "buy":
                sr_info = {"vol": int(bt_vol)}
                data = self.getdatabyname(inst)
                order = self.buy(data=data, size=bt_vol, sr=sr_info)
                self.order_list.append(order)
                self.record_order_if_preparing(order, "buy", data=data, size=bt_vol, sr=sr_info)
                self._to_log(
                    today,
                    f"计划买入: {inst} 量({int(bt_vol)}) 金额({money:.0f})",
                )
            else:
                sr_info = {"vol": int(bt_vol)}
                data = self.getdatabyname(inst)
                order = self.sell(data=data, size=bt_vol, sr=sr_info)
                self.order_list.append(order)
                self.record_order_if_preparing(order, "sell", data=data, size=bt_vol, sr=sr_info)
                self._to_log(
                    today,
                    f"计划卖出: {inst} 量({int(bt_vol)}) 金额({money:.0f})",
                )


class BT_LongShortStockSelectStrategy(LongShortStrategy):
    pass


__all__ = [
    "LongShortStrategy",
    "BT_LongShortStockSelectStrategy",
    "LongShortOptimizerProtocol",
    "should_rebalance",
    "calculate_target_positions",
    "generate_order_list",
    "prepare_score_data",
    "analyze_trade_type",
    "calculate_holding_daily_pnl",
    "finalize_stock_summary",
    "generate_sell_orders",
    "generate_buy_orders",
    "SellOrderPlan",
    "BuyOrderPlan",
    "refine_buy_vol",
    "refine_sell_vol",
    "refine_short_buy_vol",
    "refine_short_sell_vol",
    "get_today_from_bt",
    "get_positions",
    "read_close_prices",
    "read_position_sizes",
    "execute_sell_plans",
    "execute_buy_plans",
    "bt_log",
    "bt_to_log",
]
